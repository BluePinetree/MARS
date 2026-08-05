"""CIFAR-10 epoch-cost calibration for MARS pre-registration §3.

Measures per-epoch wall-clock for CIFAR-adapted ResNet-18 / MobileNetV2 under
(a) the conditions of the reference run 230013 (nw=0, bs=32, deterministic, no AMP)
    -> control: should reproduce the known 55.2 s (ResNet-18) / 98.2 s (MobileNetV2)
(b) a throughput-fixed configuration (nw=8, bs=128, AMP, cudnn.benchmark)

Writes JSON to stdout tail and to calibration_result.json.
No training beyond 1 warmup + 1 measured epoch per config.
"""
import json
import os
import platform
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
import torchvision
from torch.utils.data import DataLoader
from torchvision import transforms

DATA_ROOT = os.environ.get("DATA_DIR") or str(Path.home() / ".cache" / "mars_datasets")
OUT = Path(__file__).with_name("calibration_result.json")

MEAN = (0.4914, 0.4822, 0.4465)
STD = (0.2470, 0.2435, 0.2616)


def adapt_resnet18(m):
    """CIFAR stem: 7x7 s2 + maxpool -> 3x3 s1, maxpool removed. total_stride 32 -> 8."""
    m.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
    m.maxpool = nn.Identity()
    return m


def adapt_mobilenet_v2(m):
    """CIFAR: stem conv stride 2->1 AND first stride-2 inverted residual (features[2]) 2->1."""
    m.features[0][0].stride = (1, 1)
    for mod in m.features[2].modules():
        if isinstance(mod, nn.Conv2d) and mod.stride == (2, 2):
            mod.stride = (1, 1)
            break
    return m


def build(name):
    if name == "resnet18":
        m = torchvision.models.resnet18(weights=None, num_classes=10)
        return adapt_resnet18(m)
    m = torchvision.models.mobilenet_v2(weights=None, num_classes=10)
    return adapt_mobilenet_v2(m)


def check_stride(model, name):
    """Assert 32x32 input reaches a 4x4 final feature map (total_stride 8)."""
    model.eval()
    feats = {}
    with torch.no_grad():
        x = torch.zeros(1, 3, 32, 32)
        if name == "resnet18":
            h = model.conv1(x)
            h = model.bn1(h); h = model.relu(h); h = model.maxpool(h)
            h = model.layer1(h); feats["stage1"] = tuple(h.shape[-2:])
            h = model.layer2(h); h = model.layer3(h); h = model.layer4(h)
        else:
            h = model.features(x)
        feats["final"] = tuple(h.shape[-2:])
    model.train()
    return feats


def run_config(name, num_workers, batch_size, amp, deterministic, epochs=2):
    torch.manual_seed(42)
    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    else:
        torch.backends.cudnn.deterministic = False
        torch.backends.cudnn.benchmark = True

    tf = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])
    ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=True, download=False, transform=tf)
    dl = DataLoader(
        ds, batch_size=batch_size, shuffle=True, num_workers=num_workers,
        pin_memory=True, drop_last=True,
        persistent_workers=bool(num_workers), prefetch_factor=4 if num_workers else None,
    )

    dev = torch.device("cuda")
    model = build(name)
    strides = check_stride(model, name)
    model = model.to(dev, memory_format=torch.channels_last if not deterministic else torch.contiguous_format)
    opt = torch.optim.SGD(model.parameters(), lr=0.1, momentum=0.9, weight_decay=5e-4)
    crit = nn.CrossEntropyLoss()
    scaler = torch.amp.GradScaler("cuda", enabled=amp)

    per_epoch = []
    for ep in range(epochs):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for xb, yb in dl:
            xb = xb.to(dev, non_blocking=True)
            if not deterministic:
                xb = xb.contiguous(memory_format=torch.channels_last)
            yb = yb.to(dev, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=amp):
                loss = crit(model(xb), yb)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
        torch.cuda.synchronize()
        per_epoch.append(round(time.perf_counter() - t0, 2))

    del model, dl, ds
    torch.cuda.empty_cache()
    return {"per_epoch_s": per_epoch, "measured_s": per_epoch[-1], "strides": strides}


def main():
    configs = [
        # control: reproduce run 230013 conditions
        ("resnet18",     "control_nw0_bs32_det",   dict(num_workers=0, batch_size=32,  amp=False, deterministic=True)),
        ("mobilenet_v2", "control_nw0_bs32_det",   dict(num_workers=0, batch_size=32,  amp=False, deterministic=True)),
        # throughput-fixed
        ("resnet18",     "fixed_nw8_bs128_amp",    dict(num_workers=8, batch_size=128, amp=True,  deterministic=False)),
        ("mobilenet_v2", "fixed_nw8_bs128_amp",    dict(num_workers=8, batch_size=128, amp=True,  deterministic=False)),
    ]
    out = {
        "env": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "gpu": torch.cuda.get_device_name(0),
        },
        "note": "1 warmup epoch + 1 measured epoch per config. Both models CIFAR-stem-adapted.",
        "configs": {},
    }
    for model_name, tag, kw in configs:
        key = f"{model_name}/{tag}"
        print(f"[calib] running {key} ...", flush=True)
        try:
            r = run_config(model_name, **kw)
            r["settings"] = kw
            out["configs"][key] = r
            print(f"[calib] {key}: measured {r['measured_s']}s/epoch  strides={r['strides']}", flush=True)
        except Exception as exc:
            out["configs"][key] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[calib] {key}: FAILED {exc}", flush=True)

    # projections
    proj = {}
    for tag in ("control_nw0_bs32_det", "fixed_nw8_bs128_amp"):
        vals = [out["configs"].get(f"{m}/{tag}", {}).get("measured_s") for m in ("resnet18", "mobilenet_v2")]
        if all(isinstance(v, (int, float)) for v in vals):
            pair = sum(vals)
            proj[tag] = {
                "pair_s_per_epoch": round(pair, 2),
                "h_200ep_pair": round(pair * 200 / 3600, 2),
                "h_200ep_resnet_only": round(vals[0] * 200 / 3600, 2),
                "h_3rollouts_pair": round(pair * 200 * 3 / 3600, 2),
            }
    out["projections_200_epochs"] = proj
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("[calib] RESULT " + json.dumps(out["projections_200_epochs"], ensure_ascii=False), flush=True)
    print(f"[calib] wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
