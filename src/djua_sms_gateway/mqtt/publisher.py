"""Reliable bridge from persistent outbox records to MQTT PUBACK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
import threading
import time

from djua_sms_gateway.mqtt.client import MqttClientProtocol
from djua_sms_gateway.storage.models import OutboxRecord, OutboxStatus
from djua_sms_gateway.storage.repository import SmsRepository

logger = logging.getLogger(__name__)


class PublishDisposition(str, Enum):
    STARTED = "STARTED"
    ACKED = "ACKED"
    FAILED = "FAILED"
    ALREADY_IN_FLIGHT = "ALREADY_IN_FLIGHT"
    NOT_PENDING = "NOT_PENDING"


@dataclass(frozen=True)
class PublishResult:
    disposition: PublishDisposition
    outbox_id: int
    mid: int | None = None
    error: str | None = None


@dataclass
class _InFlight:
    outbox_id: int
    started_monotonic: float


def compute_backoff_seconds(
    attempt_count: int,
    *,
    base_seconds: float,
    max_seconds: float,
) -> float:
    if attempt_count < 0:
        raise ValueError("attempt_count must be >= 0")
    exponent = min(attempt_count, 30)
    return min(max_seconds, base_seconds * (2 ** exponent))


class MqttPublisher:
    def __init__(
        self,
        client: MqttClientProtocol,
        repository: SmsRepository,
        *,
        publish_timeout_seconds: float = 10.0,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 300.0,
        monotonic=time.monotonic,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.client = client
        self.repository = repository
        self.publish_timeout_seconds = publish_timeout_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self._monotonic = monotonic
        self._clock = clock
        self._lock = threading.Lock()
        self._mid_to_inflight: dict[int, _InFlight] = {}
        self._outbox_to_mid: dict[int, int] = {}
        self._early_acks: set[int] = set()
        self._ignored_mids: set[int] = set()
        client.set_publish_ack_handler(self._on_publish_ack)

    def is_in_flight(self, outbox_id: int) -> bool:
        with self._lock:
            return outbox_id in self._outbox_to_mid

    def publish(self, outbox: OutboxRecord) -> PublishResult:
        if outbox.status is not OutboxStatus.PENDING:
            return PublishResult(PublishDisposition.NOT_PENDING, outbox.id)
        if self.is_in_flight(outbox.id):
            return PublishResult(PublishDisposition.ALREADY_IN_FLIGHT, outbox.id)

        logger.info(
            "OUTBOX_PUBLISH_START outbox_id=%s topic=%s attempt_count=%s",
            outbox.id,
            outbox.topic,
            outbox.attempt_count,
        )
        try:
            receipt = self.client.publish(
                outbox.topic,
                outbox.payload_json,
                qos=outbox.qos,
                retain=outbox.retain,
            )
        except Exception as exc:
            updated = self.record_failure(outbox, str(exc))
            logger.warning(
                "OUTBOX_PUBLISH_FAILED outbox_id=%s error=%s",
                outbox.id,
                type(exc).__name__,
            )
            return PublishResult(
                PublishDisposition.FAILED,
                outbox.id,
                error=updated.last_error,
            )

        acked_early = False
        with self._lock:
            if receipt.mid in self._early_acks:
                self._early_acks.remove(receipt.mid)
                acked_early = True
            else:
                self._mid_to_inflight[receipt.mid] = _InFlight(
                    outbox_id=outbox.id,
                    started_monotonic=self._monotonic(),
                )
                self._outbox_to_mid[outbox.id] = receipt.mid

        if acked_early:
            self._mark_published(outbox.id, receipt.mid)
            return PublishResult(PublishDisposition.ACKED, outbox.id, mid=receipt.mid)
        return PublishResult(PublishDisposition.STARTED, outbox.id, mid=receipt.mid)

    def record_failure(self, outbox: OutboxRecord, error: str) -> OutboxRecord:
        delay = compute_backoff_seconds(
            outbox.attempt_count,
            base_seconds=self.retry_base_seconds,
            max_seconds=self.retry_max_seconds,
        )
        next_attempt = self._clock() + timedelta(seconds=delay)
        updated = self.repository.record_publish_failure(
            outbox.id,
            error=error,
            next_attempt_at=next_attempt.isoformat(),
        )
        logger.info(
            "OUTBOX_RETRY_SCHEDULED outbox_id=%s attempt_count=%s next_attempt_at=%s",
            outbox.id,
            updated.attempt_count,
            updated.next_attempt_at,
        )
        return updated

    def expire_timeouts(self) -> list[int]:
        now = self._monotonic()
        expired: list[tuple[int, int]] = []
        with self._lock:
            for mid, item in list(self._mid_to_inflight.items()):
                if now - item.started_monotonic >= self.publish_timeout_seconds:
                    expired.append((mid, item.outbox_id))
                    self._mid_to_inflight.pop(mid, None)
                    self._outbox_to_mid.pop(item.outbox_id, None)
                    self._ignored_mids.add(mid)
        outbox_ids: list[int] = []
        for mid, outbox_id in expired:
            current = self.repository.get_outbox(outbox_id)
            if current and current.status is OutboxStatus.PENDING:
                self.record_failure(current, f"PUBACK timeout mid={mid}")
                outbox_ids.append(outbox_id)
        return outbox_ids

    def _on_publish_ack(self, mid: int) -> None:
        outbox_id: int | None = None
        with self._lock:
            if mid in self._ignored_mids:
                self._ignored_mids.remove(mid)
                return
            item = self._mid_to_inflight.pop(mid, None)
            if item is None:
                self._early_acks.add(mid)
                return
            outbox_id = item.outbox_id
            self._outbox_to_mid.pop(outbox_id, None)
        self._mark_published(outbox_id, mid)

    def _mark_published(self, outbox_id: int, mid: int) -> None:
        try:
            self.repository.mark_outbox_published(outbox_id)
        except Exception:
            logger.exception(
                "OUTBOX_PUBACK_COMMIT_FAILED outbox_id=%s mid=%s",
                outbox_id,
                mid,
            )
            return
        logger.info("OUTBOX_PUBLISH_ACK outbox_id=%s mid=%s", outbox_id, mid)
