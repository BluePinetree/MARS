"""
Model client factory for AutoGen.
"""

from __future__ import annotations

from autogen_core.models import ModelFamily, ModelInfo
from autogen_ext.models.openai import OpenAIChatCompletionClient

from core.config_loader import AgentLLMConfig, SystemConfig, get_llm_api_key


_MODEL_FAMILY_MAP: dict[str, str] = {
    # OpenAI
    "gpt-5.2": ModelFamily.GPT_4O,
    "gpt-5.2-pro": ModelFamily.GPT_4O,
    "gpt-5.2-codex": ModelFamily.GPT_4O,
    "gpt-5-mini": ModelFamily.GPT_4O,
    "gpt-5-nano": ModelFamily.GPT_4O,
    "gpt-4o": ModelFamily.GPT_4O,
    "gpt-4o-mini": ModelFamily.GPT_4O,
    "gpt-4.1-mini": ModelFamily.GPT_4O,
    "gpt-4.1-nano": ModelFamily.GPT_4O,
    "o3-mini": ModelFamily.O3,
    # Anthropic
    "claude-sonnet-4-5-20250929": ModelFamily.CLAUDE_3_5_SONNET,
    "claude-haiku-4-5-20251001": ModelFamily.CLAUDE_3_5_HAIKU,
    "claude-opus-4-1-20250805": ModelFamily.CLAUDE_3_5_SONNET,
    "claude-sonnet-4-20250514": ModelFamily.CLAUDE_3_5_SONNET,
    # Google
    "gemini-3-pro-preview": ModelFamily.GEMINI_2_0_FLASH,
    "gemini-3-flash-preview": ModelFamily.GEMINI_2_0_FLASH,
    "gemini-2.5-flash-lite-preview-09-2025": ModelFamily.GEMINI_2_0_FLASH,
    "gemini-2.5-flash": ModelFamily.GEMINI_2_0_FLASH,
    "gemini-2.0-flash": ModelFamily.GEMINI_2_0_FLASH,
    "gemini-2.5-pro": ModelFamily.GEMINI_1_5_PRO,
}

_MODEL_VISION_MAP: dict[str, bool] = {
    "gpt-5.2": True,
    "gpt-5.2-pro": True,
    "gpt-5.2-codex": False,
    "gpt-5-mini": True,
    "gpt-5-nano": False,
    "gpt-4o": True,
    "gpt-4o-mini": True,
    "gpt-4.1-mini": True,
    "gpt-4.1-nano": False,
    "o3-mini": False,
    "claude-sonnet-4-5-20250929": True,
    "claude-haiku-4-5-20251001": False,
    "claude-opus-4-1-20250805": True,
    "claude-sonnet-4-20250514": True,
    "gemini-3-pro-preview": True,
    "gemini-3-flash-preview": True,
    "gemini-2.5-flash-lite-preview-09-2025": True,
    "gemini-2.5-flash": True,
    "gemini-2.0-flash": True,
    "gemini-2.5-pro": True,
}


def _get_model_info(model_name: str) -> ModelInfo:
    return ModelInfo(
        vision=_MODEL_VISION_MAP.get(model_name, False),
        function_calling=True,
        json_output=True,
        family=_MODEL_FAMILY_MAP.get(model_name, ModelFamily.UNKNOWN),
    )


def _create_openai_client(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
) -> OpenAIChatCompletionClient:
    """
    OpenAI client.

    Important: do not pass `temperature` or `max_tokens` for OpenAI GPT-5 paths.
    """
    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        model_info=_get_model_info(model),
        max_retries=10,
    )


def _create_anthropic_client(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
) -> OpenAIChatCompletionClient:
    """Anthropic via OpenAI-compatible proxy."""
    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        model_info=_get_model_info(model),
    )


def _create_google_client(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
) -> OpenAIChatCompletionClient:
    """Google Gemini via OpenAI-compatible endpoint."""
    gemini_openai_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    resolved_base_url = gemini_openai_url if not base_url else base_url
    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=resolved_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        model_info=_get_model_info(model),
    )


_PROVIDER_FACTORIES = {
    "openai": _create_openai_client,
    "anthropic": _create_anthropic_client,
    "google": _create_google_client,
}


def create_model_client(
    config: SystemConfig,
    agent_name: str,
) -> OpenAIChatCompletionClient:
    """Create model client bound to an agent."""
    agent_llm = config.agent_llm_mapping.get(agent_name)
    if not agent_llm:
        agent_llm = AgentLLMConfig(
            provider="openai",
            model="gpt-5-mini",
            temperature=0.7,
            max_tokens=4096,
        )

    provider_name = agent_llm.provider
    api_key = get_llm_api_key(config, provider_name)
    provider_config = config.llm_providers.get(provider_name)
    if not provider_config:
        raise ValueError(f"Provider '{provider_name}' is missing in llm_providers config.")

    factory = _PROVIDER_FACTORIES.get(provider_name)
    if not factory:
        raise ValueError(
            f"Unsupported provider: {provider_name}. "
            f"Supported: {list(_PROVIDER_FACTORIES.keys())}"
        )

    return factory(
        model=agent_llm.model,
        api_key=api_key,
        base_url=provider_config.base_url,
        temperature=agent_llm.temperature,
        max_tokens=agent_llm.max_tokens,
    )


def create_selector_client(config: SystemConfig) -> OpenAIChatCompletionClient:
    """Create model client for selector agent."""
    selector_models = {
        "openai": "gpt-5-mini",
        "anthropic": "claude-haiku-4-5-20251001",
        "google": "gemini-2.5-flash",
    }

    for provider_name in ["openai", "anthropic", "google"]:
        provider = config.llm_providers.get(provider_name)
        if not provider:
            continue

        try:
            api_key = get_llm_api_key(config, provider_name)
        except ValueError:
            continue

        factory = _PROVIDER_FACTORIES.get(provider_name)
        if not factory:
            continue

        model = selector_models.get(provider_name, provider.available_models[0])
        return factory(
            model=model,
            api_key=api_key,
            base_url=provider.base_url,
            temperature=0.0,
            max_tokens=256,
        )

    raise ValueError(
        "Failed to create selector model client. Configure at least one provider API key."
    )
