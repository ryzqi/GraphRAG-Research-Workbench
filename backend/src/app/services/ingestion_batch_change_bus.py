from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from time import monotonic
import uuid

from app.core.settings import Settings
from app.integrations.redis_client import RedisClient
from app.integrations.redis_client import close_redis_client, create_redis_client
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)
INGESTION_BATCH_CHANGED_EVENT = "changed"


def _normalize_pubsub_data(data: object) -> str | None:
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except Exception:
            return None
    if isinstance(data, str):
        normalized = data.strip()
        return normalized or None
    return None


@dataclass(slots=True)
class IngestionBatchChangeListener:
    pubsub: PubSub
    channel: str

    async def wait(self, *, timeout: float) -> bool:
        bounded_timeout = max(float(timeout), 0.0)
        deadline = monotonic() + bounded_timeout
        while True:
            message = await self.pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=bounded_timeout,
            )
            if message is None:
                return False
            payload = _normalize_pubsub_data(message.get("data"))
            if payload:
                return payload == INGESTION_BATCH_CHANGED_EVENT
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            bounded_timeout = remaining

    async def aclose(self) -> None:
        try:
            await self.pubsub.unsubscribe(self.channel)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(
                "Ingestion batch change listener unsubscribe failed",
                extra={"channel": self.channel, "error": str(exc)},
            )
        try:
            await self.pubsub.aclose()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(
                "Ingestion batch change listener close failed",
                extra={"channel": self.channel, "error": str(exc)},
            )


@dataclass(slots=True)
class IngestionBatchChangeBus:
    redis: RedisClient

    def _channel(self, batch_id: uuid.UUID) -> str:
        return f"ingestion-batch:{batch_id}"

    async def publish(
        self,
        *,
        batch_id: uuid.UUID,
        event: str = INGESTION_BATCH_CHANGED_EVENT,
    ) -> None:
        try:
            await self.redis.publish(self._channel(batch_id), event)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(
                "Ingestion batch change publish failed",
                extra={"batch_id": str(batch_id), "error": str(exc)},
            )

    @asynccontextmanager
    async def listen(
        self,
        *,
        batch_id: uuid.UUID,
    ) -> AsyncIterator[IngestionBatchChangeListener]:
        channel = self._channel(batch_id)
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe(channel)
        except Exception:
            await pubsub.aclose()
            raise
        listener = IngestionBatchChangeListener(pubsub=pubsub, channel=channel)
        try:
            yield listener
        finally:
            await listener.aclose()


@asynccontextmanager
async def open_ingestion_batch_change_bus(
    *,
    settings: Settings,
) -> AsyncIterator[IngestionBatchChangeBus | None]:
    redis: RedisClient | None = None
    try:
        try:
            redis = create_redis_client(settings)
        except Exception as exc:
            logger.warning(
                "Ingestion batch change bus unavailable; continuing without realtime notifications",
                extra={"error": str(exc)},
            )
            yield None
            return
        yield IngestionBatchChangeBus(redis)
    finally:
        await close_redis_client(redis)
