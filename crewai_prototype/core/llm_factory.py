"""
core/llm_factory.py
===================
멀티 프로바이더 LLM 팩토리 모듈.
에이전트별로 서로 다른 LLM 프로바이더/모델을 할당할 수 있도록
CrewAI 호환 LLM 인스턴스를 생성합니다.

지원 프로바이더:
  - OpenAI  (gpt-5.2, gpt-5-mini 등)
  - Anthropic (claude-sonnet-4-5, claude-opus-4-1 등)
  - Google  (gemini-3-pro-preview, gemini-2.5-flash 등)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from crewai import LLM

from core.config import (
    AgentLLMConfig,
    SystemConfig,
    get_api_key,
    get_config,
)


def _build_model_string(provider: str, model: str) -> str:
    """
    CrewAI LLM이 인식하는 모델 문자열을 생성합니다.
    CrewAI는 내부적으로 litellm을 사용하므로 litellm 형식을 따릅니다.
      - openai  → "openai/<model>"  또는 그냥 "<model>"
      - anthropic → "anthropic/<model>"
      - google  → "gemini/<model>"
    """
    prefix_map = {
        "openai": "openai/",        # provider를 명시해 litellm 라우팅을 고정
        "anthropic": "anthropic/",
        "google": "gemini/",
    }
    prefix = prefix_map.get(provider, f"{provider}/")
    return f"{prefix}{model}"


def create_llm_for_agent(
    agent_name: str,
    config: Optional[SystemConfig] = None,
) -> LLM:
    """
    에이전트 이름에 매핑된 LLM 인스턴스를 생성합니다.

    Args:
        agent_name: config.yaml의 agent_llm_mapping 키
                    (예: "research_planner", "code_generator")
        config: SystemConfig 객체 (None이면 전역 설정 사용)

    Returns:
        crewai.LLM 인스턴스
    """
    if config is None:
        config = get_config()

    # 에이전트 LLM 매핑 조회
    agent_cfg: AgentLLMConfig = config.agent_llm_mapping.get(agent_name)
    if agent_cfg is None:
        raise ValueError(
            f"에이전트 '{agent_name}'에 대한 LLM 매핑이 config.yaml에 없습니다. "
            f"agent_llm_mapping 섹션을 확인하세요."
        )

    # 프로바이더 설정 조회
    provider_cfg = config.llm_providers.get(agent_cfg.provider)
    if provider_cfg is None:
        raise ValueError(
            f"프로바이더 '{agent_cfg.provider}'가 config.yaml의 "
            f"llm_providers에 정의되어 있지 않습니다."
        )

    # API 키를 환경변수에서 가져오기
    api_key = get_api_key(provider_cfg)

    # 모델 문자열 생성
    model_string = _build_model_string(agent_cfg.provider, agent_cfg.model)

    # CrewAI LLM 인스턴스 생성
    llm_kwargs = {
        "model": model_string,
        "api_key": api_key,
    }

    if provider_cfg.base_url:
        llm_kwargs["base_url"] = provider_cfg.base_url
    if agent_cfg.temperature is not None:
        llm_kwargs["temperature"] = agent_cfg.temperature
    # CrewAI currently remaps max_completion_tokens back into max_tokens when
    # building LiteLLM params. For OpenAI GPT-5 models that yields a 400 error,
    # so OpenAI requests intentionally omit token-cap kwargs here.
    if agent_cfg.max_tokens is not None and agent_cfg.provider != "openai":
        llm_kwargs["max_tokens"] = agent_cfg.max_tokens

    # Disable parallel tool calls for OpenAI models — GPT-5 tends to batch
    # multiple tool calls into a JSON array, which CrewAI's ReAct executor rejects.
    if agent_cfg.provider == "openai":
        llm_kwargs["parallel_tool_calls"] = False

    # LiteLLM retry: 429/529 에러 시 최대 5회 자동 재시도
    llm_kwargs["num_retries"] = 5

    llm = LLM(**llm_kwargs)

    return llm


def create_all_agent_llms(
    config: Optional[SystemConfig] = None,
) -> Dict[str, LLM]:
    """
    config.yaml에 정의된 모든 에이전트의 LLM 인스턴스를 한 번에 생성합니다.

    Returns:
        Dict[str, LLM]: {에이전트명: LLM 인스턴스} 딕셔너리
    """
    if config is None:
        config = get_config()

    llms: Dict[str, LLM] = {}
    for agent_name in config.agent_llm_mapping:
        try:
            llms[agent_name] = create_llm_for_agent(agent_name, config)
        except ValueError as e:
            print(f"[경고] {agent_name} LLM 생성 실패: {e}")

    return llms


def make_reasoning_llm(
    base_llm: LLM,
    budget_tokens: int = 8000,
) -> LLM:
    """Return an LLM with extended thinking enabled for reasoning-heavy agents.

    Only applied to Claude (Anthropic) models — other providers fall back to base_llm.
    Requires temperature=1.0 (Claude API enforces this for thinking mode).

    Falls back to base_llm if the thinking parameter is not supported by the
    installed CrewAI/litellm version.
    """
    model = getattr(base_llm, "model", "") or ""
    is_claude = "claude" in model.lower() or "anthropic" in model.lower()

    if not is_claude:
        return base_llm

    try:
        api_key = getattr(base_llm, "api_key", None)
        num_retries = getattr(base_llm, "num_retries", 3)

        kwargs: dict = {
            "model": model,
            "temperature": 1.0,
            "thinking": {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            },
            "num_retries": num_retries,
        }
        if api_key:
            kwargs["api_key"] = api_key

        return LLM(**kwargs)
    except Exception:
        return base_llm


def get_available_providers(
    config: Optional[SystemConfig] = None,
) -> Dict[str, list]:
    """
    설정된 프로바이더와 사용 가능한 모델 목록을 반환합니다.
    CLI에서 사용자에게 선택지를 보여줄 때 사용합니다.
    """
    if config is None:
        config = get_config()

    result = {}
    for name, provider in config.llm_providers.items():
        # API 키가 설정되어 있는지 확인
        key = os.getenv(provider.api_key_env, "")
        result[name] = {
            "models": provider.available_models,
            "api_key_configured": bool(key),
            "api_key_env": provider.api_key_env,
        }
    return result
