"""
Configuration loader for the AutoGen prototype.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# rsp/ (Research System Platform) 공유 레이어 등록
_RESEARCH_SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RESEARCH_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_SYSTEM_ROOT))

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class LLMProviderConfig(BaseModel):
    api_key_env: str
    base_url: str
    available_models: list[str] = Field(default_factory=list)


class AgentLLMConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096


class GroupChatConfig(BaseModel):
    max_rounds: int = 30
    speaker_selection: str = "auto"
    allow_repeat_speaker: bool = True
    termination_keyword: str = "RESEARCH_COMPLETE"
    context_char_budget: int = 24000
    context_token_budget: int = 6000
    compact_max_chars: int = 2000


class RabbitMQConfig(BaseModel):
    host: str = "localhost"
    port: int = 5672
    username: str = "guest"
    password: str = "guest"
    exchange_name: str = "research_exchange"
    queue_prefix: str = "agent_"
    enabled: bool = False


class LanceDBConfig(BaseModel):
    db_path: str = "./data/lance_db"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    table_name: str = "research_knowledge"
    top_k: int = 5
    query_max_chars: int = 1500


class OpenHandsConfig(BaseModel):
    enabled: bool = False
    api_url: str = "http://localhost:3000"
    workspace_dir: str = "./workspace"
    timeout_seconds: int = 300
    fallback_to_local: bool = True


class LoggingConfig(BaseModel):
    log_dir: str = "./logs"
    log_format: str = "jsonl"
    console_output: bool = True
    log_level: str = "INFO"


class ResearchDefaults(BaseModel):
    max_experiments: int = 3
    time_limit_minutes: int = 60
    output_base_path: str = "./outputs"


class SystemConfig(BaseModel):
    llm_providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    agent_llm_mapping: dict[str, AgentLLMConfig] = Field(default_factory=dict)
    group_chat: GroupChatConfig = Field(default_factory=GroupChatConfig)
    rabbitmq: RabbitMQConfig = Field(default_factory=RabbitMQConfig)
    lancedb: LanceDBConfig = Field(default_factory=LanceDBConfig)
    openhands: OpenHandsConfig = Field(default_factory=OpenHandsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    research_defaults: ResearchDefaults = Field(default_factory=ResearchDefaults)


def load_config(
    config_path: Optional[str] = None,
    env_path: Optional[str] = None,
) -> SystemConfig:
    """Load `.env` and YAML config into `SystemConfig`."""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")

    resolved = Path(config_path).resolve()
    if not resolved.exists():
        print(f"[warning] config file not found: {resolved}. Using defaults.")
        return SystemConfig()

    with resolved.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return SystemConfig(**raw)


def _default_agent_llm() -> AgentLLMConfig:
    return AgentLLMConfig(
        provider="openai",
        model="gpt-5-mini",
        temperature=0.7,
        max_tokens=4096,
    )


def get_llm_api_key(config: SystemConfig, provider_name: str) -> str:
    """Resolve provider API key from environment variable."""
    provider = config.llm_providers.get(provider_name)
    if not provider:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    api_key = os.environ.get(provider.api_key_env, "")
    if not api_key:
        raise ValueError(
            f"Missing API key. Set env var '{provider.api_key_env}' with your key."
        )
    return api_key


def build_autogen_llm_config(config: SystemConfig, agent_name: str) -> dict[str, Any]:
    """Build AutoGen-style config dict for a specific agent."""
    agent_llm = config.agent_llm_mapping.get(agent_name, _default_agent_llm())

    provider_name = agent_llm.provider
    provider_config = config.llm_providers.get(provider_name)
    if not provider_config:
        raise ValueError(f"Provider '{provider_name}' is missing in config.")

    llm_entry: dict[str, Any] = {
        "model": agent_llm.model,
        "api_key": get_llm_api_key(config, provider_name),
        "base_url": provider_config.base_url,
    }

    # Keep OpenAI requests minimal (GPT-5 rejects several legacy params).
    if provider_name != "openai":
        llm_entry["temperature"] = agent_llm.temperature
        llm_entry["max_tokens"] = agent_llm.max_tokens

    result: dict[str, Any] = {
        "config_list": [llm_entry],
        "cache_seed": None,
    }
    if provider_name != "openai":
        result["temperature"] = agent_llm.temperature

    return result


def get_model_client_kwargs(config: SystemConfig, agent_name: str) -> dict[str, Any]:
    """Build kwargs for model client factory."""
    agent_llm = config.agent_llm_mapping.get(agent_name, _default_agent_llm())

    provider_name = agent_llm.provider
    provider_config = config.llm_providers.get(provider_name)
    if not provider_config:
        raise ValueError(f"Provider '{provider_name}' is missing in config.")

    kwargs: dict[str, Any] = {
        "provider": provider_name,
        "model": agent_llm.model,
        "api_key": get_llm_api_key(config, provider_name),
        "base_url": provider_config.base_url,
    }

    if provider_name != "openai":
        kwargs["temperature"] = agent_llm.temperature
        kwargs["max_tokens"] = agent_llm.max_tokens

    return kwargs
