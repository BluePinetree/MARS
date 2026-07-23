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
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # crewai_prototype/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from entrypoints.init import initialize_runtime  # noqa: E402

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
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless anchor run (Gate-C)")
    parser.add_argument("--profile", default="tabular", choices=list(PRESETS.keys()))
    parser.add_argument("--topic", default=None)
    parser.add_argument("--goal", default=None)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--max-experiments", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800, help="전체 타임아웃(초)")
    args = parser.parse_args()

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
