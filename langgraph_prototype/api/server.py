"""
FastAPI 서버.

자율 연구 시스템의 REST API를 제공합니다.
동기 실행과 Celery 비동기 실행을 모두 지원합니다.

엔드포인트:
    POST /api/v1/research/run        - 동기 연구 실행
    POST /api/v1/research/run/async  - 비동기 연구 실행 (Celery)
    GET  /api/v1/research/status/{task_id} - 태스크 상태 조회
    POST /api/v1/research/cancel/{task_id} - 태스크 취소
    GET  /api/v1/health              - 헬스체크
    GET  /api/v1/config              - 현재 설정 조회
    PUT  /api/v1/config/agents       - 에이전트별 LLM 설정 변경
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 요청/응답 스키마
# ──────────────────────────────────────────────

class ResearchRequest(BaseModel):
    """연구 실행 요청."""
    research_topic: str = Field(..., description="연구 주제", examples=["ResNet vs ViT 성능 비교"])
    research_goal: Optional[str] = Field(None, description="연구 목표")
    research_domain: str = Field("일반", description="연구 분야", examples=["컴퓨터 비전", "NLP"])
    data_path: Optional[str] = Field(None, description="데이터셋 경로")
    output_path: str = Field("./outputs", description="출력 디렉토리")
    target_accuracy: float = Field(0.85, description="목표 정확도", ge=0.0, le=1.0)
    max_experiments: int = Field(5, description="최대 실험 횟수", ge=1, le=20)
    preferred_frameworks: List[str] = Field(["PyTorch"], description="선호 프레임워크")


class AgentLLMConfig(BaseModel):
    """에이전트별 LLM 설정."""
    agent_name: str = Field(..., description="에이전트 이름", examples=["planner", "coder"])
    provider: str = Field(..., description="LLM 제공자", examples=["openai", "anthropic", "google"])
    model: str = Field(..., description="모델명", examples=["gpt-5.2", "claude-sonnet-4-5-20250929"])
    temperature: float = Field(0.7, description="생성 온도", ge=0.0, le=2.0)


class AgentConfigUpdate(BaseModel):
    """에이전트 LLM 설정 업데이트 요청."""
    agents: List[AgentLLMConfig] = Field(..., description="에이전트별 LLM 설정 리스트")


class ResearchResponse(BaseModel):
    """연구 실행 응답."""
    success: bool
    session_id: str
    run_id: str
    status: str
    report_path: Optional[str] = None
    best_metrics: Dict[str, Any] = {}
    meets_target: bool = False
    total_experiments: int = 0
    phase_history: List[str] = []
    log_path: Optional[str] = None


class AsyncResearchResponse(BaseModel):
    """비동기 연구 실행 응답."""
    task_id: str
    session_id: str
    message: str
    status_url: str


class TaskStatusResponse(BaseModel):
    """태스크 상태 응답."""
    task_id: str
    state: str
    info: Dict[str, Any] = {}


class HealthResponse(BaseModel):
    """헬스체크 응답."""
    status: str
    version: str
    timestamp: str
    tools: Dict[str, bool]


class ConfigResponse(BaseModel):
    """설정 조회 응답."""
    agents: Dict[str, Dict[str, Any]]
    tools: Dict[str, bool]
    system: Dict[str, Any]


# ──────────────────────────────────────────────
# FastAPI 앱 생성
# ──────────────────────────────────────────────

def create_app() -> FastAPI:
    """FastAPI 앱을 생성합니다."""

    app = FastAPI(
        title="자율 연구 시스템 API",
        description=(
            "LangGraph 기반 자율 연구 시스템의 REST API입니다. "
            "연구 주제를 입력하면 에이전트들이 자율적으로 실험을 설계, 실행, 분석합니다."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS 설정
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ──────────────────────────────────────────
    # 헬스체크
    # ──────────────────────────────────────────

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["System"])
    async def health_check():
        """시스템 상태를 확인합니다."""
        from tools import create_tools

        tools = create_tools()
        return HealthResponse(
            status="healthy",
            version="0.1.0",
            timestamp=datetime.now().isoformat(),
            tools={
                "pinecone": tools["pinecone"].is_available,
                "docker": tools["docker"].is_available,
                "wandb": tools["wandb"].is_available,
            },
        )

    # ──────────────────────────────────────────
    # 설정 조회 / 변경
    # ──────────────────────────────────────────

    @app.get("/api/v1/config", response_model=ConfigResponse, tags=["Config"])
    async def get_config():
        """현재 시스템 설정을 조회합니다."""
        from config.settings import load_settings
        from tools import create_tools

        settings = load_settings()
        tools = create_tools(settings)

        agents_config = {}
        for agent_name, agent_cfg in settings.agents.items():
            agents_config[agent_name] = {
                "provider": agent_cfg.get("provider", "openai"),
                "model": agent_cfg.get("model", "gpt-5-mini"),
                "temperature": agent_cfg.get("temperature", 0.7),
            }

        return ConfigResponse(
            agents=agents_config,
            tools={
                "pinecone": tools["pinecone"].is_available,
                "docker": tools["docker"].is_available,
                "wandb": tools["wandb"].is_available,
            },
            system={
                "target_accuracy": settings.target_accuracy,
                "max_debug_loops": settings.max_debug_loops,
            },
        )

    @app.put("/api/v1/config/agents", tags=["Config"])
    async def update_agent_config(request: AgentConfigUpdate):
        """
        에이전트별 LLM 설정을 동적으로 변경합니다.
        변경 사항은 다음 연구 실행부터 적용됩니다.
        """
        from config.settings import load_settings
        import yaml

        settings = load_settings()

        for agent_cfg in request.agents:
            if agent_cfg.agent_name in settings.agents:
                settings.agents[agent_cfg.agent_name] = {
                    "provider": agent_cfg.provider,
                    "model": agent_cfg.model,
                    "temperature": agent_cfg.temperature,
                }
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"알 수 없는 에이전트: {agent_cfg.agent_name}. "
                           f"사용 가능: {list(settings.agents.keys())}",
                )

        # config.yaml 업데이트
        try:
            config_path = settings.config_path or "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            for agent_cfg in request.agents:
                config["agents"][agent_cfg.agent_name] = {
                    "provider": agent_cfg.provider,
                    "model": agent_cfg.model,
                    "temperature": agent_cfg.temperature,
                }

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        except Exception as e:
            logger.warning(f"config.yaml 업데이트 실패: {e}")

        return {
            "message": "에이전트 LLM 설정이 업데이트되었습니다.",
            "updated_agents": [a.agent_name for a in request.agents],
        }

    # ──────────────────────────────────────────
    # 동기 연구 실행
    # ──────────────────────────────────────────

    @app.post("/api/v1/research/run", response_model=ResearchResponse, tags=["Research"])
    async def run_research(request: ResearchRequest):
        """
        연구 워크플로우를 동기적으로 실행합니다.
        전체 워크플로우가 완료될 때까지 응답을 대기합니다.
        """
        from config.settings import load_settings
        from graph.state import ResearchInput, create_initial_state
        from graph.builder import build_graph
        from tools import create_tools
        from utils.logger import ResearchLogger

        settings = load_settings()
        settings.target_accuracy = request.target_accuracy

        session_id = f"session_{uuid.uuid4().hex[:8]}"
        run_id = f"run_{uuid.uuid4().hex[:8]}"

        # 로거
        from pathlib import Path
        log_dir = Path(request.output_path) / "logs" / session_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = str(log_dir / f"{run_id}.jsonl")

        research_logger = ResearchLogger(
            session_id=session_id,
            run_id=run_id,
            log_path=log_path,
        )

        # 도구 및 그래프
        tools = create_tools(settings)
        graph = build_graph(
            settings=settings,
            logger=research_logger,
            pinecone_tool=tools["pinecone"],
            docker_tool=tools["docker"],
            wandb_tool=tools["wandb"],
        )

        # 입력 생성
        ri = ResearchInput(
            research_topic=request.research_topic,
            research_goal=request.research_goal or f"{request.research_topic}에 대한 체계적 실험",
            research_domain=request.research_domain,
            data_path=request.data_path or "",
            output_path=request.output_path,
            constraints={
                "max_experiments": request.max_experiments,
                "preferred_frameworks": request.preferred_frameworks,
            },
        )
        initial_state = create_initial_state(
            ri,
            session_id,
            run_id,
            max_loops=settings.max_debug_loops,
            context_char_budget=settings.context_char_budget,
            context_token_budget=settings.context_token_budget,
            compact_max_chars=settings.compact_max_chars,
        )

        try:
            final_state = graph.invoke(initial_state)

            return ResearchResponse(
                success=True,
                session_id=session_id,
                run_id=run_id,
                status=final_state.get("status", "unknown"),
                report_path=final_state.get("report_path"),
                best_metrics=final_state.get("best_metrics", {}),
                meets_target=final_state.get("meets_target", False),
                total_experiments=len(final_state.get("experiment_results", [])),
                phase_history=final_state.get("phase_history", []),
                log_path=log_path,
            )

        except Exception as e:
            logger.error(f"연구 실행 실패: {e}")
            raise HTTPException(status_code=500, detail=f"연구 실행 실패: {str(e)}")

    # ──────────────────────────────────────────
    # 비동기 연구 실행 (Celery)
    # ──────────────────────────────────────────

    @app.post("/api/v1/research/run/async", response_model=AsyncResearchResponse, tags=["Research"])
    async def run_research_async(request: ResearchRequest):
        """
        연구 워크플로우를 Celery를 통해 비동기로 실행합니다.
        즉시 task_id를 반환하며, 상태 조회 API로 진행 상황을 확인합니다.
        """
        try:
            from tasks.research_tasks import run_research_workflow

            session_id = f"session_{uuid.uuid4().hex[:8]}"

            research_input_dict = {
                "research_topic": request.research_topic,
                "research_goal": request.research_goal or f"{request.research_topic}에 대한 체계적 실험",
                "research_domain": request.research_domain,
                "data_path": request.data_path or "",
                "output_path": request.output_path,
                "constraints": {
                    "max_experiments": request.max_experiments,
                    "preferred_frameworks": request.preferred_frameworks,
                },
            }

            task = run_research_workflow.delay(
                research_input=research_input_dict,
                session_id=session_id,
                config_overrides={"target_accuracy": request.target_accuracy},
            )

            return AsyncResearchResponse(
                task_id=task.id,
                session_id=session_id,
                message="연구 워크플로우가 비동기로 시작되었습니다.",
                status_url=f"/api/v1/research/status/{task.id}",
            )

        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"비동기 실행 실패 (Celery/Redis 연결 확인 필요): {str(e)}",
            )

    # ──────────────────────────────────────────
    # 태스크 상태 조회 / 취소
    # ──────────────────────────────────────────

    @app.get("/api/v1/research/status/{task_id}", response_model=TaskStatusResponse, tags=["Research"])
    async def get_research_status(task_id: str):
        """Celery 태스크의 현재 상태를 조회합니다."""
        try:
            from tasks.research_tasks import get_task_status

            status = get_task_status(task_id)
            return TaskStatusResponse(**status)

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"상태 조회 실패: {str(e)}")

    @app.post("/api/v1/research/cancel/{task_id}", tags=["Research"])
    async def cancel_research(task_id: str):
        """실행 중인 연구 태스크를 취소합니다."""
        try:
            from tasks.research_tasks import cancel_task

            result = cancel_task(task_id)
            return result

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"태스크 취소 실패: {str(e)}")

    return app
