"""
자율 연구 시스템 (Autonomous Research System) - 메인 진입점.

LangGraph 기반 워크플로우 제어 아키텍처의 프로토타입입니다.
CLI 모드와 FastAPI 서버 모드를 모두 지원합니다.

사용법:
    # CLI 모드 - 동기 실행
    python main.py run --topic "ResNet vs ViT 성능 비교" --domain "컴퓨터 비전"

    # CLI 모드 - 대화형
    python main.py interactive

    # FastAPI 서버 모드
    python main.py serve --host 0.0.0.0 --port 8000

    # 드라이런 (LLM 호출 없이 그래프 구조 검증)
    python main.py dry-run
"""

import argparse
import json
import sys
import uuid
import os
from pathlib import Path
from datetime import datetime


def setup_python_path():
    """프로젝트 루트를 PYTHONPATH에 추가합니다."""
    project_root = Path(__file__).parent.resolve()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


setup_python_path()


# ──────────────────────────────────────────────
# CLI 모드
# ──────────────────────────────────────────────

def cmd_run(args):
    """동기 모드로 연구 워크플로우를 실행합니다."""
    from config.settings import load_settings
    from graph.state import ResearchInput, create_initial_state
    from graph.builder import build_graph
    from tools import create_tools
    from utils.logger import ResearchLogger

    settings = load_settings(args.config)

    session_id = f"session_{uuid.uuid4().hex[:8]}"
    run_id = f"run_{uuid.uuid4().hex[:8]}"

    print("=" * 60)
    print("  자율 연구 시스템 (LangGraph Prototype)")
    print("=" * 60)
    print(f"  세션 ID : {session_id}")
    print(f"  실행 ID : {run_id}")
    print(f"  연구 주제: {args.topic}")
    print(f"  연구 분야: {args.domain}")
    print(f"  목표 정확도: {args.target_accuracy}")
    print("=" * 60)

    # 로거 생성
    log_dir = Path(args.output) / "logs" / session_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(log_dir / f"{run_id}.jsonl")

    research_logger = ResearchLogger(
        session_id=session_id,
        run_id=run_id,
        log_path=log_path,
    )

    # 도구 생성
    tools = create_tools(settings)
    print(f"\n[도구 상태]")
    print(f"  Pinecone : {'연결됨' if tools['pinecone'].is_available else '폴백 모드'}")
    print(f"  Docker   : {'연결됨' if tools['docker'].is_available else '폴백 모드'}")
    print(f"  W&B      : {'연결됨' if tools['wandb'].is_available else '폴백 모드'}")

    # 설정 오버라이드
    if args.target_accuracy:
        settings.target_accuracy = args.target_accuracy

    # 그래프 빌드
    print("\n[그래프 빌드 중...]")
    graph = build_graph(
        settings=settings,
        logger=research_logger,
        pinecone_tool=tools["pinecone"],
        docker_tool=tools["docker"],
        wandb_tool=tools["wandb"],
    )
    print("[그래프 빌드 완료]")

    # 연구 입력 생성
    research_input = ResearchInput(
        research_topic=args.topic,
        research_goal=args.goal or f"{args.topic}에 대한 체계적 실험 및 분석",
        research_domain=args.domain,
        data_path=args.data_path or "",
        output_path=args.output,
        constraints={
            "max_experiments": args.max_experiments,
            "preferred_frameworks": args.frameworks.split(",") if args.frameworks else ["PyTorch"],
        },
    )

    initial_state = create_initial_state(
        research_input,
        session_id,
        run_id,
        max_loops=settings.max_debug_loops,
        context_char_budget=settings.context_char_budget,
        context_token_budget=settings.context_token_budget,
        compact_max_chars=settings.compact_max_chars,
    )

    # 워크플로우 실행
    print("\n" + "=" * 60)
    print("  워크플로우 실행 시작")
    print("=" * 60 + "\n")

    try:
        final_state = graph.invoke(initial_state)

        print("\n" + "=" * 60)
        print("  워크플로우 실행 완료")
        print("=" * 60)
        print(f"  상태     : {final_state.get('status', 'unknown')}")
        print(f"  목표 달성: {'예' if final_state.get('meets_target') else '아니오'}")
        print(f"  최고 메트릭: {final_state.get('best_metrics', {})}")
        print(f"  실험 횟수: {len(final_state.get('experiment_results', []))}")
        print(f"  보고서   : {final_state.get('report_path', 'N/A')}")
        print(f"  로그     : {log_path}")
        print(f"  단계 이력: {' → '.join(final_state.get('phase_history', []))}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n[사용자에 의해 중단됨]")
        sys.exit(1)
    except Exception as e:
        print(f"\n[에러] 워크플로우 실행 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_interactive(args):
    """대화형 모드로 연구 워크플로우를 실행합니다."""
    print("=" * 60)
    print("  자율 연구 시스템 - 대화형 모드")
    print("=" * 60)
    print("  연구 주제와 설정을 입력하면 자율적으로 실험을 수행합니다.")
    print("  종료하려면 'quit' 또는 'exit'를 입력하세요.")
    print("=" * 60 + "\n")

    # 연구 주제 입력
    topic = input("📋 연구 주제를 입력하세요: ").strip()
    if topic.lower() in ("quit", "exit"):
        return

    domain = input("🔬 연구 분야를 입력하세요 (예: 컴퓨터 비전, NLP): ").strip() or "일반"
    goal = input("🎯 연구 목표를 입력하세요 (Enter로 자동 설정): ").strip()
    data_path = input("📁 데이터 경로를 입력하세요 (Enter로 건너뛰기): ").strip()
    output_path = input("📂 출력 경로를 입력하세요 (기본: ./outputs): ").strip() or "./outputs"

    target_str = input("📊 목표 정확도를 입력하세요 (기본: 0.85): ").strip()
    target_accuracy = float(target_str) if target_str else 0.85

    # LLM 설정 확인
    print("\n[에이전트별 LLM 설정]")
    print("  config.yaml에서 에이전트별 LLM 모델을 설정할 수 있습니다.")
    print("  현재 설정을 사용하려면 Enter를 누르세요.\n")

    confirm = input("위 설정으로 실행할까요? (y/n): ").strip().lower()
    if confirm not in ("y", "yes", ""):
        print("실행을 취소합니다.")
        return

    # argparse Namespace 생성하여 cmd_run 호출
    run_args = argparse.Namespace(
        topic=topic,
        domain=domain,
        goal=goal or None,
        data_path=data_path or None,
        output=output_path,
        target_accuracy=target_accuracy,
        max_experiments=5,
        frameworks="PyTorch",
        config=args.config if hasattr(args, "config") else None,
    )

    cmd_run(run_args)


def cmd_dry_run(args):
    """LLM 호출 없이 그래프 구조만 검증합니다."""
    from graph.builder import build_graph_dry_run
    from graph.state import ResearchInput, create_initial_state
    from graph.research_graph import get_graph_visualization_mermaid

    print("=" * 60)
    print("  드라이런 모드 - 그래프 구조 검증")
    print("=" * 60)

    # 그래프 빌드
    graph = build_graph_dry_run()
    print("[OK] 그래프 컴파일 성공")

    # Mermaid 다이어그램 출력
    mermaid = get_graph_visualization_mermaid()
    print(f"\n[그래프 구조 (Mermaid)]\n{mermaid}")

    # 테스트 실행
    inp = ResearchInput(
        research_topic="드라이런 테스트",
        research_goal="그래프 구조 검증",
        research_domain="테스트",
        output_path="./outputs",
    )
    state = create_initial_state(inp, "dry_session", "dry_run")

    print("\n[드라이런 실행 중...]")
    final = graph.invoke(state)

    print(f"\n[결과]")
    print(f"  상태: {final.get('status')}")
    print(f"  단계 이력: {' → '.join(final.get('phase_history', []))}")
    print(f"  목표 달성: {final.get('meets_target')}")
    print("\n[OK] 드라이런 완료 - 그래프 구조가 정상입니다.")


def cmd_serve(args):
    """FastAPI 서버를 시작합니다."""
    import uvicorn
    from api.server import create_app

    app = create_app()

    print("=" * 60)
    print("  자율 연구 시스템 - API 서버 모드")
    print(f"  http://{args.host}:{args.port}")
    print(f"  API 문서: http://{args.host}:{args.port}/docs")
    print("=" * 60)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


# ──────────────────────────────────────────────
# CLI 파서
# ──────────────────────────────────────────────

def create_parser():
    """CLI 인자 파서를 생성합니다."""
    parser = argparse.ArgumentParser(
        description="자율 연구 시스템 (LangGraph Prototype)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 동기 실행
  python main.py run --topic "ResNet vs ViT 성능 비교" --domain "컴퓨터 비전"

  # 대화형 모드
  python main.py interactive

  # API 서버
  python main.py serve --port 8000

  # 드라이런
  python main.py dry-run
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="실행 모드")

    # run 서브커맨드
    run_parser = subparsers.add_parser("run", help="동기 모드로 연구 워크플로우 실행")
    run_parser.add_argument("--topic", "-t", required=True, help="연구 주제")
    run_parser.add_argument("--domain", "-d", default="일반", help="연구 분야")
    run_parser.add_argument("--goal", "-g", default=None, help="연구 목표")
    run_parser.add_argument("--data-path", default=None, help="데이터셋 경로")
    run_parser.add_argument("--output", "-o", default="./outputs", help="출력 디렉토리")
    run_parser.add_argument("--target-accuracy", type=float, default=0.85, help="목표 정확도")
    run_parser.add_argument("--max-experiments", type=int, default=5, help="최대 실험 횟수")
    run_parser.add_argument("--frameworks", default="PyTorch", help="선호 프레임워크 (쉼표 구분)")
    run_parser.add_argument("--config", "-c", default=None, help="설정 파일 경로")

    # interactive 서브커맨드
    interactive_parser = subparsers.add_parser("interactive", help="대화형 모드")
    interactive_parser.add_argument("--config", "-c", default=None, help="설정 파일 경로")

    # dry-run 서브커맨드
    dry_parser = subparsers.add_parser("dry-run", help="LLM 없이 그래프 구조 검증")

    # serve 서브커맨드
    serve_parser = subparsers.add_parser("serve", help="FastAPI 서버 시작")
    serve_parser.add_argument("--host", default="0.0.0.0", help="서버 호스트")
    serve_parser.add_argument("--port", "-p", type=int, default=8000, help="서버 포트")
    serve_parser.add_argument("--reload", action="store_true", help="자동 리로드")

    return parser


def main():
    """메인 진입점."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "run": cmd_run,
        "interactive": cmd_interactive,
        "dry-run": cmd_dry_run,
        "serve": cmd_serve,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
