"""SQLite persistence and durable MQTT outbox."""

from .database import Database, SCHEMA_VERSION
from .models import (
    InboundSmsRecord,
    InboundStatus,
    OutboxRecord,
    OutboxStatus,
    QueueDisposition,
    RawSmsInput,
    StoreDisposition,
)
from .repository import (
    SmsRepository,
    canonical_logical_message,
    compute_logical_dedupe_key,
    compute_raw_dedupe_key,
)

__all__ = [
    "Database",
    "SCHEMA_VERSION",
    "InboundSmsRecord",
    "InboundStatus",
    "OutboxRecord",
    "OutboxStatus",
    "QueueDisposition",
    "RawSmsInput",
    "StoreDisposition",
    "SmsRepository",
    "canonical_logical_message",
    "compute_logical_dedupe_key",
    "compute_raw_dedupe_key",
]
