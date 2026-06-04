"""
자율 연구 시스템 진입점 (CLI + FastAPI)

사용법:
  1. CLI 모드:
     python main.py run --topic "..." --goal "..." --domain "..."

  2. API 서버 모드:
     python main.py serve --host 0.0.0.0 --port 8000

  3. 대화형 모드:
     python main.py interactive
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# .env 파일 로드
load_dotenv(PROJECT_ROOT / ".env")


# ============================================================
# CLI 모드
# ============================================================

async def run_cli(args: argparse.Namespace) -> None:
    """CLI 모드로 연구를 실행합니다."""
    from core.research_session import ResearchSession, ResearchConfig

    # 연구 설정 구성
    research_config = ResearchConfig(
        research_topic=args.topic,
        research_goal=args.goal,
        research_domain=args.domain,
        data_path=args.data_path or "",
        data_description=args.data_desc or "",
        max_experiments=args.max_experiments,
        time_limit_minutes=args.time_limit,
        preferred_frameworks=(
            args.frameworks.split(",") if args.frameworks else []
        ),
        output_path=args.output,
    )

    # 필수 필드 검증
    missing = research_config.validate()
    if missing:
        print(f"\n❌ 필수 입력이 누락되었습니다:")
        for m in missing:
            print(f"  - {m}")
        print(f"\n사용 예:")
        print(f'  python main.py run --topic "CIFAR-100 분류" --goal "95% 정확도 달성" --domain "컴퓨터 비전"')
        sys.exit(1)

    # 세션 생성 및 실행
    config_path = args.config if args.config else None
    session = ResearchSession(config_path=config_path)

    print(f"\n🚀 자율 연구 시스템 시작")
    print(f"   주제: {research_config.research_topic}")
    print(f"   목표: {research_config.research_goal}")
    print(f"   분야: {research_config.research_domain}")
    print(f"   최대 실험: {research_config.max_experiments}회")
    print(f"   시간 제한: {research_config.time_limit_minutes}분")
    print(f"{'='*60}\n")

    if args.stream:
        # 스트리밍 모드
        async for event in session.run_stream(research_config):
            event_type = event.get("event_type", "")
            agent = event.get("agent_name", "System")
            content = event.get("content", "")

            if event_type == "SYSTEM_END":
                print(f"\n{'='*60}")
                print(f"🏁 {content}")
                break
    else:
        # 일반 모드
        result = await session.run(research_config)

        print(f"\n{'='*60}")
        print(f"🏁 연구 완료!")
        print(f"   실행 ID: {result['run_id']}")
        print(f"   총 메시지: {result['total_messages']}개")
        print(f"   산출물 경로: {result['output_dir']}")
        print(f"   로그 파일: {result['log_file']}")


# ============================================================
# 대화형 모드
# ============================================================

async def run_interactive(args: argparse.Namespace) -> None:
    """대화형 모드로 연구를 실행합니다."""
    from core.research_session import ResearchSession, ResearchConfig

    print(f"\n{'='*60}")
    print(f"🔬 자율 연구 시스템 (대화형 모드)")
    print(f"{'='*60}")
    print(f"\n연구에 필요한 정보를 입력해 주세요.\n")

    # 필수 정보 수집
    topic = input("📋 연구 주제: ").strip()
    if not topic:
        print("❌ 연구 주제는 필수입니다.")
        sys.exit(1)

    goal = input("🎯 연구 목표: ").strip()
    if not goal:
        print("❌ 연구 목표는 필수입니다.")
        sys.exit(1)

    domain = input("📚 연구 분야: ").strip()
    if not domain:
        print("❌ 연구 분야는 필수입니다.")
        sys.exit(1)

    # 선택 정보 수집
    data_path = input("📁 데이터 경로 (없으면 Enter): ").strip()
    data_desc = input("📝 데이터 설명 (없으면 Enter): ").strip()
    frameworks = input("🔧 선호 프레임워크 (쉼표 구분, 없으면 Enter): ").strip()

    max_exp_str = input("🔢 최대 실험 횟수 (기본 3): ").strip()
    max_exp = int(max_exp_str) if max_exp_str else 3

    time_str = input("⏱️  시간 제한(분) (기본 60): ").strip()
    time_limit = int(time_str) if time_str else 60

    research_config = ResearchConfig(
        research_topic=topic,
        research_goal=goal,
        research_domain=domain,
        data_path=data_path,
        data_description=data_desc,
        max_experiments=max_exp,
        time_limit_minutes=time_limit,
        preferred_frameworks=frameworks.split(",") if frameworks else [],
        output_path=args.output if hasattr(args, "output") else "./outputs",
    )

    print(f"\n{'='*60}")
    print(f"🚀 연구를 시작합니다...")
    print(f"{'='*60}\n")

    config_path = args.config if args.config else None
    session = ResearchSession(config_path=config_path)

    async for event in session.run_stream(research_config):
        event_type = event.get("event_type", "")
        if event_type == "SYSTEM_END":
            print(f"\n{'='*60}")
            print(f"🏁 {event.get('content', '연구 완료')}")
            break


# ============================================================
# FastAPI 서버 모드
# ============================================================

def create_app():
    """FastAPI 애플리케이션을 생성합니다."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel
    from typing import Optional

    app = FastAPI(
        title="자율 연구 시스템 API",
        description="AutoGen 기반 대화형 멀티에이전트 자율 연구 시스템",
        version="0.1.0",
    )

    # CORS 설정
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 활성 세션 저장소
    active_sessions: dict[str, "ResearchSession"] = {}

    # ---- 요청/응답 모델 ----

    class ResearchRequest(BaseModel):
        research_topic: str
        research_goal: str
        research_domain: str
        data_path: str = ""
        data_description: str = ""
        max_experiments: int = 3
        time_limit_minutes: int = 60
        preferred_frameworks: list[str] = []
        output_path: str = "./outputs"
        config_path: Optional[str] = None

    class ResearchResponse(BaseModel):
        run_id: str
        status: str
        total_messages: int
        output_dir: str
        log_file: str

    class StatusResponse(BaseModel):
        status: str
        active_sessions: int
        version: str = "0.1.0"

    # ---- 엔드포인트 ----

    @app.get("/", response_model=StatusResponse)
    async def root():
        return StatusResponse(
            status="running",
            active_sessions=len(active_sessions),
        )

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.post("/api/research/start", response_model=ResearchResponse)
    async def start_research(request: ResearchRequest):
        """연구를 시작합니다 (동기 모드)."""
        from core.research_session import ResearchSession, ResearchConfig

        research_config = ResearchConfig(
            research_topic=request.research_topic,
            research_goal=request.research_goal,
            research_domain=request.research_domain,
            data_path=request.data_path,
            data_description=request.data_description,
            max_experiments=request.max_experiments,
            time_limit_minutes=request.time_limit_minutes,
            preferred_frameworks=request.preferred_frameworks,
            output_path=request.output_path,
        )

        missing = research_config.validate()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"필수 필드 누락: {', '.join(missing)}",
            )

        session = ResearchSession(config_path=request.config_path)
        result = await session.run(research_config)

        return ResearchResponse(
            run_id=result["run_id"],
            status=result["status"],
            total_messages=result["total_messages"],
            output_dir=result["output_dir"],
            log_file=result["log_file"],
        )

    @app.post("/api/research/stream")
    async def stream_research(request: ResearchRequest):
        """연구를 시작합니다 (SSE 스트리밍 모드)."""
        from core.research_session import ResearchSession, ResearchConfig

        research_config = ResearchConfig(
            research_topic=request.research_topic,
            research_goal=request.research_goal,
            research_domain=request.research_domain,
            data_path=request.data_path,
            data_description=request.data_description,
            max_experiments=request.max_experiments,
            time_limit_minutes=request.time_limit_minutes,
            preferred_frameworks=request.preferred_frameworks,
            output_path=request.output_path,
        )

        missing = research_config.validate()
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"필수 필드 누락: {', '.join(missing)}",
            )

        session = ResearchSession(config_path=request.config_path)

        async def event_generator():
            async for event in session.run_stream(research_config):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    @app.get("/api/logs/{run_id}")
    async def get_logs(run_id: str, event_type: str = None, limit: int = 100):
        """특정 실행의 로그를 조회합니다."""
        from core.logger import ResearchLogger

        log_file = Path("./logs") / f"{run_id}.jsonl"
        if not log_file.exists():
            raise HTTPException(status_code=404, detail=f"로그 파일 없음: {run_id}")

        events = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event_type and event.get("event_type") != event_type:
                        continue
                    events.append(event)
                except json.JSONDecodeError:
                    continue

        if limit:
            events = events[-limit:]

        return {"run_id": run_id, "events": events, "total": len(events)}

    @app.get("/api/outputs/{run_id}")
    async def get_outputs(run_id: str):
        """특정 실행의 산출물 목록을 조회합니다."""
        output_dir = Path("./outputs") / run_id
        if not output_dir.exists():
            raise HTTPException(status_code=404, detail=f"산출물 없음: {run_id}")

        files = []
        for f in output_dir.rglob("*"):
            if f.is_file():
                files.append({
                    "path": str(f.relative_to(output_dir)),
                    "size_bytes": f.stat().st_size,
                })

        return {"run_id": run_id, "files": files}

    return app


