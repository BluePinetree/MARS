"""
Celery 앱 설정 및 초기화.

Redis를 메시지 브로커 및 결과 백엔드로 사용합니다.
장시간 실행되는 연구 워크플로우를 비동기 태스크로 처리합니다.

실행 방법:
    celery -A tasks.celery_app worker --loglevel=info --concurrency=2
"""

import os
from celery import Celery

# Redis 연결 설정 (환경변수 또는 기본값)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Celery 앱 생성
celery_app = Celery(
    "autonomous_research",
    broker=REDIS_URL,
    backend=RESULT_BACKEND,
    include=[
        "tasks.research_tasks",
    ],
)

# Celery 설정
celery_app.conf.update(
    # 직렬화 설정
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 타임존 설정
    timezone="Asia/Seoul",
    enable_utc=True,

    # 태스크 설정
    task_track_started=True,
    task_time_limit=7200,       # 최대 2시간
    task_soft_time_limit=6600,  # 소프트 리밋 1시간 50분
    task_acks_late=True,        # 완료 후 ACK (안정성)
    worker_prefetch_multiplier=1,  # 한 번에 하나씩 처리

    # 결과 설정
    result_expires=86400,       # 결과 24시간 보관
    result_extended=True,       # 확장 결과 정보

    # 재시도 설정
    task_default_retry_delay=60,
    task_max_retries=3,

    # 큐 설정
    task_default_queue="research",
    task_queues={
        "research": {
            "exchange": "research",
            "routing_key": "research",
        },
        "experiment": {
            "exchange": "experiment",
            "routing_key": "experiment",
        },
    },

    # 모니터링
    worker_send_task_events=True,
    task_send_sent_event=True,
)
