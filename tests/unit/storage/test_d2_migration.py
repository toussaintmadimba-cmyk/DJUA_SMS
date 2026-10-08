import sqlite3
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.storage.database import Database, SCHEMA_VERSION
from djua_sms_gateway.storage.repository import SmsRepository


V1_SCHEMA = """
CREATE TABLE inbound_sms (
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
    status TEXT NOT NULL CHECK (
        status IN ('RECEIVED','INVALID','VALIDATED','QUEUED','PUBLISHED','FAILED')
    ),
    validation_status TEXT NULL,
    validation_warning TEXT NULL,
    validation_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE mqtt_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sms_id INTEGER NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    qos INTEGER NOT NULL CHECK(qos IN (0,1,2)),
    retain INTEGER NOT NULL CHECK(retain IN (0,1)),
    status TEXT NOT NULL CHECK(status IN ('PENDING','PUBLISHED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT NULL,
    FOREIGN KEY (sms_id) REFERENCES inbound_sms(id) ON DELETE RESTRICT
);
PRAGMA user_version = 1;
"""


class D2MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_v1_database_migrates_without_losing_d1_rows_or_outbox(self):
        connection = sqlite3.connect(self.path)
        connection.executescript(V1_SCHEMA)
        connection.execute(
            """
            INSERT INTO inbound_sms (
                sender, modem_timestamp, gateway_received_at, raw_body,
                raw_dedupe_key, protocol_version, device_id, sequence,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "+2431",
                "transport-time",
                "2026-09-27T15:00:00+00:00",
                "D1,legacy",
                "raw-key",
                "D1",
                "DJUA-KIN-000001",
                42,
                "QUEUED",
                "now",
                "now",
            ),
        )
        sms_id = connection.execute(
            "SELECT id FROM inbound_sms"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO mqtt_outbox (
                sms_id, topic, payload_json, qos, retain, status,
                attempt_count, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 0, 'PENDING', 0, 'now', 'now')
            """,
            (sms_id, "djua/test/DJUA-KIN-000001/telemetry", "{}"),
        )
        connection.commit()
        connection.close()

        Database(self.path).initialize()

        connection = sqlite3.connect(self.path)
        version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(inbound_sms)"
            )
        }
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM inbound_sms"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM mqtt_outbox"
            ).fetchone()[0],
            1,
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("http_outbox", tables)
        for column in (
            "message_id",
            "d2_content_hash",
            "auth_status",
            "security_status",
            "conflict_with_sms_id",
        ):
            self.assertIn(column, columns)
        row = connection.execute(
            "SELECT message_id, auth_status FROM inbound_sms"
        ).fetchone()
        self.assertEqual(row, (None, None))
        connection.close()

        repository = SmsRepository(Database(self.path))
        legacy = repository.get_inbound(sms_id)
        self.assertEqual(legacy.protocol_version, "D1")
        self.assertIsNone(legacy.message_id)

    def test_v2_database_migrates_to_v3_without_losing_existing_rows(self):
        connection = sqlite3.connect(self.path)
        connection.executescript(V1_SCHEMA)
        for statement in (
            "ALTER TABLE inbound_sms ADD COLUMN message_id TEXT NULL",
            "ALTER TABLE inbound_sms ADD COLUMN d2_content_hash TEXT NULL",
            "ALTER TABLE inbound_sms ADD COLUMN auth_status TEXT NULL",
            "ALTER TABLE inbound_sms ADD COLUMN security_status TEXT NULL",
            "ALTER TABLE inbound_sms ADD COLUMN conflict_with_sms_id INTEGER NULL",
        ):
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 2")
        connection.execute(
            """
            INSERT INTO inbound_sms (
                sender, gateway_received_at, raw_body, raw_dedupe_key,
                protocol_version, device_id, sequence, message_id,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "+2431",
                "2026-10-08T10:00:00+00:00",
                "D2T2,legacy-v2",
                "raw-key-v2",
                "D2T2",
                "DJUA-KIN-000001",
                50002,
                "D2:DJUA-KIN-000001:12KY",
                "QUEUED",
                "now",
                "now",
            ),
        )
        sms_id = connection.execute(
            "SELECT id FROM inbound_sms"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO mqtt_outbox (
                sms_id, topic, payload_json, qos, retain, status,
                attempt_count, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 0, 'PENDING', 0, 'now', 'now')
            """,
            (
                sms_id,
                "djua/test/DJUA-KIN-000001/telemetry",
                '{"protocol":"D2T2"}',
            ),
        )
        connection.commit()
        connection.close()

        Database(self.path).initialize()

        connection = sqlite3.connect(self.path)
        self.assertEqual(
            connection.execute("PRAGMA user_version").fetchone()[0],
            SCHEMA_VERSION,
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("http_outbox", tables)
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM inbound_sms"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM mqtt_outbox"
            ).fetchone()[0],
            1,
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
