"""
core/config.py
==============
시스템 설정 로더 모듈.
config.yaml과 .env 파일을 로드하여 전역 설정 객체를 제공합니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# ── 프로젝트 루트 경로 ──────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Pydantic 설정 모델 ──────────────────────────────────
class LLMProviderConfig(BaseModel):
    api_key_env: str
    base_url: str
    available_models: List[str] = []


class AgentLLMConfig(BaseModel):
    provider: str
    model: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class CrewConfig(BaseModel):
    process: str = "sequential"
    verbose: bool = True
    memory: bool = False
    max_rpm: int = 30
    context_char_budget: int = 24000
    context_token_budget: int = 6000
    compact_max_chars: int = 2000
    chromadb_query_max_chars: int = 1500


class ChromaDBConfig(BaseModel):
    persist_directory: str = "./data/chromadb"
    collection_name: str = "research_memory"
    embedding_model: str = "all-MiniLM-L6-v2"


class E2BConfig(BaseModel):
    api_key_env: str = "E2B_API_KEY"
    timeout_seconds: int = 300
    template: str = "Python3"
    execution_backend: str = "workspace"
    workspace_dir: str = "."


class MLflowConfig(BaseModel):
    tracking_uri: str = "http://localhost:5000"
    experiment_name: str = "autonomous_research"


class RayConfig(BaseModel):
    enabled: bool = False
    num_cpus: int = 4
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8265


class ResearchDefaultsConfig(BaseModel):
    max_experiments: int = 3
    time_limit_minutes: int = 60
    preferred_frameworks: List[str] = ["PyTorch", "scikit-learn"]


class LoggingConfig(BaseModel):
    log_dir: str = "./logs"
    log_format: str = "jsonl"
    console_output: bool = True
    log_level: str = "INFO"


class SystemConfig(BaseModel):
    """전체 시스템 설정을 담는 최상위 모델"""
    llm_providers: Dict[str, LLMProviderConfig] = {}
    agent_llm_mapping: Dict[str, AgentLLMConfig] = {}
    crew: CrewConfig = CrewConfig()
    chromadb: ChromaDBConfig = ChromaDBConfig()
    e2b: E2BConfig = E2BConfig()
    mlflow: MLflowConfig = MLflowConfig()
    ray: RayConfig = RayConfig()
    research_defaults: ResearchDefaultsConfig = ResearchDefaultsConfig()
    logging: LoggingConfig = LoggingConfig()


# ── 설정 로드 함수 ──────────────────────────────────────
def load_config(
    config_path: Optional[str] = None,
    env_path: Optional[str] = None,
) -> SystemConfig:
    """
    config.yaml과 .env 파일을 로드하여 SystemConfig 객체를 반환합니다.

    Args:
        config_path: config.yaml 파일 경로 (None이면 프로젝트 루트의 config.yaml)
        env_path: .env 파일 경로 (None이면 프로젝트 루트의 .env)

    Returns:
        SystemConfig: 파싱된 시스템 설정 객체
    """
    # .env 로드
    if env_path is None:
        env_path = str(PROJECT_ROOT / ".env")
    load_dotenv(env_path, override=True)

    # config.yaml 로드
    if config_path is None:
        config_path = str(PROJECT_ROOT / "config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    return SystemConfig(**raw)


def get_api_key(provider_config: LLMProviderConfig) -> str:
    """프로바이더 설정에서 환경변수 이름을 읽어 실제 API 키를 반환합니다."""
    key = os.getenv(provider_config.api_key_env, "")
    if not key:
        raise ValueError(
            f"환경변수 '{provider_config.api_key_env}'가 설정되지 않았습니다. "
            f".env 파일을 확인하세요."
        )
    return key


# ── 싱글턴 캐시 ─────────────────────────────────────────
_cached_config: Optional[SystemConfig] = None


def get_config() -> SystemConfig:
    """캐시된 설정 객체를 반환합니다. 최초 호출 시 로드합니다."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def reload_config() -> SystemConfig:
    """설정을 강제로 다시 로드합니다."""
    global _cached_config
    _cached_config = load_config()
    return _cached_config
