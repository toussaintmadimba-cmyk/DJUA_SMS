"""Small sqlite3 database wrapper with explicit compatible migrations."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

SCHEMA_VERSION = 3


class ClosingConnection(sqlite3.Connection):
    """sqlite3 connection that also closes at the end of a with block."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS inbound_sms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    modem_timestamp TEXT NULL,
    gateway_received_at TEXT NOT NULL,
    raw_body TEXT NOT NULL,
    raw_dedupe_key TEXT NOT NULL UNIQUE,
    logical_dedupe_key TEXT NULL UNIQUE,
    protocol_version TEXT NULL,
    device_id TEXT NULL,
    sequence INTEGER NULL,
    message_id TEXT NULL,
    d2_content_hash TEXT NULL,
    auth_status TEXT NULL,
    security_status TEXT NULL,
    conflict_with_sms_id INTEGER NULL,
    status TEXT NOT NULL CHECK (
        status IN ('RECEIVED','INVALID','VALIDATED','QUEUED','PUBLISHED','FAILED')
    ),
    validation_status TEXT NULL,
    validation_warning TEXT NULL,
    validation_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mqtt_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sms_id INTEGER NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    qos INTEGER NOT NULL CHECK (qos IN (0,1,2)),
    retain INTEGER NOT NULL CHECK (retain IN (0,1)),
    status TEXT NOT NULL CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT NULL,
    FOREIGN KEY (sms_id) REFERENCES inbound_sms(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_inbound_sms_status
    ON inbound_sms(status);
CREATE INDEX IF NOT EXISTS idx_inbound_sms_message_id
    ON inbound_sms(message_id);
CREATE INDEX IF NOT EXISTS idx_outbox_status_next_attempt
    ON mqtt_outbox(status, next_attempt_at, id);

CREATE TABLE IF NOT EXISTS http_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sms_id INTEGER NOT NULL UNIQUE,
    url TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT NULL,
    FOREIGN KEY (sms_id) REFERENCES inbound_sms(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_http_outbox_status_next_attempt
    ON http_outbox(status, next_attempt_at, id);
"""

_MIGRATION_V1_TO_V2 = (
    "ALTER TABLE inbound_sms ADD COLUMN message_id TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN d2_content_hash TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN auth_status TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN security_status TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN conflict_with_sms_id INTEGER NULL",
    "CREATE INDEX IF NOT EXISTS idx_inbound_sms_message_id ON inbound_sms(message_id)",
)

_MIGRATION_V2_TO_V3 = """
CREATE TABLE IF NOT EXISTS http_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sms_id INTEGER NOT NULL UNIQUE,
    url TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT NULL,
    FOREIGN KEY (sms_id) REFERENCES inbound_sms(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_http_outbox_status_next_attempt
    ON http_outbox(status, next_attempt_at, id);
"""


class Database:
    """Owns schema initialization and short-lived SQLite connections."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        parent = Path(self.path).expanduser().parent
        if self.path != ":memory:":
            parent.mkdir(parents=True, exist_ok=True)

        with self.connect() as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {current_version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )

            if current_version == 0:
                connection.executescript(_SCHEMA)
                connection.execute(
                    f"PRAGMA user_version = {SCHEMA_VERSION}"
                )
                return

            if current_version == 1:
                for statement in _MIGRATION_V1_TO_V2:
                    connection.execute(statement)
                current_version = 2

            if current_version == 2:
                connection.executescript(_MIGRATION_V2_TO_V3)
                current_version = 3

            connection.executescript(_SCHEMA)
            connection.execute(
                f"PRAGMA user_version = {SCHEMA_VERSION}"
            )

    @contextmanager
    def transaction(
        self,
        *,
        immediate: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute(
                "BEGIN IMMEDIATE" if immediate else "BEGIN"
            )
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
