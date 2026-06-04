"""
비동기 연구 태스크.

LangGraph 연구 워크플로우와 개별 실험 실행을 Celery 태스크로 래핑합니다.
FastAPI에서 이 태스크를 호출하여 비동기 실행을 트리거하고,
태스크 ID로 진행 상황을 조회합니다.

주요 태스크:
- run_research_workflow: 전체 연구 워크플로우 실행
- run_single_experiment: 개별 실험 코드 실행
- check_task_status: 태스크 상태 조회 유틸리티
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.run_research_workflow",
    queue="research",
    max_retries=1,
    soft_time_limit=6600,
    time_limit=7200,
)
def run_research_workflow(
    self,
    research_input: Dict[str, Any],
    session_id: Optional[str] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    전체 연구 워크플로우를 비동기로 실행합니다.

    Args:
        research_input: 연구 입력 딕셔너리 (ResearchInput 형식).
        session_id: 세션 ID (미제공 시 자동 생성).
        config_overrides: 설정 오버라이드 딕셔너리.

    Returns:
        dict: 최종 연구 결과 (상태, 보고서 경로, 메트릭 등).
    """
    task_id = self.request.id
    session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
    run_id = f"run_{uuid.uuid4().hex[:8]}"

    logger.info(f"[Celery] 연구 워크플로우 시작: task_id={task_id}, session={session_id}")

    # 진행 상태 업데이트
    self.update_state(
        state="PROGRESS",
        meta={
            "phase": "initializing",
            "session_id": session_id,
            "run_id": run_id,
            "started_at": datetime.now().isoformat(),
        },
    )

    try:
        # 설정 로드
        from config.settings import load_settings

        settings = load_settings()

        # 설정 오버라이드 적용
        if config_overrides:
            for key, value in config_overrides.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)

        # 로거 생성
        from utils.logger import ResearchLogger

        log_path = f"./logs/{session_id}/{run_id}.jsonl"
        research_logger = ResearchLogger(
            session_id=session_id,
            run_id=run_id,
            log_path=log_path,
        )

        # 도구 생성
        from tools import create_tools

        tools = create_tools(settings)

        # workspace_root 설정
        import os
        workspace_root = os.path.join("./outputs", run_id, "workspace")
        os.makedirs(workspace_root, exist_ok=True)

        # 그래프 빌드
        from graph.builder import build_graph

        graph = build_graph(
            settings=settings,
            workspace_root=workspace_root,
            logger=research_logger,
            pinecone_tool=tools["pinecone"],
            docker_tool=tools["docker"],
            wandb_tool=tools["wandb"],
        )

        # 초기 상태 생성
        from graph.state import ResearchInput as RI, create_initial_state

        ri = RI(**research_input)
        initial_state = create_initial_state(
            ri,
            session_id,
            run_id,
            max_loops=settings.max_debug_loops,
            context_char_budget=settings.context_char_budget,
            context_token_budget=settings.context_token_budget,
            compact_max_chars=settings.compact_max_chars,
            workspace_root=workspace_root,
        )

        # 진행 상태 업데이트: 실행 시작
        self.update_state(
            state="PROGRESS",
            meta={
                "phase": "running",
                "session_id": session_id,
                "run_id": run_id,
                "started_at": datetime.now().isoformat(),
            },
        )

        # 그래프 실행
        final_state = graph.invoke(initial_state)

        # Telemetry 요약 저장
        _save_telemetry_summary(workspace_root, run_id)

        # 결과 정리
        result = {
            "success": True,
            "task_id": task_id,
            "session_id": session_id,
            "run_id": run_id,
            "status": final_state.get("status", "unknown"),
            "report_path": final_state.get("report_path", ""),
            "best_metrics": final_state.get("best_metrics", {}),
            "meets_target": final_state.get("meets_target", False),
            "total_experiments": len(final_state.get("experiment_results", [])),
            "phase_history": final_state.get("phase_history", []),
            "log_path": log_path,
            "completed_at": datetime.now().isoformat(),
        }

        logger.info(f"[Celery] 연구 워크플로우 완료: {result['status']}")
        return result

    except Exception as e:
        logger.error(f"[Celery] 연구 워크플로우 실패: {str(e)}")

        # 재시도 가능한 에러인지 판단
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)

        return {
            "success": False,
            "task_id": task_id,
            "session_id": session_id,
            "run_id": run_id,
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat(),
        }


