"""
harness/anchor_run.py
=====================
헤드리스 인프로세스 앵커 러너 (Gate-C).

- uvicorn 서버를 쓰지 않고 PipelineOrchestrator를 인프로세스로 구동한다.
  (ADR-014 Windows asyncio IOCP 프리즈는 "uvicorn 메인 루프 + 백그라운드 스레드"
   조합에서 발생하므로, 서버 없이 파이프라인만 돌리면 구조적으로 회피된다.)
- 파이프라인은 launch_prepared()로 백그라운드 데몬 스레드에서 실행하고,
  메인 스레드가 승인/preflight/guidance 게이트를 즉시 자동 처리한다.
  (HITL 타임아웃 대기 없이 진행)

Usage:
    python harness/anchor_run.py --profile tabular
    python harness/anchor_run.py --topic "..." --goal "..." --timeout 1800
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # crewai_prototype/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 실행 적합 가상환경 보장 (capability 기반) ───────────────────────────────
# 특정 이름의 환경(예: MARS)에 묶지 않는다. 파이프라인 실행에 필요한 패키지를 갖춘
# "적합한" 환경인지 능력(import 가능 여부)으로 판정한다.
#   1) 현재 환경이 적합하면 그대로 진행
#   2) 아니면 설치된 conda 환경들을 탐색해 적합한 환경을 찾아 그 환경으로 재실행
#   3) 적합한 환경이 하나도 없으면 생성 방법을 안내하고 종료
# (crewai/torch 등을 import하기 "전에" 수행)
# 능력 기반 탐지 프리미티브는 core/env_detect.py에서 공유한다(웹 API/phase3도 재사용).
from core.env_detect import (  # noqa: E402
    REQUIRED_MODULES as _REQUIRED_MODULES,
    current_env_suitable as _current_env_suitable,
    probe_python as _probe_python,
    candidate_pythons as _candidate_pythons,
    env_name as _env_name,
    dedup_suitable as _dedup_suitable,
)


def _env_guidance() -> str:
    return (
        "\n[적합한 실행 환경 없음] 이 파이프라인을 실행하려면 다음 패키지가 모두 설치된\n"
        "가상환경이 필요합니다: " + ", ".join(_REQUIRED_MODULES) + " (+ vision용 timm/seaborn, GPU torch).\n"
        f"  현재 실행 환경: {sys.prefix}\n"
        "  설치된 conda 환경 중 적합한 것을 찾지 못했습니다. 아래처럼 새로 만든 뒤 다시 실행하세요:\n\n"
        "    conda create -n mars python=3.10 -y\n"
        "    conda activate mars\n"
        "    # GPU torch (CUDA 11.8 예시 — 하드웨어에 맞게 조정):\n"
        "    pip install torch==2.5.0 torchvision==0.20.0 --index-url https://download.pytorch.org/whl/cu118\n"
        "    # 파이프라인 의존성:\n"
        "    pip install -r crewai_prototype/requirements.txt\n"
        "    pip install timm seaborn\n\n"
        "  생성 후:  <env python> harness/anchor_run.py --profile <preset>\n"
    )


def _requested_env() -> "str | None":
    """`--env <name|path>` 로 명시 지정된 환경을 sys.argv에서 직접 읽는다 (argparse 이전)."""
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--env" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--env="):
            return a.split("=", 1)[1]
    return None


def _choose_env(suitable):
    """적합 환경이 여러 개일 때 번호 선택 메뉴를 띄우고 (name, py)를 반환한다."""
    cur = Path(sys.executable).resolve()
    print("\n[실행 환경 선택] 적합한 가상환경이 여러 개 있습니다. 번호를 고르세요:", flush=True)
    for i, (name, py) in enumerate(suitable, 1):
        tag = " (현재)" if Path(py).resolve() == cur else ""
        print(f"  {i}) {name}{tag}   [{py}]", flush=True)
    while True:
        try:
            raw = input(f"선택 [1-{len(suitable)}] (엔터=1): ").strip()
        except EOFError:
            return suitable[0]
        if raw == "":
            return suitable[0]
        if raw.isdigit() and 1 <= int(raw) <= len(suitable):
            return suitable[int(raw) - 1]
        print("  올바른 번호를 입력하세요.", flush=True)


def _ensure_suitable_env() -> None:
    """적합한 실행 환경을 보장한다.

    - 현재 환경 적합 + 비대화형 + --env 미지정 → 즉시 진행(탐색 생략, 빠름)
    - 그 외에는 적합 환경들을 수집한 뒤:
        * --env 지정 → 그 환경 사용
        * 1개뿐 → 그 환경 사용
        * 대화형 + 2개↑ → 번호 선택 메뉴로 사용자가 선택
        * 비대화형 + 2개↑ → 현재(적합 시) 또는 첫 번째 적합 환경 자동 선택
    - 적합 환경이 하나도 없으면 생성 방법 안내 후 종료
    - 선택된 환경이 현재와 다르면 그 환경으로 재실행(subprocess 대기)
    """
    if os.environ.get("_ENV_REEXEC") == "1":
        return  # 이미 재실행됨 → 무한루프 방지 (선택 환경 신뢰)

    req = _requested_env()
    cur_suitable = _current_env_suitable()
    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())

    # 빠른 경로: 자동화(비대화형)에서 현재 환경이 적합하고 명시 요청도 없으면 그대로.
    if not req and cur_suitable and not interactive:
        return

    if not req and not cur_suitable:
        print("[anchor] 현재 실행 환경이 요구사항을 만족하지 않습니다. 적합한 환경을 탐색합니다...", flush=True)

    # 적합 환경 수집
    cur_py = Path(sys.executable).resolve()
    suitable = []
    if cur_suitable:
        suitable.append((_env_name(cur_py), str(cur_py)))
    for py in _candidate_pythons():
        if _probe_python(py):
            suitable.append((_env_name(py), str(py)))
    suitable = _dedup_suitable(suitable)

    if not suitable:
        print(_env_guidance(), flush=True)
        sys.exit(2)

    # 선택
    if req:
        pick = next(
            (s for s in suitable
             if s[0] == req
             or Path(s[1]).name == req
             or str(Path(s[1]).resolve()) == str(Path(req).resolve())),
            None,
        )
        if pick is None:
            print(f"[anchor] 요청한 환경 '{req}'을(를) 적합 목록에서 찾지 못했습니다.", flush=True)
            print("  적합 환경: " + ", ".join(n for n, _ in suitable), flush=True)
            sys.exit(2)
    elif len(suitable) == 1:
        pick = suitable[0]
    elif interactive:
        pick = _choose_env(suitable)
    else:
        pick = next((s for s in suitable if Path(s[1]).resolve() == cur_py), suitable[0])

    name, py = pick
    if Path(py).resolve() == cur_py:
        return  # 현재 환경에서 진행

    # 적합 환경을 찾았지만 현재와 다르다. 자동 재실행(subprocess 재기동)은 Phase 3의
    # 실험 서브프로세스 스트리밍이 교착되는 문제가 있어, 해당 환경에서 "직접 실행"하도록
    # 명령을 안내하고 종료한다. (claude-code처럼 감지→안내→사용자가 실행)
    argstr = " ".join(sys.argv[1:])
    print("\n[anchor] 현재 환경은 파이프라인 실행에 적합하지 않습니다.", flush=True)
    print(f"  적합한 환경: {name}   [{py}]", flush=True)
    print("  아래 명령으로 그 환경에서 직접 실행하세요:\n", flush=True)
    print(f'    "{py}" harness/anchor_run.py {argstr}\n', flush=True)
    sys.exit(3)


_ensure_suitable_env()

from entrypoints.init import initialize_runtime  # noqa: E402  (MARS 보장 후 import)

# 기본 앵커 태스크: CPU에서 빠르고 timm/GPU 불필요한 tabular 분류
PRESETS = {
    "tabular": {
        "topic": "Titanic 생존자 예측: Logistic Regression vs Random Forest 비교",
        "goal": (
            "scikit-learn Titanic(또는 seaborn titanic) 데이터셋으로 결측치 처리와 "
            "기본 특징공학을 수행하고, Logistic Regression과 Random Forest를 학습해 "
            "정확도(accuracy)와 ROC-AUC를 비교한다. seed는 42로 고정한다. CPU만 사용."
        ),
        "domain": "tabular classification",
    },
    # S5 — Tabular regression (torch 불필요, sklearn 내장 데이터)
    "regression": {
        "topic": "California Housing 가격 예측: 선형 회귀 vs Gradient Boosting",
        "goal": (
            "sklearn.datasets.fetch_california_housing 내장 데이터셋으로 "
            "Linear Regression과 Gradient Boosting Regressor를 학습해 "
            "RMSE, MAE, R²로 예측 정확도를 비교하고 피처 중요도를 분석한다. "
            "train/test split과 seed는 42로 고정한다. CPU만 사용."
        ),
        "domain": "tabular regression",
    },
    # S2 — Vision classification (GPU, CIFAR-100 데이터는 DATA_DIR에 사전 배치됨)
    "vision": {
        "topic": "CIFAR-100 이미지 분류: ViT-tiny vs ResNet-50 성능 비교",
        "goal": (
            "torchvision CIFAR-100 데이터셋(os.environ['DATA_DIR']에 이미 캐시됨, 재다운로드 금지)으로 "
            "timm의 ViT-tiny와 torchvision의 ResNet-50을 학습해 top-1/top-5 accuracy, "
            "학습 시간, 파라미터 수를 비교한다. GPU(CUDA)를 사용하고 각 모델 3 epoch 학습, "
            "seed는 42로 고정한다."
        ),
        "domain": "computer vision",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless anchor run (Gate-C)")
    parser.add_argument("--profile", default="tabular", choices=list(PRESETS.keys()))
    parser.add_argument("--topic", default=None)
    parser.add_argument("--goal", default=None)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--max-experiments", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800, help="전체 타임아웃(초)")
    parser.add_argument("--device", default="auto", help="실험 device: auto|cuda|cpu")
    parser.add_argument("--env", default=None,
                        help="실행에 사용할 가상환경(이름/경로)을 명시 지정 (미지정 시 자동/선택 메뉴)")
    args = parser.parse_args()

    # 실험 서브프로세스 device 결정 → phase3가 MARS_EXPERIMENT_DEVICE 환경변수로 읽음
    device = args.device
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    os.environ["MARS_EXPERIMENT_DEVICE"] = device
    print(f"[anchor] experiment device = {device}", flush=True)

    preset = PRESETS[args.profile]
    research_input = {
        "topic": args.topic or preset["topic"],
        "goal": args.goal or preset["goal"],
        "domain": args.domain or preset["domain"],
        "max_experiments": args.max_experiments,
        "frameworks": ["scikit-learn"],
    }

    services = initialize_runtime()
    coord = services.coordinator

    prepared = coord.prepare_run(research_input)
    run_id = prepared.run_id
    print(f"[anchor] run_id={run_id}", flush=True)
    print(f"[anchor] topic={research_input['topic']}", flush=True)

    coord.launch_prepared(prepared)

    deadline = time.time() + args.timeout
    last_status = None
    while time.time() < deadline:
        # 1) Phase 1 승인 게이트 → 즉시 승인
        ag = services.approval_registry.get(run_id)
        if ag is not None and ag.action == "pending":
            services.approval_registry.resolve(run_id, "approve")
            print("[anchor] plan gate -> auto-approve", flush=True)

        # 2) preflight / repair guidance 게이트 자동 처리
        any_g = services.guidance_registry.get_any(run_id)
        if any_g is not None:
            gate_key, gate = any_g
            if str(gate_key).startswith("preflight_"):
                # 빈 hint로 resolve → clarifier가 기본값 사용, 60초 대기 회피
                services.guidance_registry.resolve(run_id, gate_key, "continue", "")
            else:
                # repair escalation 등은 hands-off 실행에서 skip (무한대기 방지)
                services.guidance_registry.resolve(run_id, gate_key, "skip", "")
                print(f"[anchor] guidance gate -> skip: {gate_key}", flush=True)

        # 3) 종료 상태 확인
        sess = services.session_store.get(run_id)
        status = getattr(sess, "status", None) if sess else None
        if status != last_status:
            print(f"[anchor] status={status}", flush=True)
            last_status = status
        if status in ("completed", "failed", "error", "interrupted"):
            break

        time.sleep(2)
    else:
        print(f"[anchor] TIMEOUT after {args.timeout}s", flush=True)

    sess = services.session_store.get(run_id)
    summary = {
        "run_id": run_id,
        "status": getattr(sess, "status", None) if sess else None,
        "result_summary": getattr(sess, "result_summary", None) if sess else None,
        "error": getattr(sess, "error", None) if sess else None,
        "output_path": getattr(sess, "output_path", None) if sess else None,
    }
    print("[anchor] FINAL " + json.dumps(summary, default=str, ensure_ascii=False), flush=True)
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
