#!/usr/bin/env python3
"""Production-style launcher for the temporary Windows DJUA_SMS test gateway."""

from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import threading
import time

from djua_sms_gateway.config import (
    AppConfig,
    D2SecurityConfig,
    GsmConfig,
    MqttConfig,
)
from djua_sms_gateway.gsm.at_protocol import AtProtocol
from djua_sms_gateway.gsm.modem import Sim800Modem
from djua_sms_gateway.gsm.serial_transport import PySerialTransport
from djua_sms_gateway.gsm.sms_receiver import SmsReceiver
from djua_sms_gateway.mqtt.client import PahoMqttClient
from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.gateway import DjuaSmsGateway
from djua_sms_gateway.services.ingestion import (
    IngestionConfig,
    SmsIngestionService,
)
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "gateway.env"
DEFAULT_LOG = ROOT / "logs" / "gateway.log"
DEFAULT_STOP_FILE = ROOT / "data" / "gateway.stop"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: str | Path, *, override: bool = False) -> dict[str, str]:
    """Load a small KEY=VALUE file without requiring python-dotenv."""

    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f"gateway config not found: {env_path}")

    loaded: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(
                f"{env_path}:{line_number}: expected KEY=VALUE"
            )

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()

        if _ENV_NAME_RE.fullmatch(name) is None:
            raise ValueError(
                f"{env_path}:{line_number}: invalid variable name {name!r}"
            )

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]

        loaded[name] = value
        if override or name not in os.environ:
            os.environ[name] = value

    return loaded


def _resolve_runtime_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def configure_logging() -> Path:
    log_path = _resolve_runtime_path(
        os.getenv("GATEWAY_LOG_PATH"),
        DEFAULT_LOG,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("GATEWAY_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ValueError(
            "GATEWAY_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL"
        )

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)

    return log_path


def load_runtime_configs():
    app = AppConfig.from_env()
    gsm = GsmConfig.from_env()
    mqtt = MqttConfig.from_env()
    security = D2SecurityConfig.from_env()

    if mqtt.host.strip().upper() in {
        "CHANGE_ME",
        "TODO",
        "BROKER_A_CONFIGURER",
    }:
        raise ValueError(
            "MQTT_HOST still contains a placeholder; edit config/gateway.env"
        )

    return app, gsm, mqtt, security


def build_gateway(
    app: AppConfig,
    gsm: GsmConfig,
    mqtt: MqttConfig,
    security: D2SecurityConfig,
) -> DjuaSmsGateway:
    database_path = Path(app.database_path)
    if not database_path.is_absolute():
        database_path = ROOT / database_path

    repository = SmsRepository(Database(database_path))

    serial_transport = PySerialTransport(gsm)
    at = AtProtocol(
        serial_transport,
        command_timeout_seconds=gsm.command_timeout_seconds,
    )
    modem = Sim800Modem(
        at,
        init_retries=gsm.init_retries,
        command_timeout_seconds=gsm.command_timeout_seconds,
        sms_storage=gsm.sms_storage,
        cnmi=gsm.cnmi,
    )

    ingestion = SmsIngestionService(
        repository,
        IngestionConfig(
            mqtt_topic_prefix=mqtt.normalized_topic_prefix,
            mqtt_qos=mqtt.qos,
            mqtt_retain=mqtt.retain,
        ),
        d2_security=security,
    )
    receiver = SmsReceiver(modem, ingestion)

    mqtt_client = PahoMqttClient(mqtt)
    publisher = MqttPublisher(
        mqtt_client,
        repository,
        publish_timeout_seconds=mqtt.publish_timeout_seconds,
        retry_base_seconds=mqtt.retry_base_seconds,
        retry_max_seconds=mqtt.retry_max_seconds,
    )
    worker = MqttOutboxWorker(repository, mqtt_client, publisher)

    return DjuaSmsGateway(
        modem,
        receiver,
        worker,
        reconnect_seconds=gsm.reconnect_seconds,
    )


def _start_stop_file_watcher(
    gateway: DjuaSmsGateway,
    stop_file: Path,
) -> threading.Thread:
    def watch() -> None:
        while True:
            if stop_file.exists():
                logging.getLogger(__name__).info(
                    "GATEWAY_STOP_FILE_DETECTED path=%s",
                    stop_file,
                )
                gateway.stop()
                return
            time.sleep(0.5)

    thread = threading.Thread(
        target=watch,
        name="djua-stop-file-watcher",
        daemon=True,
    )
    thread.start()
    return thread


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the DJUA SMS gateway continuously."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the persistent KEY=VALUE gateway configuration.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration without opening SIM868 or MQTT.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    os.chdir(ROOT)

    try:
        load_env_file(args.config)
        log_path = configure_logging()
        app, gsm, mqtt, security = load_runtime_configs()
    except Exception as exc:
        print(f"CONFIG_ERROR: {exc}")
        return 2

    if args.check_config:
        print("CONFIG_OK")
        print(f"SERIAL_PORT={gsm.serial_port}")
        print(f"MQTT_HOST={mqtt.host}")
        print(f"MQTT_TOPIC_PREFIX={mqtt.normalized_topic_prefix}")
        print(f"D2_AUTH_MODE={security.mode}")
        print(f"DATABASE_PATH={app.database_path}")
        print(f"LOG_PATH={log_path}")
        return 0

    logger = logging.getLogger(__name__)
    stop_file = _resolve_runtime_path(
        os.getenv("GATEWAY_STOP_FILE"),
        DEFAULT_STOP_FILE,
    )
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    if stop_file.exists():
        stop_file.unlink()

    gateway: DjuaSmsGateway | None = None
    try:
        gateway = build_gateway(app, gsm, mqtt, security)
        _start_stop_file_watcher(gateway, stop_file)

        logger.info(
            "GATEWAY_PROCESS_START serial_port=%s mqtt_host=%s d2_mode=%s",
            gsm.serial_port,
            mqtt.host,
            security.mode,
        )
        gateway.run_forever()
        logger.info("GATEWAY_PROCESS_STOP_REQUESTED")
        return 0
    except KeyboardInterrupt:
        logger.info("GATEWAY_KEYBOARD_INTERRUPT")
        return 0
    except Exception:
        logger.exception("GATEWAY_FATAL")
        return 1
    finally:
        if gateway is not None:
            try:
                gateway.shutdown()
            except Exception:
                logger.exception("GATEWAY_SHUTDOWN_FAILED")
        if stop_file.exists():
            try:
                stop_file.unlink()
            except OSError:
                logger.warning(
                    "GATEWAY_STOP_FILE_CLEANUP_FAILED path=%s",
                    stop_file,
                )


if __name__ == "__main__":
    raise SystemExit(main())
