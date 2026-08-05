"""Final calibration for MARS pre-registration §3 — the exact recipe to be frozen.

Recipe under test (literature standard for CIFAR-10, 200 epochs):
  SGD lr=0.1 momentum=0.9 wd=5e-4 | CosineAnnealingLR(T_max=200) | bs=128
  RandomCrop(32,pad=4) + HorizontalFlip + Normalize
  train/val split 45000/5000 (val carved from train, seed 42)
  num_workers=8, persistent, pin_memory, prefetch=4
  cudnn.deterministic=True, benchmark=False, no AMP, contiguous format
  CIFAR-adapted stems on BOTH models

Measures: train epoch + per-epoch val pass (the real per-epoch cost).
Properly guarded for Windows spawn. 1 warmup + 2 measured epochs.
"""
import json
import platform
import time
from pathlib import Path

import torch
import torch.nn as nn
import torchvision
from torch.utils.data import DataLoader, Subset
from torchvision import transforms

import os
DATA_ROOT = os.environ.get("DATA_DIR") or str(Path.home() / ".cache" / "mars_datasets")
MEAN = (0.4914, 0.4822, 0.4465)
STD = (0.2470, 0.2435, 0.2616)
EPOCHS_TOTAL = 200
BS_TRAIN, BS_EVAL, NW = 128, 256, 8


def adapt_resnet18(m):
    m.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
    m.maxpool = nn.Identity()
    return m


def adapt_mobilenet_v2(m):
    m.features[0][0].stride = (1, 1)
    for mod in m.features[2].modules():
        if isinstance(mod, nn.Conv2d) and mod.stride == (2, 2):
            mod.stride = (1, 1)
            break
    return m


def build(name):
    if name == "resnet18":
        return adapt_resnet18(torchvision.models.resnet18(weights=None, num_classes=10))
    return adapt_mobilenet_v2(torchvision.models.mobilenet_v2(weights=None, num_classes=10))


def total_stride(model, name):
    model.eval()
    with torch.no_grad():
        x = torch.zeros(1, 3, 32, 32)
        h = model.features(x) if name != "resnet18" else _resnet_fwd(model, x)
    model.train()
    return {"final_spatial": tuple(h.shape[-2:]), "total_stride": 32 // h.shape[-1]}


def _resnet_fwd(m, x):
    h = m.maxpool(m.relu(m.bn1(m.conv1(x))))
    return m.layer4(m.layer3(m.layer2(m.layer1(h))))


def make_splits():
    """val is carved from train with a DIFFERENT transform pipeline (no augmentation).

    random_split alone would leak train augmentation into val, so two dataset
    instances over disjoint index sets are used.
    """
    tf_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])
    tf_eval = transforms.Compose([transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    full_tr = torchvision.datasets.CIFAR10(DATA_ROOT, train=True, download=False, transform=tf_train)
    full_va = torchvision.datasets.CIFAR10(DATA_ROOT, train=True, download=False, transform=tf_eval)
    g = torch.Generator().manual_seed(42)
    perm = torch.randperm(len(full_tr), generator=g).tolist()
    va_idx, tr_idx = perm[:5000], perm[5000:]
    return Subset(full_tr, tr_idx), Subset(full_va, va_idx)


def run(name):
    torch.manual_seed(42)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

    tr_ds, va_ds = make_splits()
    tr = DataLoader(tr_ds, batch_size=BS_TRAIN, shuffle=True, num_workers=NW,
                    pin_memory=True, drop_last=True, persistent_workers=True, prefetch_factor=4)
    va = DataLoader(va_ds, batch_size=BS_EVAL, shuffle=False, num_workers=NW,
                    pin_memory=True, persistent_workers=True, prefetch_factor=4)

    dev = torch.device("cuda")
    model = build(name)
    strides = total_stride(model, name)
    model = model.to(dev)
    opt = torch.optim.SGD(model.parameters(), lr=0.1, momentum=0.9, weight_decay=5e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS_TOTAL)
    crit = nn.CrossEntropyLoss()

    train_s, val_s, lrs = [], [], []
    for ep in range(3):  # 1 warmup + 2 measured
        torch.cuda.synchronize(); t0 = time.perf_counter()
        model.train()
        for xb, yb in tr:
            xb, yb = xb.to(dev, non_blocking=True), yb.to(dev, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            crit(model(xb), yb).backward()
            opt.step()
        torch.cuda.synchronize(); t1 = time.perf_counter()
        model.eval(); correct = 0
        with torch.no_grad():
            for xb, yb in va:
                xb, yb = xb.to(dev, non_blocking=True), yb.to(dev, non_blocking=True)
                correct += (model(xb).argmax(1) == yb).sum().item()
        torch.cuda.synchronize(); t2 = time.perf_counter()
        lrs.append(round(opt.param_groups[0]["lr"], 6))
        sched.step()
        train_s.append(round(t1 - t0, 2)); val_s.append(round(t2 - t1, 2))

    acc = correct / len(va_ds) * 100
    del model, tr, va
    torch.cuda.empty_cache()
    return {
        "train_s_measured": train_s[1:], "val_s_measured": val_s[1:],
        "epoch_s": round(sum(train_s[1:]) / 2 + sum(val_s[1:]) / 2, 2),
        "lr_first3": lrs, "lr_changed": len(set(lrs)) > 1,
        "val_top1_percent_after_3ep": round(acc, 2),
        "strides": strides, "train_size": len(tr_ds), "val_size": len(va_ds),
    }


def main():
    out = {"env": {"python": platform.python_version(), "torch": torch.__version__,
                   "gpu": torch.cuda.get_device_name(0)},
           "recipe": {"optimizer": "SGD", "lr": 0.1, "momentum": 0.9, "weight_decay": 5e-4,
                      "scheduler": "CosineAnnealingLR", "t_max": EPOCHS_TOTAL,
                      "batch_size": BS_TRAIN, "eval_batch_size": BS_EVAL, "num_workers": NW,
                      "amp": False, "cudnn_deterministic": True, "val_split": 0.1},
           "models": {}}
    for m in ("resnet18", "mobilenet_v2"):
        print(f"[final] {m} ...", flush=True)
        out["models"][m] = run(m)
        r = out["models"][m]
        print(f"[final] {m}: {r['epoch_s']}s/epoch (train {r['train_s_measured']} + val {r['val_s_measured']}) "
              f"stride={r['strides']} lr_changed={r['lr_changed']} val@3ep={r['val_top1_percent_after_3ep']}%", flush=True)

    pair = sum(out["models"][m]["epoch_s"] for m in out["models"])
    out["projection"] = {
        "pair_s_per_epoch": round(pair, 2),
        "h_200ep_pair_one_rollout": round(pair * EPOCHS_TOTAL / 3600, 2),
        "h_200ep_9_rollouts": round(pair * EPOCHS_TOTAL * 9 / 3600, 2),
        "h_200ep_9_rollouts_plus_baseline": round(pair * EPOCHS_TOTAL * 10 / 3600, 2),
    }
    Path("calibration_final.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("[final] RESULT " + json.dumps(out["projection"]), flush=True)


if __name__ == "__main__":
    main()