@celery_app.task(
    bind=True,
    name="tasks.run_single_experiment",
    queue="experiment",
    max_retries=2,
    soft_time_limit=1800,
    time_limit=2400,
)
def run_single_experiment(
    self,
    code: str,
    requirements: str = "",
    experiment_id: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    개별 실험 코드를 비동기로 실행합니다.

    Docker 도구를 사용하여 격리된 환경에서 코드를 실행합니다.
    주로 Executor 노드의 장시간 실험을 비동기로 처리할 때 사용됩니다.

    Args:
        code: 실행할 Python 코드.
        requirements: pip 패키지 목록.
        experiment_id: 실험 ID.
        env_vars: 환경변수 딕셔너리.

    Returns:
        dict: 실행 결과 (성공 여부, 로그, 메트릭).
    """
    experiment_id = experiment_id or f"exp_{uuid.uuid4().hex[:8]}"
    task_id = self.request.id

    logger.info(f"[Celery] 실험 실행 시작: task_id={task_id}, exp={experiment_id}")

    self.update_state(
        state="PROGRESS",
        meta={
            "experiment_id": experiment_id,
            "phase": "executing",
            "started_at": datetime.now().isoformat(),
        },
    )

    try:
        from tools.docker_tool import DockerTool

        docker_tool = DockerTool()
        result = docker_tool.execute(
            code=code,
            requirements=requirements,
            experiment_id=experiment_id,
            env_vars=env_vars,
        )

        result["task_id"] = task_id
        result["experiment_id"] = experiment_id
        result["completed_at"] = datetime.now().isoformat()

        logger.info(
            f"[Celery] 실험 완료: exp={experiment_id}, "
            f"success={result['success']}"
        )
        return result

    except Exception as e:
        logger.error(f"[Celery] 실험 실행 실패: {str(e)}")

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=30)

        return {
            "success": False,
            "task_id": task_id,
            "experiment_id": experiment_id,
            "logs": f"Celery 태스크 실패: {str(e)}",
            "metrics": {},
            "exit_code": -1,
            "completed_at": datetime.now().isoformat(),
        }


def _save_telemetry_summary(workspace_root: str, run_id: str) -> None:
    try:
        import sys
        from pathlib import Path
        _rsp_root = str(Path(workspace_root).parent.parent.parent.parent)
        if _rsp_root not in sys.path:
            sys.path.insert(0, _rsp_root)
        from rsp.telemetry import TelemetryStore
        summary = TelemetryStore.summary()
        summary["framework"] = "langgraph"
        summary["run_id"] = run_id
        out_path = Path(workspace_root) / "logs" / "telemetry_summary.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    Celery 태스크의 현재 상태를 조회합니다.

    Args:
        task_id: Celery 태스크 ID.

    Returns:
        dict: {
            "task_id": str,
            "state": str,  # PENDING, STARTED, PROGRESS, SUCCESS, FAILURE, REVOKED
            "info": dict,  # 상태별 추가 정보
        }
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "state": result.state,
    }

    if result.state == "PENDING":
        response["info"] = {"message": "태스크가 대기 중입니다."}
    elif result.state == "STARTED":
        response["info"] = {"message": "태스크가 시작되었습니다."}
    elif result.state == "PROGRESS":
        response["info"] = result.info if result.info else {}
    elif result.state == "SUCCESS":
        response["info"] = result.result if result.result else {}
    elif result.state == "FAILURE":
        response["info"] = {
            "error": str(result.result) if result.result else "알 수 없는 에러",
            "traceback": result.traceback,
        }
    elif result.state == "REVOKED":
        response["info"] = {"message": "태스크가 취소되었습니다."}
    else:
        response["info"] = result.info if result.info else {}

    return response


def cancel_task(task_id: str) -> Dict[str, Any]:
    """
    실행 중인 Celery 태스크를 취소합니다.

    Args:
        task_id: 취소할 태스크 ID.

    Returns:
        dict: 취소 결과.
    """
    celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
    return {
        "task_id": task_id,
        "action": "revoked",
        "message": f"태스크 {task_id}에 취소 신호를 보냈습니다.",
    }
