"""
tasks 패키지.
Celery 비동기 태스크를 제공합니다.
Redis를 브로커로 사용하여 장시간 실행되는 연구 워크플로우를 비동기 처리합니다.

실행 방법:
    # Redis 서버 시작 (Docker 또는 로컬)
    docker run -d -p 6379:6379 redis:7-alpine

    # Celery 워커 시작
    celery -A tasks.celery_app worker --loglevel=info --concurrency=2

    # (선택) Celery 모니터링
    celery -A tasks.celery_app flower --port=5555
"""

from tasks.celery_app import celery_app
from tasks.research_tasks import (
    run_research_workflow,
    run_single_experiment,
    get_task_status,
    cancel_task,
)

__all__ = [
    "celery_app",
    "run_research_workflow",
    "run_single_experiment",
    "get_task_status",
    "cancel_task",
]
