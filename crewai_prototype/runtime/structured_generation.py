"""Helpers for real LLM-backed structured JSON generation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(slots=True)
class StructuredGenerationError(Exception):
    """Raised when an LLM call cannot be parsed into the required structure."""

    agent_name: str
    schema_name: str
    reason: str
    raw_response: str | None = None
    attempt: int = 0
    cause: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        return f"{self.schema_name} generation failed for {self.agent_name}: {self.reason}"


def create_llm_for_agent(agent_name: str, config: Any | None = None) -> Any:
    """Lazy wrapper around the existing CrewAI LLM factory."""
    from core.llm_factory import create_llm_for_agent as load_llm_for_agent

    return load_llm_for_agent(agent_name, config)


def _schema_to_text(output_schema: Any) -> str:
    return json.dumps(output_schema, ensure_ascii=False, indent=2, sort_keys=True)


def _coerce_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    for attr in ("content", "text", "output"):
        value = getattr(response, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(response, dict):
        content = response.get("content")
        if isinstance(content, str):
            return content
    return str(response)


def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        raise ValueError("empty response")

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    if text.startswith("json\n"):
        text = text[5:].strip()

    if text.startswith("{") and text.endswith("}"):
        return text
    if text.startswith("[") and text.endswith("]"):
        return text

    start_candidates = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not start_candidates:
        raise ValueError("no JSON object found")
    start = min(start_candidates)
    end = max(text.rfind("}"), text.rfind("]"))
    if end <= start:
        raise ValueError("incomplete JSON envelope")
    return text[start : end + 1]


def _parse_json_payload(raw_text: str, *, schema_name: str, required_keys: Iterable[str] | None = None) -> dict[str, Any]:
    try:
        json_text = _extract_json_text(raw_text)
        payload = json.loads(json_text)
    except Exception as exc:  # pragma: no cover - error path exercised in tests
        raise ValueError(f"invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")

    if required_keys:
        missing = [key for key in required_keys if key not in payload]
        if missing:
            raise ValueError(f"missing required keys: {missing}")

    return payload


def _build_messages(*, prompt: str, schema_name: str, output_schema: Any) -> list[dict[str, str]]:
    schema_text = _schema_to_text(output_schema)
    system = (
        "You are a structured generation engine.\n"
        f"Return exactly one JSON object for schema '{schema_name}'.\n"
        "Do not wrap the answer in markdown fences.\n"
        "Do not add commentary, prose, bullet points, or code blocks.\n"
        "Every key required by the schema must be present.\n"
        "Use plain JSON values only.\n"
    )
    user = f"Task:\n{prompt}\n\nSchema:\n{schema_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_text(
    prompt: str,
    *,
    agent_name: str = "coder",
    max_tokens: int = 8192,
    llm: Any | None = None,
    config: Any | None = None,
) -> str:
    """Plain-text LLM call — no JSON schema constraint.

    Used for generating Python source files where the output must be raw code,
    not a JSON-wrapped string.
    """
    if llm is None:
        llm = create_llm_for_agent(agent_name, config)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a Python code generation engine.\n"
                "Output ONLY valid Python source code.\n"
                "Do NOT wrap code in markdown fences.\n"
                "Do NOT add prose, commentary, or explanations.\n"
                "The first line of your response must be Python (import, def, class, or a comment)."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    return _coerce_text(llm.call(messages=messages))


def generate_structured_json(
    *,
    agent_name: str,
    schema_name: str,
    prompt: str,
    output_schema: Any,
    required_keys: Iterable[str] | None = None,
    llm: Any | None = None,
    config: Any | None = None,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Call an LLM and parse a structured JSON object.

    The helper retries once with a repair prompt if the first response cannot be
    parsed into valid JSON. Missing provider or parse failures propagate as a
    StructuredGenerationError.
    """

    if llm is None:
        llm = create_llm_for_agent(agent_name, config)

    messages = _build_messages(prompt=prompt, schema_name=schema_name, output_schema=output_schema)
    last_error: StructuredGenerationError | None = None
    for attempt in range(1, max_attempts + 1):
        raw_response = _coerce_text(llm.call(messages=messages))
        try:
            return _parse_json_payload(
                raw_response,
                schema_name=schema_name,
                required_keys=required_keys,
            )
        except Exception as exc:
            last_error = StructuredGenerationError(
                agent_name=agent_name,
                schema_name=schema_name,
                reason=str(exc),
                raw_response=raw_response,
                attempt=attempt,
                cause=type(exc).__name__,
            )
            if attempt >= max_attempts:
                raise last_error from exc
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a structured generation engine.\n"
                        f"Return exactly one JSON object for schema '{schema_name}'.\n"
                        "The previous response was invalid.\n"
                        "Do not wrap the answer in markdown fences.\n"
                        "Do not add commentary, prose, bullet points, or code blocks.\n"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{prompt}\n\n"
                        f"Schema:\n{_schema_to_text(output_schema)}\n\n"
                        f"Invalid previous response:\n{raw_response}\n\n"
                        f"Parse error:\n{last_error.reason}\n\n"
                        "Return only valid JSON now."
                    ),
                },
            ]

    if last_error is None:  # pragma: no cover - defensive
        raise StructuredGenerationError(
            agent_name=agent_name,
            schema_name=schema_name,
            reason="unknown structured generation failure",
        )
    raise last_error
