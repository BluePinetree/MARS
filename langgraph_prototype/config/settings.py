"""
Settings loader for the LangGraph prototype.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# research_system 루트를 sys.path에 추가 (rsp/ 모듈 접근)
_RESEARCH_SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RESEARCH_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_SYSTEM_ROOT))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LLMModelConfig:
    provider: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 4096


@dataclass
class Settings:
    # Agent LLMs
    llm_config: Dict[str, LLMModelConfig] = field(default_factory=dict)

    # Defaults
    max_experiments: int = 3
    max_debug_loops: int = 3
    time_limit_minutes: int = 60
    target_accuracy: float = 0.90

    # Prompt/context controls
    context_char_budget: int = 24000
    context_token_budget: int = 6000
    compact_max_chars: int = 2000

    # Pinecone
    pinecone_index_name: str = "research-papers"
    pinecone_namespace: str = "default"
    pinecone_top_k: int = 5
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    pinecone_query_max_chars: int = 1500

    # Docker
    docker_base_image: str = "python:3.11-slim"
    docker_memory_limit: str = "4g"
    docker_cpu_limit: float = 2.0
    docker_timeout: int = 600
    docker_network_mode: str = "none"

    # W&B
    wandb_project: str = "autonomous-research"
    wandb_log_frequency: int = 10

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Logging
    log_level: str = "INFO"
    log_dir: str = "./logs"

    # API keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    pinecone_api_key: Optional[str] = None
    wandb_api_key: Optional[str] = None


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except ImportError:
        pass

    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not key.startswith("#"):
            os.environ.setdefault(key, value)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_path: Optional[str] = None) -> Settings:
    """Load settings from `.env` and `config.yaml`."""
    _load_env(PROJECT_ROOT / ".env")

    resolved = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"
    raw = _load_yaml(resolved)

    settings = Settings()

    llm_raw = raw.get("llm_config", {})
    for agent_name, model_cfg in llm_raw.items():
        settings.llm_config[agent_name] = LLMModelConfig(
            provider=str(model_cfg.get("provider", "openai")),
            model=str(model_cfg.get("model", "gpt-5-mini")),
            temperature=float(model_cfg.get("temperature", 0.3)),
            max_tokens=int(model_cfg.get("max_tokens", 4096)),
        )

    defaults = raw.get("defaults", {})
    settings.max_experiments = int(defaults.get("max_experiments", settings.max_experiments))
    settings.max_debug_loops = int(defaults.get("max_debug_loops", settings.max_debug_loops))
    settings.time_limit_minutes = int(defaults.get("time_limit_minutes", settings.time_limit_minutes))
    settings.target_accuracy = float(defaults.get("target_accuracy", settings.target_accuracy))

    context = raw.get("context", {})
    settings.context_char_budget = int(context.get("char_budget", settings.context_char_budget))
    settings.context_token_budget = int(context.get("token_budget", settings.context_token_budget))
    settings.compact_max_chars = int(context.get("compact_max_chars", settings.compact_max_chars))

    pinecone_cfg = raw.get("pinecone", {})
    settings.pinecone_index_name = str(pinecone_cfg.get("index_name", settings.pinecone_index_name))
    settings.pinecone_namespace = str(pinecone_cfg.get("namespace", settings.pinecone_namespace))
    settings.pinecone_top_k = int(pinecone_cfg.get("top_k", settings.pinecone_top_k))
    settings.embedding_model = str(pinecone_cfg.get("embedding_model", settings.embedding_model))
    settings.embedding_dimension = int(pinecone_cfg.get("embedding_dimension", settings.embedding_dimension))
    settings.pinecone_query_max_chars = int(
        pinecone_cfg.get("query_max_chars", settings.pinecone_query_max_chars)
    )

    docker_cfg = raw.get("docker", {})
    settings.docker_base_image = str(docker_cfg.get("base_image", settings.docker_base_image))
    settings.docker_memory_limit = str(docker_cfg.get("memory_limit", settings.docker_memory_limit))
    settings.docker_cpu_limit = float(docker_cfg.get("cpu_limit", settings.docker_cpu_limit))
    settings.docker_timeout = int(docker_cfg.get("timeout_seconds", settings.docker_timeout))
    settings.docker_network_mode = str(docker_cfg.get("network_mode", settings.docker_network_mode))

    wandb_cfg = raw.get("wandb", {})
    settings.wandb_project = str(wandb_cfg.get("project", settings.wandb_project))
    settings.wandb_log_frequency = int(wandb_cfg.get("log_frequency", settings.wandb_log_frequency))

    celery_cfg = raw.get("celery", {})
    settings.celery_broker_url = os.getenv(
        "CELERY_BROKER_URL", celery_cfg.get("broker_url", settings.celery_broker_url)
    )
    settings.celery_result_backend = os.getenv(
        "CELERY_RESULT_BACKEND", celery_cfg.get("result_backend", settings.celery_result_backend)
    )

    log_cfg = raw.get("logging", {})
    settings.log_level = os.getenv("LOG_LEVEL", str(log_cfg.get("level", settings.log_level)))
    settings.log_dir = str(log_cfg.get("log_dir", settings.log_dir))

    settings.openai_api_key = os.getenv("OPENAI_API_KEY")
    settings.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    settings.google_api_key = os.getenv("GOOGLE_API_KEY")
    settings.pinecone_api_key = os.getenv("PINECONE_API_KEY")
    settings.wandb_api_key = os.getenv("WANDB_API_KEY")

    return settings


def get_api_key_for_provider(settings: Settings, provider: str) -> Optional[str]:
    key_map = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
    }
    return key_map.get(provider.lower())
