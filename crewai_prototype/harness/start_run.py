"""
harness/start_run.py
====================
Start a V3 experiment via the backend API, poll until done, then run diagnostics.
Designed to be called by the assistant in iterative debug loops.

Usage:
    python harness/start_run.py
    python harness/start_run.py --topic "ResNet과 ViT의 CIFAR-100 성능 차이 분석"
    python harness/start_run.py --timeout 3600

Environment:
    Backend must be running at http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Windows cp949 terminals can't encode Unicode spinners
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = "http://localhost:8000"
PYTHON = sys.executable
HARNESS_DIR = Path(__file__).parent
DIAGNOSE = HARNESS_DIR / "diagnose.py"
OUTPUTS_ROOT = HARNESS_DIR.parent / "outputs"

DEFAULT_TOPIC = "ResNet과 ViT의 CIFAR-100 성능 차이 분석"
DEFAULT_TIMEOUT = 7200   # 2 hours — CIFAR-100 multi-iter can exceed 1h
POLL_INTERVAL = 15       # seconds between status checks


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BACKEND}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=60) as resp:
        return json.loads(resp.read())


def _backend_alive() -> bool:
    import urllib.error
    try:
        _get("/")
        return True
    except urllib.error.HTTPError:
        # Server is up but returns 4xx on root path — that's fine
        return True
    except Exception:
        return False


# ── Run lifecycle ─────────────────────────────────────────────────────────────
def start_run(topic: str, goal: str = "", subprocess_timeout: int = 3600) -> str:
    """POST to /api/v1/research and return run_id."""
    payload = {
        "topic": topic,
        "goal": goal or "ResNet18/34와 ViT-Tiny/Small의 CIFAR-100 Top-1 accuracy, 학습속도, 파라미터 효율 비교",
        "domain": "computer vision",
        "max_experiments": 2,
        "time_limit": 90,
        "frameworks": ["PyTorch"],
        "subprocess_timeout": subprocess_timeout,  # per-execution training timeout
    }
    resp = _post("/api/v1/research", payload)
    run_id = resp["run_id"]
    return run_id


def poll_until_done(run_id: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Poll /api/v1/research/{run_id}/status until terminal. Returns final status."""
    deadline = time.time() + timeout
    last_event_count = 0
    spinner = ["-", "\\", "|", "/"]
    tick = 0

    print(f"\n  Polling run {run_id} (timeout={timeout}s, interval={POLL_INTERVAL}s)")
    print(f"  {'-'*55}")

    while time.time() < deadline:
        try:
            status_data = _get(f"/api/v1/research/{run_id}/status")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"\n  Backend unreachable: {exc}. Retrying in {POLL_INTERVAL}s ...")
            time.sleep(POLL_INTERVAL)
            continue

        status = status_data.get("status", "unknown")
        progress = status_data.get("progress", 0)
        n_events = status_data.get("total_events", 0)

        sp = spinner[tick % len(spinner)]
        tick += 1

        new_events = n_events - last_event_count
        last_event_count = n_events

        print(
            f"\r  {sp} [{status:10}] {progress:3}%  events={n_events} (+{new_events})",
            end="",
            flush=True,
        )

        if status in ("completed", "failed", "error"):
            print()  # newline after spinner
            return status

        time.sleep(POLL_INTERVAL)

    print(f"\n  TIMEOUT after {timeout}s")
    return "timeout"


def run_diagnostics(run_id: str) -> bool:
    """Run diagnose.py and return True if all checks pass."""
    print(f"\n{'═'*60}")
    print(f"  Running diagnostics for {run_id}")
    print(f"{'═'*60}")
    result = subprocess.run(
        [PYTHON, str(DIAGNOSE), run_id],
        capture_output=False,   # print directly to stdout
    )
    return result.returncode == 0


def find_latest_run_id() -> str | None:
    dirs = sorted(
        [d for d in OUTPUTS_ROOT.iterdir() if d.is_dir() and d.name.startswith("v3_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return dirs[0].name if dirs else None


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Start a V3 experiment and run diagnostics")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--goal", default="")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="Harness poll timeout in seconds (default: 7200)")
    parser.add_argument("--subprocess-timeout", type=int, default=3600,
                        help="Per-training-run subprocess timeout in seconds (default: 3600)")
    parser.add_argument(
        "--diagnose-only",
        metavar="RUN_ID",
        default=None,
        help="Skip starting a new run; just diagnose this run_id (or 'latest')",
    )
    args = parser.parse_args()

    # Diagnose-only mode
    if args.diagnose_only:
        run_id = find_latest_run_id() if args.diagnose_only == "latest" else args.diagnose_only
        if not run_id:
            print("No runs found.")
            return 1
        passed = run_diagnostics(run_id)
        return 0 if passed else 1

    # Check backend
    print(f"\n  Checking backend at {BACKEND} ...")
    if not _backend_alive():
        print(f"  Backend not reachable. Start it with:")
        print(f"    cd crewai_prototype && python -m uvicorn entrypoints.api:app --port 8000")
        return 1
    print(f"  Backend OK\n")

    # Start run
    print(f"  Topic : {args.topic}")
    print(f"  Goal  : {args.goal or '(auto)'}")
    try:
        run_id = start_run(args.topic, args.goal, subprocess_timeout=args.subprocess_timeout)
    except Exception as exc:
        print(f"  Failed to start run: {exc}")
        return 1
    print(f"  Run started: {run_id}\n")

    # Poll
    final_status = poll_until_done(run_id, args.timeout)
    print(f"\n  Final status: {final_status}")

    # Diagnose
    time.sleep(2)  # let filesystem settle
    passed = run_diagnostics(run_id)

    # Print next-steps hint on failure
    if not passed:
        print("\n  Next steps:")
        print("  1. Read the failing checks above")
        print("  2. Fix the root cause in the pipeline code")
        print("  3. Re-run: python harness/start_run.py")
        print(f"  4. Compare: python harness/diagnose.py --all\n")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
