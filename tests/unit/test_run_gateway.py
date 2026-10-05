import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_gateway import load_env_file, load_runtime_configs


class RunGatewayConfigTests(unittest.TestCase):
    def test_env_loader_preserves_json_and_empty_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gateway.env"
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "D2_AUTH_MODE=production",
                        'D2_HMAC_KEYS_JSON={"DJUA-1":"abc#def"}',
                        "MQTT_USERNAME=",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_env_file(path)
                self.assertEqual(
                    loaded["D2_HMAC_KEYS_JSON"],
                    '{"DJUA-1":"abc#def"}',
                )
                self.assertEqual(os.environ["MQTT_USERNAME"], "")

    def test_env_loader_does_not_override_process_environment_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gateway.env"
            path.write_text("MQTT_HOST=file-host\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"MQTT_HOST": "process-host"},
                clear=True,
            ):
                load_env_file(path)
                self.assertEqual(os.environ["MQTT_HOST"], "process-host")

    def test_env_loader_rejects_malformed_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gateway.env"
            path.write_text("NOT_A_KEY_VALUE\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env_file(path)

    def test_runtime_config_rejects_mqtt_placeholder(self):
        env = {
            "SERIAL_PORT": "COM16",
            "MQTT_HOST": "CHANGE_ME",
            "D2_AUTH_MODE": "development",
            "D2_HMAC_KEYS_JSON": "{}",
            "D2_SENDER_BINDINGS_JSON": "{}",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                load_runtime_configs()

    def test_runtime_config_rejects_numeric_host_that_is_really_a_port(self):
        env = {
            "SERIAL_PORT": "COM16",
            "MQTT_HOST": "8000",
            "MQTT_PORT": "1883",
            "D2_AUTH_MODE": "development",
            "D2_HMAC_KEYS_JSON": "{}",
            "D2_SENDER_BINDINGS_JSON": "{}",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(
                ValueError,
                "looks like a port number",
            ):
                load_runtime_configs()

    def test_runtime_config_accepts_temporary_windows_test_values(self):
        env = {
            "DATABASE_PATH": "data/test.db",
            "SERIAL_PORT": "COM16",
            "SERIAL_BAUD_RATE": "9600",
            "MQTT_HOST": "broker.test.local",
            "MQTT_PORT": "1883",
            "MQTT_TOPIC_PREFIX": "djua/test",
            "D2_AUTH_MODE": "development",
            "D2_HMAC_KEYS_JSON": "{}",
            "D2_SENDER_BINDINGS_JSON": "{}",
        }
        with patch.dict(os.environ, env, clear=True):
            app, gsm, mqtt, security = load_runtime_configs()

        self.assertEqual(app.database_path, "data/test.db")
        self.assertEqual(gsm.serial_port, "COM16")
        self.assertEqual(mqtt.host, "broker.test.local")
        self.assertEqual(mqtt.normalized_topic_prefix, "djua/test")
        self.assertEqual(security.mode, "development")


class WindowsAutomationAssetsTests(unittest.TestCase):
    def test_windows_test_assets_exist(self):
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "config/gateway.env.example",
            "start_djua_gateway.bat",
            "start_djua_gateway_hidden.vbs",
            "setup_windows_test.bat",
            "stop_djua_gateway.bat",
            "disable_windows_test_autostart.bat",
            "scripts/install_windows_test_task.ps1",
        ):
            with self.subTest(path=relative):
                self.assertTrue((root / relative).is_file())

    def test_launcher_restarts_only_after_nonzero_exit(self):
        root = Path(__file__).resolve().parents[2]
        content = (
            root / "start_djua_gateway.bat"
        ).read_text(encoding="utf-8")
        self.assertIn('if "%EXIT_CODE%"=="0" exit /b 0', content)
        self.assertIn("goto restart", content)

    def test_setup_passes_root_without_trailing_backslash_quote_problem(self):
        root = Path(__file__).resolve().parents[2]
        content = (
            root / "setup_windows_test.bat"
        ).read_text(encoding="utf-8")
        self.assertIn('-Root "%~dp0."', content)
        self.assertNotIn('-Root "%~dp0"\n', content)

    def test_powershell_normalizes_root_path_before_resolve(self):
        root = Path(__file__).resolve().parents[2]
        content = (
            root / "scripts" / "install_windows_test_task.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("TrimEnd", content)
        self.assertIn("Resolve-Path -LiteralPath", content)

    def test_setup_validates_configuration_before_installing_task(self):
        root = Path(__file__).resolve().parents[2]
        content = (
            root / "setup_windows_test.bat"
        ).read_text(encoding="utf-8")
        check_pos = content.index("--check-config")
        task_pos = content.index("install_windows_test_task.ps1")
        self.assertLess(check_pos, task_pos)


if __name__ == "__main__":
    unittest.main()
