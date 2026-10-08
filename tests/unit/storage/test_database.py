import sqlite3
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.storage.database import Database, SCHEMA_VERSION


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"
        self.db = Database(self.path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_initialize_creates_schema_and_version(self) -> None:
        self.db.initialize()
        with self.db.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIn("inbound_sms", names)
        self.assertIn("mqtt_outbox", names)
        self.assertIn("http_outbox", names)

    def test_initialize_is_idempotent_on_existing_database(self) -> None:
        self.db.initialize()
        Database(self.path).initialize()
        with self.db.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)

    def test_transaction_commits(self) -> None:
        self.db.initialize()
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO inbound_sms (
                    sender, gateway_received_at, raw_body, raw_dedupe_key,
                    status, created_at, updated_at
                ) VALUES ('+243000', 'now', 'body', 'key1', 'RECEIVED', 'now', 'now')
                """
            )
        with self.db.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM inbound_sms").fetchone()[0]
        self.assertEqual(count, 1)

    def test_transaction_rolls_back_on_exception(self) -> None:
        self.db.initialize()
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO inbound_sms (
                        sender, gateway_received_at, raw_body, raw_dedupe_key,
                        status, created_at, updated_at
                    ) VALUES ('+243000', 'now', 'body', 'key1', 'RECEIVED', 'now', 'now')
                    """
                )
                raise RuntimeError("boom")
        with self.db.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM inbound_sms").fetchone()[0]
        self.assertEqual(count, 0)

    def test_foreign_keys_are_enforced(self) -> None:
        self.db.initialize()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO mqtt_outbox (
                        sms_id, topic, payload_json, qos, retain, status,
                        attempt_count, created_at, updated_at
                    ) VALUES (999, 'x', '{}', 1, 0, 'PENDING', 0, 'now', 'now')
                    """
                )

    def test_newer_schema_is_rejected(self) -> None:
        self.db.initialize()
        with self.db.connect() as connection:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        with self.assertRaises(RuntimeError):
            self.db.initialize()


if __name__ == "__main__":
    unittest.main()
