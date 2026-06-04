"""
core/json_extractor.py
======================
LLM 출력 텍스트에서 JSON 객체를 안전하게 추출하는 유틸리티.

추출 우선순위:
  1. 전체 텍스트가 유효한 JSON인 경우
  2. ```json ... ``` 코드 블록
  3. 첫 번째 { 부터 bracket-balanced } 까지
  4. 잘린 JSON 복구 (닫는 괄호 추가)
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def extract_json_object(text: str) -> dict | None:
    """
    LLM 출력 텍스트에서 첫 번째 유효한 JSON 객체를 추출한다.
    실패 시 None 반환.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 1. 전체 텍스트 직접 파싱
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. ```json ... ``` 또는 ``` ... ``` 코드 블록 추출
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block:
        try:
            obj = json.loads(code_block.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 3. Bracket-balanced { } 추출
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    end = -1

    for i, ch in enumerate(text[start:], start):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end > start:
        try:
            obj = json.loads(text[start:end])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # 4. 잘린 JSON 복구 — 열린 괄호 스택으로 닫는 문자 역순 추가
    #    예: {"a": [1,2  →  스택=[}, ]]  →  복구: {"a": [1,2]}
    partial = text[start:]
    stack: list[str] = []
    in_string = False
    escaped = False
    _CLOSE = {"{": "}", "[": "]"}
    _OPEN_OF = {"}": "{", "]": "["}

    for ch in partial:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(_CLOSE[ch])
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()

    if stack:
        closing = "".join(reversed(stack))
        recovered = partial.rstrip(",\n\r ") + closing
        try:
            obj = json.loads(recovered)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def extract_and_validate(text: str, model_cls: type[T]) -> T | None:
    """
    JSON 추출 후 Pydantic 모델로 검증.
    추출 실패 또는 스키마 불일치 시 None 반환.
    """
    obj = extract_json_object(text)
    if obj is None:
        return None
    try:
        return model_cls.model_validate(obj)
    except ValidationError:
        return None
