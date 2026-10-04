"""SQLite repository implementing non-loss, deduplication and outbox semantics."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from djua_sms_gateway.protocol.d2 import D2Message, derive_message_id
from djua_sms_gateway.protocol.models import SmsTelemetry, ValidationResult

from .database import Database
from .models import (
    InboundSmsRecord,
    InboundStatus,
    OutboxRecord,
    OutboxStatus,
    QueueDisposition,
    QueueResult,
    RawSmsInput,
    StoreDisposition,
    StoreRawSmsResult,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_raw_dedupe_key(raw: RawSmsInput) -> str:
    """Hash sender + modem time when present + exact raw body.

    If the modem timestamp is unavailable, the exact sender/body pair is used.
    D1 embeds sequence/RTC/uptime, so an identical body is intentionally treated
    as the same received message rather than creating a second logical delivery.
    """

    return _sha256_json(
        {
            "v": "raw-v1",
            "sender": raw.sender,
            "modem_timestamp": raw.modem_timestamp or "",
            "raw_body": raw.raw_body,
        }
    )


def canonical_logical_message(telemetry: SmsTelemetry) -> str:
    """Return a stable semantic D1 representation excluding transport auth text.

    Values belonging to a group whose validity flag is false are canonicalized
    to null because the normalizer deliberately ignores those raw values.
    """

    value = {
        "protocol_version": telemetry.protocol_version,
        "device_id": telemetry.device_id,
        "sequence": telemetry.sequence,
        "rtc": telemetry.rtc if telemetry.rtc_valid else None,
        "timezone_minutes": (
            telemetry.timezone_minutes if telemetry.rtc_valid else None
        ),
        "uptime_ms": telemetry.uptime_ms,
        "interval_seconds": telemetry.interval_seconds,
        "latitude": telemetry.latitude if telemetry.gps_valid else None,
        "longitude": telemetry.longitude if telemetry.gps_valid else None,
        "battery_voltage": (
            telemetry.battery_voltage if telemetry.battery_valid else None
        ),
        "battery_current": (
            telemetry.battery_current if telemetry.battery_valid else None
        ),
        "battery_power": telemetry.battery_power if telemetry.battery_valid else None,
        "solar_voltage": telemetry.solar_voltage if telemetry.solar_valid else None,
        "solar_current": telemetry.solar_current if telemetry.solar_valid else None,
        "solar_power": telemetry.solar_power if telemetry.solar_valid else None,
        "solar_energy_interval_wh": (
            telemetry.solar_energy_interval_wh if telemetry.solar_valid else None
        ),
        "ac_voltage": telemetry.ac_voltage if telemetry.ac_valid else None,
        "ac_current": telemetry.ac_current if telemetry.ac_valid else None,
        "ac_active_power": (
            telemetry.ac_active_power if telemetry.ac_valid else None
        ),
        "ac_apparent_power": (
            telemetry.ac_apparent_power if telemetry.ac_valid else None
        ),
        "ac_energy_interval_wh": (
            telemetry.ac_energy_interval_wh if telemetry.ac_valid else None
        ),
        "flags": telemetry.flags,
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def compute_logical_dedupe_key(telemetry: SmsTelemetry) -> str:
    return _sha256_json(
        {
            "v": "logical-v1",
            "device_id": telemetry.device_id,
            "sequence": telemetry.sequence,
            "rtc": telemetry.rtc,
            "uptime_ms": telemetry.uptime_ms,
            "canonical_d1": canonical_logical_message(telemetry),
        }
    )


def compute_d2_content_hash(message: D2Message) -> str:
    """Hash the canonical signed D2 content, excluding AUTH text."""

    return hashlib.sha256(
        message.signed_part.encode("ascii")
    ).hexdigest()


def _inbound_from_row(row: sqlite3.Row) -> InboundSmsRecord:
    return InboundSmsRecord(
        id=row["id"],
        sender=row["sender"],
        modem_timestamp=row["modem_timestamp"],
        gateway_received_at=row["gateway_received_at"],
        raw_body=row["raw_body"],
        raw_dedupe_key=row["raw_dedupe_key"],
        logical_dedupe_key=row["logical_dedupe_key"],
        protocol_version=row["protocol_version"],
        device_id=row["device_id"],
        sequence=row["sequence"],
        message_id=row["message_id"],
        d2_content_hash=row["d2_content_hash"],
        auth_status=row["auth_status"],
        security_status=row["security_status"],
        conflict_with_sms_id=row["conflict_with_sms_id"],
        status=InboundStatus(row["status"]),
        validation_status=row["validation_status"],
        validation_warning=row["validation_warning"],
        validation_error=row["validation_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _outbox_from_row(row: sqlite3.Row) -> OutboxRecord:
    return OutboxRecord(
        id=row["id"],
        sms_id=row["sms_id"],
        topic=row["topic"],
        payload_json=row["payload_json"],
        qos=row["qos"],
        retain=bool(row["retain"]),
        status=OutboxStatus(row["status"]),
        attempt_count=row["attempt_count"],
        next_attempt_at=row["next_attempt_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        published_at=row["published_at"],
    )


class SmsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.database.initialize()

    def store_raw_sms(self, raw: RawSmsInput) -> StoreRawSmsResult:
        raw_key = compute_raw_dedupe_key(raw)
        received_at = raw.gateway_received_at or utc_now()
        now = utc_now()

        with self.database.transaction(immediate=True) as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO inbound_sms (
                        sender, modem_timestamp, gateway_received_at, raw_body,
                        raw_dedupe_key, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw.sender,
                        raw.modem_timestamp,
                        received_at,
                        raw.raw_body,
                        raw_key,
                        InboundStatus.RECEIVED.value,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM inbound_sms WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
                return StoreRawSmsResult(StoreDisposition.STORED, _inbound_from_row(row))
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM inbound_sms WHERE raw_dedupe_key = ?", (raw_key,)
                ).fetchone()
                if row is None:
                    raise
                return StoreRawSmsResult(StoreDisposition.DUPLICATE, _inbound_from_row(row))

    def mark_invalid(
        self,
        sms_id: int,
        *,
        validation_error: str,
        validation_status: str = "INVALID_FORMAT",
        validation_warning: str | None = None,
        telemetry: SmsTelemetry | None = None,
    ) -> InboundSmsRecord:
        now = utc_now()
        protocol_version = telemetry.protocol_version if telemetry else None
        device_id = telemetry.device_id if telemetry else None
        sequence = telemetry.sequence if telemetry else None
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE inbound_sms
                SET protocol_version = COALESCE(?, protocol_version),
                    device_id = COALESCE(?, device_id),
                    sequence = COALESCE(?, sequence),
                    status = ?, validation_status = ?, validation_warning = ?,
                    validation_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    protocol_version,
                    device_id,
                    sequence,
                    InboundStatus.INVALID.value,
                    validation_status,
                    validation_warning,
                    validation_error,
                    now,
                    sms_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM inbound_sms WHERE id = ?", (sms_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"inbound SMS {sms_id} not found")
            return _inbound_from_row(row)

    def queue_valid_sms(
        self,
        sms_id: int,
        telemetry: SmsTelemetry,
        validation: ValidationResult,
        *,
        topic: str,
        payload_json: str,
        qos: int = 1,
        retain: bool = False,
    ) -> QueueResult:
        logical_key = compute_logical_dedupe_key(telemetry)
        warning_text = "\n".join(validation.warnings) or None
        now = utc_now()

        with self.database.transaction(immediate=True) as connection:
            try:
                connection.execute(
                    """
                    UPDATE inbound_sms
                    SET logical_dedupe_key = ?, protocol_version = ?, device_id = ?,
                        sequence = ?, status = ?, validation_status = ?,
                        validation_warning = ?, validation_error = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        logical_key,
                        telemetry.protocol_version,
                        telemetry.device_id,
                        telemetry.sequence,
                        InboundStatus.QUEUED.value,
                        validation.status.value,
                        warning_text,
                        now,
                        sms_id,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT id FROM inbound_sms WHERE logical_dedupe_key = ?",
                    (logical_key,),
                ).fetchone()
                if existing is None:
                    raise
                duplicate_warning = f"DUPLICATE_LOGICAL:{existing['id']}"
                if warning_text:
                    duplicate_warning = f"{warning_text}\n{duplicate_warning}"
                connection.execute(
                    """
                    UPDATE inbound_sms
                    SET protocol_version = ?, device_id = ?, sequence = ?,
                        status = ?, validation_status = ?, validation_warning = ?,
                        validation_error = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        telemetry.protocol_version,
                        telemetry.device_id,
                        telemetry.sequence,
                        InboundStatus.VALIDATED.value,
                        validation.status.value,
                        duplicate_warning,
                        now,
                        sms_id,
                    ),
                )
                return QueueResult(
                    QueueDisposition.DUPLICATE_LOGICAL,
                    sms_id=sms_id,
                    outbox=None,
                    duplicate_of_sms_id=int(existing["id"]),
                )

            cursor = connection.execute(
                """
                INSERT INTO mqtt_outbox (
                    sms_id, topic, payload_json, qos, retain, status,
                    attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    sms_id,
                    topic,
                    payload_json,
                    qos,
                    int(retain),
                    OutboxStatus.PENDING.value,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM mqtt_outbox WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return QueueResult(
                QueueDisposition.QUEUED,
                sms_id=sms_id,
                outbox=_outbox_from_row(row),
            )

    def mark_d2_rejected(
        self,
        sms_id: int,
        message: D2Message,
        *,
        validation_error: str,
        security_status: str,
        auth_status: str | None = None,
    ) -> InboundSmsRecord:
        """Archive a parsed D2 security rejection without claiming message_id."""

        now = utc_now()
        message_id = derive_message_id(message)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE inbound_sms
                SET protocol_version = ?, device_id = ?, sequence = ?,
                    message_id = ?, d2_content_hash = NULL,
                    auth_status = ?, security_status = ?,
                    conflict_with_sms_id = NULL,
                    status = ?, validation_status = ?,
                    validation_warning = NULL, validation_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    message.protocol_version,
                    message.device_id,
                    message.sequence,
                    message_id,
                    auth_status,
                    security_status,
                    InboundStatus.INVALID.value,
                    "SECURITY_REJECTED",
                    validation_error,
                    now,
                    sms_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM inbound_sms WHERE id = ?",
                (sms_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"inbound SMS {sms_id} not found")
            return _inbound_from_row(row)

    def queue_d2_message(
        self,
        sms_id: int,
        message: D2Message,
        *,
        auth_status: str,
        topic: str,
        payload_json: str,
        qos: int = 1,
        retain: bool = False,
    ) -> QueueResult:
        """Atomically claim a D2 message_id and create its MQTT outbox.

        Replays with the same signed content create no second outbox.
        The same message_id with different signed content is an explicit
        conflict and is never downgraded to a normal duplicate.
        """

        message_id = derive_message_id(message)
        content_hash = compute_d2_content_hash(message)
        now = utc_now()

        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                """
                SELECT id, d2_content_hash
                FROM inbound_sms
                WHERE message_id = ?
                  AND id <> ?
                  AND d2_content_hash IS NOT NULL
                  AND security_status IS NULL
                ORDER BY id
                LIMIT 1
                """,
                (message_id, sms_id),
            ).fetchone()

            if existing is not None:
                if existing["d2_content_hash"] == content_hash:
                    connection.execute(
                        """
                        UPDATE inbound_sms
                        SET protocol_version = ?, device_id = ?,
                            sequence = ?, message_id = ?,
                            d2_content_hash = ?, auth_status = ?,
                            security_status = NULL,
                            conflict_with_sms_id = NULL,
                            status = ?, validation_status = ?,
                            validation_warning = ?,
                            validation_error = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            message.protocol_version,
                            message.device_id,
                            message.sequence,
                            message_id,
                            content_hash,
                            auth_status,
                            InboundStatus.VALIDATED.value,
                            "VALID",
                            f"DUPLICATE_MESSAGE_ID:{existing['id']}",
                            now,
                            sms_id,
                        ),
                    )
                    return QueueResult(
                        QueueDisposition.DUPLICATE_LOGICAL,
                        sms_id=sms_id,
                        outbox=None,
                        duplicate_of_sms_id=int(existing["id"]),
                    )

                connection.execute(
                    """
                    UPDATE inbound_sms
                    SET protocol_version = ?, device_id = ?,
                        sequence = ?, message_id = ?,
                        d2_content_hash = ?, auth_status = ?,
                        security_status = ?,
                        conflict_with_sms_id = ?,
                        status = ?, validation_status = ?,
                        validation_warning = NULL,
                        validation_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        message.protocol_version,
                        message.device_id,
                        message.sequence,
                        message_id,
                        content_hash,
                        auth_status,
                        "MESSAGE_ID_CONFLICT",
                        int(existing["id"]),
                        InboundStatus.INVALID.value,
                        "CONFLICT",
                        f"MESSAGE_ID_CONFLICT:{existing['id']}",
                        now,
                        sms_id,
                    ),
                )
                return QueueResult(
                    QueueDisposition.MESSAGE_ID_CONFLICT,
                    sms_id=sms_id,
                    outbox=None,
                    duplicate_of_sms_id=int(existing["id"]),
                )

            connection.execute(
                """
                UPDATE inbound_sms
                SET protocol_version = ?, device_id = ?, sequence = ?,
                    message_id = ?, d2_content_hash = ?,
                    auth_status = ?, security_status = NULL,
                    conflict_with_sms_id = NULL,
                    status = ?, validation_status = ?,
                    validation_warning = NULL,
                    validation_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    message.protocol_version,
                    message.device_id,
                    message.sequence,
                    message_id,
                    content_hash,
                    auth_status,
                    InboundStatus.QUEUED.value,
                    "VALID",
                    now,
                    sms_id,
                ),
            )

            cursor = connection.execute(
                """
                INSERT INTO mqtt_outbox (
                    sms_id, topic, payload_json, qos, retain, status,
                    attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    sms_id,
                    topic,
                    payload_json,
                    qos,
                    int(retain),
                    OutboxStatus.PENDING.value,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM mqtt_outbox WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return QueueResult(
                QueueDisposition.QUEUED,
                sms_id=sms_id,
                outbox=_outbox_from_row(row),
            )

    def get_inbound_by_message_id(
        self,
        message_id: str,
    ) -> list[InboundSmsRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM inbound_sms
                WHERE message_id = ?
                ORDER BY id
                """,
                (message_id,),
            ).fetchall()
        return [_inbound_from_row(row) for row in rows]

    def get_inbound(self, sms_id: int) -> InboundSmsRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM inbound_sms WHERE id = ?", (sms_id,)
            ).fetchone()
        return _inbound_from_row(row) if row else None

    def get_outbox(self, outbox_id: int) -> OutboxRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM mqtt_outbox WHERE id = ?", (outbox_id,)
            ).fetchone()
        return _outbox_from_row(row) if row else None

    def list_pending_outbox(
        self,
        *,
        limit: int | None = None,
        due_before: str | None = None,
    ) -> list[OutboxRecord]:
        sql = "SELECT * FROM mqtt_outbox WHERE status = ?"
        params: list[object] = [OutboxStatus.PENDING.value]
        if due_before is not None:
            sql += " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
            params.append(due_before)
        sql += " ORDER BY id"
        if limit is not None:
            if limit <= 0:
                return []
            sql += " LIMIT ?"
            params.append(limit)

        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_outbox_from_row(row) for row in rows]

    def mark_outbox_published(
        self,
        outbox_id: int,
        *,
        published_at: str | None = None,
    ) -> OutboxRecord:
        published_at = published_at or utc_now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT sms_id FROM mqtt_outbox WHERE id = ?", (outbox_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"outbox {outbox_id} not found")
            connection.execute(
                """
                UPDATE mqtt_outbox
                SET status = ?, published_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    OutboxStatus.PUBLISHED.value,
                    published_at,
                    published_at,
                    outbox_id,
                ),
            )
            connection.execute(
                "UPDATE inbound_sms SET status = ?, updated_at = ? WHERE id = ?",
                (InboundStatus.PUBLISHED.value, published_at, row["sms_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM mqtt_outbox WHERE id = ?", (outbox_id,)
            ).fetchone()
            return _outbox_from_row(updated)

    def record_publish_failure(
        self,
        outbox_id: int,
        *,
        error: str,
        next_attempt_at: str | None = None,
        terminal: bool = False,
    ) -> OutboxRecord:
        now = utc_now()
        status = OutboxStatus.FAILED if terminal else OutboxStatus.PENDING
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT sms_id FROM mqtt_outbox WHERE id = ?", (outbox_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"outbox {outbox_id} not found")
            connection.execute(
                """
                UPDATE mqtt_outbox
                SET status = ?, attempt_count = attempt_count + 1,
                    next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, next_attempt_at, error, now, outbox_id),
            )
            if terminal:
                connection.execute(
                    "UPDATE inbound_sms SET status = ?, updated_at = ? WHERE id = ?",
                    (InboundStatus.FAILED.value, now, row["sms_id"]),
                )
            updated = connection.execute(
                "SELECT * FROM mqtt_outbox WHERE id = ?", (outbox_id,)
            ).fetchone()
            return _outbox_from_row(updated)

    def count_inbound(self) -> int:
        with self.database.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM inbound_sms").fetchone()[0])

    def count_outbox(self) -> int:
        with self.database.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM mqtt_outbox").fetchone()[0])
