"""
LLM 클라이언트 팩토리 모듈.
에이전트별로 서로 다른 LLM 프로바이더/모델을 동적으로 생성합니다.
한 세션에서 GPT-5 계열 + Claude 4.5 계열 등 자유로운 조합이 가능합니다.
"""

import os
from typing import Optional

from config.settings import Settings, LLMModelConfig, get_api_key_for_provider


# ── Anthropic SDK 직접 팩토리 ─────────────────────────────────────────────────

def create_anthropic_client():
    """Anthropic SDK 클라이언트 반환 (run_tool_loop 전용)."""
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def get_agent_model(settings: Optional[Settings], agent_name: str) -> str:
    """settings.llm_config에서 에이전트 모델명 반환. 없으면 claude-sonnet-4-6."""
    if settings is None:
        return "claude-sonnet-4-6"
    cfg = settings.llm_config.get(agent_name)
    if cfg and cfg.model:
        return cfg.model
    return "claude-sonnet-4-6"


def create_llm(
    settings: Settings,
    agent_name: str,
    override_config: Optional[LLMModelConfig] = None,
):
    """
    에이전트 이름에 해당하는 LLM 클라이언트를 생성합니다.

    config.yaml에서 에이전트별로 지정된 provider/model을 사용하며,
    override_config가 제공되면 해당 설정을 우선 적용합니다.

    Args:
        settings: 시스템 설정 객체.
        agent_name: 에이전트 이름 (planner, designer, coder, executor, analyzer, writer).
        override_config: 설정을 덮어쓸 LLMModelConfig (선택).

    Returns:
        BaseChatModel: LangChain 호환 LLM 클라이언트.

    Raises:
        ValueError: 지원하지 않는 프로바이더이거나 API 키가 없는 경우.
    """
    # 설정 결정: override > config.yaml > 기본값
    if override_config:
        model_config = override_config
    elif agent_name in settings.llm_config:
        model_config = settings.llm_config[agent_name]
    else:
        model_config = LLMModelConfig(
            provider="openai",
            model="gpt-5-mini",
            temperature=0.3,
            max_tokens=4096,
        )

    api_key = get_api_key_for_provider(settings, model_config.provider)

    if model_config.provider == "openai":
        return _create_openai_llm(model_config, api_key)
    elif model_config.provider == "anthropic":
        return _create_anthropic_llm(model_config, api_key)
    elif model_config.provider == "google":
        return _create_google_llm(model_config, api_key)
    else:
        raise ValueError(
            f"지원하지 않는 LLM 프로바이더: {model_config.provider}. "
            f"지원 목록: openai, anthropic, google"
        )


def _create_openai_llm(config: LLMModelConfig, api_key: Optional[str]):
    """OpenAI LLM 클라이언트를 생성합니다."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain-openai 패키지가 필요합니다. "
            "pip install langchain-openai 로 설치하세요."
        )

    if not api_key:
        raise ValueError(
            "OpenAI API 키가 설정되지 않았습니다. "
            ".env 파일에 OPENAI_API_KEY를 설정하세요."
        )

    return ChatOpenAI(
        model=config.model,
        api_key=api_key,
    )


def _create_anthropic_llm(config: LLMModelConfig, api_key: Optional[str]):
    """Anthropic LLM 클라이언트를 생성합니다."""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError(
            "langchain-anthropic 패키지가 필요합니다. "
            "pip install langchain-anthropic 로 설치하세요."
        )

    if not api_key:
        raise ValueError(
            "Anthropic API 키가 설정되지 않았습니다. "
            ".env 파일에 ANTHROPIC_API_KEY를 설정하세요."
        )

    return ChatAnthropic(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        api_key=api_key,
    )


def _create_google_llm(config: LLMModelConfig, api_key: Optional[str]):
    """Google Gemini LLM 클라이언트를 생성합니다."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError(
            "langchain-google-genai 패키지가 필요합니다. "
            "pip install langchain-google-genai 로 설치하세요."
        )

    if not api_key:
        raise ValueError(
            "Google API 키가 설정되지 않았습니다. "
            ".env 파일에 GOOGLE_API_KEY를 설정하세요."
        )

    return ChatGoogleGenerativeAI(
        model=config.model,
        temperature=config.temperature,
        max_output_tokens=config.max_tokens,
        google_api_key=api_key,
    )


def validate_llm_config(settings: Settings) -> dict:
    """
    설정된 LLM 구성의 유효성을 검사합니다.

    Returns:
        dict: 각 에이전트별 검증 결과.
              {"planner": {"valid": True, "provider": "openai", "model": "gpt-5.2"}, ...}
    """
    results = {}
    for agent_name, model_config in settings.llm_config.items():
        api_key = get_api_key_for_provider(settings, model_config.provider)
        has_key = api_key is not None and len(api_key) > 0
        results[agent_name] = {
            "valid": has_key,
            "provider": model_config.provider,
            "model": model_config.model,
            "temperature": model_config.temperature,
            "api_key_set": has_key,
        }
    return results
