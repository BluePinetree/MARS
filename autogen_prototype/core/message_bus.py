"""
RabbitMQ 메시지 버스

에이전트 간 메시지를 비동기적으로 전달하기 위한 RabbitMQ 기반 메시지 버스입니다.
RabbitMQ가 비활성화된 경우, 인메모리 큐를 사용하는 폴백 모드로 동작합니다.

설계 원칙:
- RabbitMQ 사용 시: 에이전트 프로세스 간 비동기 메시지 전달
- RabbitMQ 미사용 시: asyncio.Queue 기반 인메모리 메시지 전달
- 모든 메시지는 표준 JSONL 로그 형식으로 기록됨
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from dataclasses import dataclass, field, asdict

from core.config_loader import RabbitMQConfig

# rsp/ telemetry (optional)
_RSP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RSP_ROOT) not in sys.path:
    sys.path.insert(0, str(_RSP_ROOT))

try:
    from rsp.telemetry import NodeEvent, TelemetryStore
    _TELEMETRY_AVAILABLE = True
except Exception:
    _TELEMETRY_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================
# 메시지 데이터 모델
# ============================================================

@dataclass
class BusMessage:
    """메시지 버스를 통해 전달되는 메시지"""
    sender: str
    content: str
    message_type: str = "text"  # text, code, execution_result, system
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> BusMessage:
        data = json.loads(json_str)
        return cls(**data)


# ============================================================
# 메시지 버스 인터페이스
# ============================================================

class MessageBusInterface:
    """메시지 버스 추상 인터페이스"""

    async def connect(self) -> None:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def publish(self, message: BusMessage, routing_key: str = "") -> None:
        raise NotImplementedError

    async def subscribe(
        self,
        queue_name: str,
        callback: Callable[[BusMessage], Any],
    ) -> None:
        raise NotImplementedError

    async def broadcast(self, message: BusMessage) -> None:
        raise NotImplementedError


# ============================================================
# 인메모리 메시지 버스 (RabbitMQ 미사용 시 폴백)
# ============================================================

class InMemoryMessageBus(MessageBusInterface):
    """
    asyncio.Queue 기반 인메모리 메시지 버스.

    RabbitMQ가 비활성화된 경우 사용되는 경량 폴백 구현입니다.
    단일 프로세스 내에서 에이전트 간 메시지를 전달합니다.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[BusMessage]] = {}
        self._subscribers: dict[str, list[Callable[[BusMessage], Any]]] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._message_history: list[BusMessage] = []

    async def connect(self) -> None:
        self._running = True
        logger.info("[InMemoryMessageBus] 연결됨 (인메모리 모드)")

    async def disconnect(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("[InMemoryMessageBus] 연결 해제됨")

    async def publish(self, message: BusMessage, routing_key: str = "") -> None:
        """메시지를 특정 큐에 발행합니다."""
        self._message_history.append(message)

        if routing_key and routing_key in self._queues:
            await self._queues[routing_key].put(message)
        else:
            # 모든 큐에 브로드캐스트
            for queue in self._queues.values():
                await queue.put(message)

    async def broadcast(self, message: BusMessage) -> None:
        """모든 구독자에게 메시지를 브로드캐스트합니다."""
        self._message_history.append(message)

        if _TELEMETRY_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="autogen",
                    node=message.sender.lower(),
                    phase="message",
                    tokens_in=0,
                    tokens_out=0,
                    tool_calls=1 if message.message_type == "tool_call" else 0,
                ))
            except Exception:
                pass

        for queue_name, callbacks in self._subscribers.items():
            for callback in callbacks:
                try:
                    result = callback(message)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"[InMemoryMessageBus] 콜백 에러 ({queue_name}): {e}")

    async def subscribe(
        self,
        queue_name: str,
        callback: Callable[[BusMessage], Any],
    ) -> None:
        """특정 큐에 대한 구독을 등록합니다."""
        if queue_name not in self._queues:
            self._queues[queue_name] = asyncio.Queue()

        if queue_name not in self._subscribers:
            self._subscribers[queue_name] = []

        self._subscribers[queue_name].append(callback)
        logger.info(f"[InMemoryMessageBus] 구독 등록: {queue_name}")

    def get_message_history(self) -> list[BusMessage]:
        """전체 메시지 히스토리를 반환합니다."""
        return list(self._message_history)

    def clear_history(self) -> None:
        """메시지 히스토리를 초기화합니다."""
        self._message_history.clear()


