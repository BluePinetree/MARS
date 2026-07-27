"""Execution-environment routes (P1-3).

설정 시점에 "적합한"(파이프라인 필수 패키지를 갖춘) 가상환경 목록을 UI에 제공한다.
능력 기반 탐지 로직은 core/env_detect.py에서 공유한다(헤드리스 러너와 동일).

후보 환경 검사는 서브프로세스로 import를 시도하므로(수 초 소요) 60초 캐시를 둔다.
"""
from __future__ import annotations

import sys
import time

from fastapi import APIRouter

from core.env_detect import list_suitable_environments

router = APIRouter(prefix="/api/v1/environments", tags=["environments"])

_CACHE_TTL = 600.0  # env 목록은 자주 바뀌지 않으므로 10분 캐시(첫 호출만 프로빙 비용)
_cache: dict = {"ts": 0.0, "data": None}


@router.get("")
def list_environments(refresh: bool = False) -> dict:
    """적합한 실행 환경 목록.

    각 항목: {name, executable, python_version, suitable, missing, is_current, recommended}
    - recommended=True 인 항목이 기본 선택 후보(현재 서버 환경 우선).
    - refresh=true 로 캐시를 무시하고 재탐색할 수 있다.
    """
    now = time.time()
    if not refresh and _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]
    envs = list_suitable_environments()
    data = {
        "environments": envs,
        "current_executable": sys.executable,
        "count": len(envs),
    }
    _cache["ts"] = now
    _cache["data"] = data
    return data
