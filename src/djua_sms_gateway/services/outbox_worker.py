"""Synchronous worker that drains due MQTT outbox rows deterministically."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from djua_sms_gateway.mqtt.client import MqttClientProtocol
from djua_sms_gateway.mqtt.publisher import MqttPublisher, PublishDisposition
from djua_sms_gateway.storage.repository import SmsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerRunResult:
    due: int = 0
    started: int = 0
    acked_immediately: int = 0
    failed: int = 0
    skipped_in_flight: int = 0
    connect_failed: bool = False


class MqttOutboxWorker:
    def __init__(
        self,
        repository: SmsRepository,
        client: MqttClientProtocol,
        publisher: MqttPublisher,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.client = client
        self.publisher = publisher
        self._clock = clock

    def run_once(self, *, limit: int | None = None) -> WorkerRunResult:
        self.publisher.expire_timeouts()
        now = self._clock()
        pending = self.repository.list_pending_outbox(
            limit=limit,
            due_before=now.isoformat(),
        )
        if not pending:
            return WorkerRunResult()

        if not self.client.connected:
            try:
                self.client.connect()
            except Exception as exc:
                logger.warning("MQTT_CONNECT_FAILED error=%s", type(exc).__name__)
                for outbox in pending:
                    self.publisher.record_failure(
                        outbox,
                        f"MQTT connect failed: {exc}",
                    )
                return WorkerRunResult(
                    due=len(pending),
                    failed=len(pending),
                    connect_failed=True,
                )

        started = acked = failed = skipped = 0
        for outbox in pending:
            result = self.publisher.publish(outbox)
            if result.disposition is PublishDisposition.STARTED:
                started += 1
            elif result.disposition is PublishDisposition.ACKED:
                acked += 1
            elif result.disposition is PublishDisposition.FAILED:
                failed += 1
            elif result.disposition is PublishDisposition.ALREADY_IN_FLIGHT:
                skipped += 1

        return WorkerRunResult(
            due=len(pending),
            started=started,
            acked_immediately=acked,
            failed=failed,
            skipped_in_flight=skipped,
        )

    def shutdown(self) -> None:
        self.client.disconnect()