def run_server(args: argparse.Namespace) -> None:
    """FastAPI 서버를 실행합니다."""
    import uvicorn

    app = create_app()
    print(f"\n🌐 자율 연구 시스템 API 서버 시작")
    print(f"   주소: http://{args.host}:{args.port}")
    print(f"   문서: http://{args.host}:{args.port}/docs")
    print(f"{'='*60}\n")

    uvicorn.run(app, host=args.host, port=args.port)


# ============================================================
# 메인 진입점
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="자율 연구 시스템 (AutoGen 기반 대화형 멀티에이전트)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # CLI 모드 (직접 실행)
  python main.py run \\
    --topic "CIFAR-100 이미지 분류 성능 개선" \\
    --goal "ResNet 대비 2% 이상 정확도 향상" \\
    --domain "컴퓨터 비전" \\
    --data-path "./data/cifar100"

  # 대화형 모드
  python main.py interactive

  # API 서버 모드
  python main.py serve --port 8000

  # 스트리밍 모드
  python main.py run --topic "..." --goal "..." --domain "..." --stream
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="설정 파일 경로 (기본: config.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="실행 모드")

    # --- run 서브커맨드 ---
    run_parser = subparsers.add_parser("run", help="CLI 모드로 연구 실행")
    run_parser.add_argument("--topic", type=str, required=True, help="연구 주제")
    run_parser.add_argument("--goal", type=str, required=True, help="연구 목표")
    run_parser.add_argument("--domain", type=str, required=True, help="연구 분야")
    run_parser.add_argument("--data-path", type=str, default="", help="데이터 경로")
    run_parser.add_argument("--data-desc", type=str, default="", help="데이터 설명")
    run_parser.add_argument("--frameworks", type=str, default="", help="선호 프레임워크 (쉼표 구분)")
    run_parser.add_argument("--max-experiments", type=int, default=3, help="최대 실험 횟수")
    run_parser.add_argument("--time-limit", type=int, default=60, help="시간 제한 (분)")
    run_parser.add_argument("--output", type=str, default="./outputs", help="산출물 경로")
    run_parser.add_argument("--stream", action="store_true", help="스트리밍 모드")

    # --- interactive 서브커맨드 ---
    int_parser = subparsers.add_parser("interactive", help="대화형 모드로 연구 실행")
    int_parser.add_argument("--output", type=str, default="./outputs", help="산출물 경로")

    # --- serve 서브커맨드 ---
    serve_parser = subparsers.add_parser("serve", help="FastAPI 서버 모드")
    serve_parser.add_argument("--host", type=str, default="0.0.0.0", help="서버 호스트")
    serve_parser.add_argument("--port", type=int, default=8000, help="서버 포트")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        asyncio.run(run_cli(args))
    elif args.command == "interactive":
        asyncio.run(run_interactive(args))
    elif args.command == "serve":
        run_server(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
