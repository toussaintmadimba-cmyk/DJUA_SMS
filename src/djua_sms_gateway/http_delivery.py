"""Reliable HTTP delivery from the persistent HTTP outbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from typing import Mapping, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from djua_sms_gateway.mqtt.publisher import compute_backoff_seconds
from djua_sms_gateway.storage.models import HttpOutboxRecord, OutboxStatus
from djua_sms_gateway.storage.repository import SmsRepository

logger = logging.getLogger(__name__)


class HttpTransportProtocol(Protocol):
    def post(
        self,
        url: str,
        payload_json: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> int:
        """POST JSON and return the HTTP status code."""


class UrllibHttpTransport:
    """Small stdlib HTTP transport to avoid adding another runtime dependency."""

    def post(
        self,
        url: str,
        payload_json: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> int:
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request_headers.update(headers)
        request = Request(
            url,
            data=payload_json.encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return int(response.status)
        except HTTPError as exc:
            return int(exc.code)


class HttpPublishDisposition(str, Enum):
    PUBLISHED = "PUBLISHED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"
    NOT_PENDING = "NOT_PENDING"


@dataclass(frozen=True)
class HttpPublishResult:
    disposition: HttpPublishDisposition
    outbox_id: int
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class HttpWorkerRunResult:
    due: int = 0
    published: int = 0
    retry_scheduled: int = 0
    failed: int = 0


class HttpPublisher:
    def __init__(
        self,
        transport: HttpTransportProtocol,
        repository: SmsRepository,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 10.0,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 300.0,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.transport = transport
        self.repository = repository
        self.headers = dict(headers or {})
        self.timeout_seconds = timeout_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self._clock = clock

    def publish(self, outbox: HttpOutboxRecord) -> HttpPublishResult:
        if outbox.status is not OutboxStatus.PENDING:
            return HttpPublishResult(
                HttpPublishDisposition.NOT_PENDING,
                outbox.id,
            )

        logger.info(
            "HTTP_OUTBOX_POST_START outbox_id=%s url=%s attempt_count=%s",
            outbox.id,
            outbox.url,
            outbox.attempt_count,
        )
        try:
            status = self.transport.post(
                outbox.url,
                outbox.payload_json,
                headers=self.headers,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as exc:
            updated = self._schedule_retry(
                outbox,
                f"{type(exc).__name__}: {exc}",
            )
            return HttpPublishResult(
                HttpPublishDisposition.RETRY_SCHEDULED,
                outbox.id,
                error=updated.last_error,
            )

        if 200 <= status < 300:
            self.repository.mark_http_outbox_published(outbox.id)
            logger.info(
                "HTTP_OUTBOX_POST_OK outbox_id=%s status=%s",
                outbox.id,
                status,
            )
            return HttpPublishResult(
                HttpPublishDisposition.PUBLISHED,
                outbox.id,
                status_code=status,
            )

        error = f"HTTP status {status}"
        if status in {408, 425, 429} or status >= 500:
            updated = self._schedule_retry(outbox, error)
            return HttpPublishResult(
                HttpPublishDisposition.RETRY_SCHEDULED,
                outbox.id,
                status_code=status,
                error=updated.last_error,
            )

        self.repository.record_http_publish_failure(
            outbox.id,
            error=error,
            terminal=True,
        )
        logger.warning(
            "HTTP_OUTBOX_FAILED outbox_id=%s status=%s",
            outbox.id,
            status,
        )
        return HttpPublishResult(
            HttpPublishDisposition.FAILED,
            outbox.id,
            status_code=status,
            error=error,
        )

    def _schedule_retry(
        self,
        outbox: HttpOutboxRecord,
        error: str,
    ) -> HttpOutboxRecord:
        delay = compute_backoff_seconds(
            outbox.attempt_count,
            base_seconds=self.retry_base_seconds,
            max_seconds=self.retry_max_seconds,
        )
        next_attempt = self._clock() + timedelta(seconds=delay)
        updated = self.repository.record_http_publish_failure(
            outbox.id,
            error=error,
            next_attempt_at=next_attempt.isoformat(),
        )
        logger.info(
            "HTTP_OUTBOX_RETRY_SCHEDULED outbox_id=%s attempt_count=%s next_attempt_at=%s",
            outbox.id,
            updated.attempt_count,
            updated.next_attempt_at,
        )
        return updated


class HttpOutboxWorker:
    def __init__(
        self,
        repository: SmsRepository,
        publisher: HttpPublisher,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self._clock = clock

    def run_once(self, *, limit: int | None = None) -> HttpWorkerRunResult:
        pending = self.repository.list_pending_http_outbox(
            limit=limit,
            due_before=self._clock().isoformat(),
        )
        published = retry = failed = 0
        for outbox in pending:
            result = self.publisher.publish(outbox)
            if result.disposition is HttpPublishDisposition.PUBLISHED:
                published += 1
            elif result.disposition is HttpPublishDisposition.RETRY_SCHEDULED:
                retry += 1
            elif result.disposition is HttpPublishDisposition.FAILED:
                failed += 1
        return HttpWorkerRunResult(
            due=len(pending),
            published=published,
            retry_scheduled=retry,
            failed=failed,
        )

    def shutdown(self) -> None:
        return None