# ============================================================
# RabbitMQ 메시지 버스
# ============================================================

class RabbitMQMessageBus(MessageBusInterface):
    """
    RabbitMQ 기반 비동기 메시지 버스.

    aio-pika를 사용하여 RabbitMQ에 연결하고,
    에이전트 프로세스 간 메시지를 비동기적으로 전달합니다.
    """

    def __init__(self, config: RabbitMQConfig) -> None:
        self._config = config
        self._connection = None
        self._channel = None
        self._exchange = None
        self._message_history: list[BusMessage] = []

    async def connect(self) -> None:
        """RabbitMQ에 연결합니다."""
        try:
            import aio_pika

            url = (
                f"amqp://{self._config.username}:{self._config.password}"
                f"@{self._config.host}:{self._config.port}/"
            )
            self._connection = await aio_pika.connect_robust(url)
            self._channel = await self._connection.channel()

            # fanout exchange 생성 (브로드캐스트용)
            self._exchange = await self._channel.declare_exchange(
                self._config.exchange_name,
                aio_pika.ExchangeType.FANOUT,
                durable=True,
            )

            logger.info(
                f"[RabbitMQMessageBus] 연결됨: "
                f"{self._config.host}:{self._config.port}"
            )
        except Exception as e:
            logger.error(f"[RabbitMQMessageBus] 연결 실패: {e}")
            raise

    async def disconnect(self) -> None:
        """RabbitMQ 연결을 종료합니다."""
        if self._connection:
            await self._connection.close()
            logger.info("[RabbitMQMessageBus] 연결 해제됨")

    async def publish(self, message: BusMessage, routing_key: str = "") -> None:
        """메시지를 발행합니다."""
        import aio_pika

        if not self._exchange:
            raise RuntimeError("RabbitMQ에 연결되지 않았습니다.")

        self._message_history.append(message)

        amqp_message = aio_pika.Message(
            body=message.to_json().encode("utf-8"),
            content_type="application/json",
        )
        await self._exchange.publish(amqp_message, routing_key=routing_key)

    async def broadcast(self, message: BusMessage) -> None:
        """모든 구독자에게 메시지를 브로드캐스트합니다."""
        await self.publish(message, routing_key="")

    async def subscribe(
        self,
        queue_name: str,
        callback: Callable[[BusMessage], Any],
    ) -> None:
        """특정 큐에 대한 구독을 등록합니다."""
        if not self._channel or not self._exchange:
            raise RuntimeError("RabbitMQ에 연결되지 않았습니다.")

        queue = await self._channel.declare_queue(
            f"{self._config.queue_prefix}{queue_name}",
            durable=True,
        )
        await queue.bind(self._exchange)

        async def _on_message(message):
            async with message.process():
                bus_msg = BusMessage.from_json(message.body.decode("utf-8"))
                result = callback(bus_msg)
                if asyncio.iscoroutine(result):
                    await result

        await queue.consume(_on_message)
        logger.info(f"[RabbitMQMessageBus] 구독 등록: {queue_name}")

    def get_message_history(self) -> list[BusMessage]:
        return list(self._message_history)


# ============================================================
# 팩토리 함수
# ============================================================

def create_message_bus(config: RabbitMQConfig) -> MessageBusInterface:
    """
    설정에 따라 적절한 메시지 버스 인스턴스를 생성합니다.

    Args:
        config: RabbitMQ 설정

    Returns:
        MessageBusInterface 구현체
    """
    if config.enabled:
        logger.info("[MessageBus] RabbitMQ 모드로 생성")
        return RabbitMQMessageBus(config)
    else:
        logger.info("[MessageBus] 인메모리 모드로 생성 (RabbitMQ 비활성화)")
        return InMemoryMessageBus()
