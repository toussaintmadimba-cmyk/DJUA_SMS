"""Persistence models for inbound SMS messages and the MQTT outbox."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InboundStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INVALID = "INVALID"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class StoreDisposition(str, Enum):
    STORED = "STORED"
    DUPLICATE = "DUPLICATE"


class QueueDisposition(str, Enum):
    QUEUED = "QUEUED"
    DUPLICATE_LOGICAL = "DUPLICATE_LOGICAL"


@dataclass(frozen=True)
class RawSmsInput:
    sender: str
    raw_body: str
    modem_timestamp: str | None = None
    gateway_received_at: str | None = None


@dataclass(frozen=True)
class InboundSmsRecord:
    id: int
    sender: str
    modem_timestamp: str | None
    gateway_received_at: str
    raw_body: str
    raw_dedupe_key: str
    logical_dedupe_key: str | None
    protocol_version: str | None
    device_id: str | None
    sequence: int | None
    status: InboundStatus
    validation_status: str | None
    validation_warning: str | None
    validation_error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OutboxRecord:
    id: int
    sms_id: int
    topic: str
    payload_json: str
    qos: int
    retain: bool
    status: OutboxStatus
    attempt_count: int
    next_attempt_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str
    published_at: str | None


@dataclass(frozen=True)
class StoreRawSmsResult:
    disposition: StoreDisposition
    record: InboundSmsRecord

    @property
    def durably_stored(self) -> bool:
        return True


@dataclass(frozen=True)
class QueueResult:
    disposition: QueueDisposition
    sms_id: int
    outbox: OutboxRecord | None
    duplicate_of_sms_id: int | None = None
