"""Environment-backed configuration for DJUA_SMS."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or not raw.strip() else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or not raw.strip() else float(raw)


@dataclass(frozen=True)
class GsmConfig:
    serial_port: str
    baud_rate: int = 9600
    serial_timeout_seconds: float = 0.5
    serial_write_timeout_seconds: float = 2.0
    init_retries: int = 3
    command_timeout_seconds: float = 5.0
    reconnect_seconds: float = 5.0
    sms_storage: str | None = None
    cnmi: str = "2,1,0,0,0"

    def validate(self) -> "GsmConfig":
        if not self.serial_port.strip():
            raise ValueError("SERIAL_PORT must not be empty")
        if self.baud_rate <= 0:
            raise ValueError("SERIAL_BAUD_RATE must be > 0")
        if self.serial_timeout_seconds <= 0:
            raise ValueError("SERIAL_TIMEOUT_SECONDS must be > 0")
        if self.serial_write_timeout_seconds <= 0:
            raise ValueError("SERIAL_WRITE_TIMEOUT_SECONDS must be > 0")
        if self.init_retries <= 0:
            raise ValueError("GSM_INIT_RETRIES must be > 0")
        if self.command_timeout_seconds <= 0:
            raise ValueError("GSM_COMMAND_TIMEOUT_SECONDS must be > 0")
        if self.reconnect_seconds <= 0:
            raise ValueError("GSM_RECONNECT_SECONDS must be > 0")
        if self.sms_storage and re.fullmatch(r"[A-Za-z0-9]{1,8}", self.sms_storage) is None:
            raise ValueError("GSM_SMS_STORAGE contains invalid characters")
        if re.fullmatch(r"\d+(?:,\d+){4}", self.cnmi) is None:
            raise ValueError("GSM_CNMI must contain five comma-separated integers")
        return self

    @classmethod
    def from_env(cls) -> "GsmConfig":
        config = cls(
            serial_port=os.getenv("SERIAL_PORT", ""),
            baud_rate=_env_int("SERIAL_BAUD_RATE", 9600),
            serial_timeout_seconds=_env_float("SERIAL_TIMEOUT_SECONDS", 0.5),
            serial_write_timeout_seconds=_env_float("SERIAL_WRITE_TIMEOUT_SECONDS", 2.0),
            init_retries=_env_int("GSM_INIT_RETRIES", 3),
            command_timeout_seconds=_env_float("GSM_COMMAND_TIMEOUT_SECONDS", 5.0),
            reconnect_seconds=_env_float("GSM_RECONNECT_SECONDS", 5.0),
            sms_storage=os.getenv("GSM_SMS_STORAGE") or None,
            cnmi=os.getenv("GSM_CNMI", "2,1,0,0,0"),
        )
        return config.validate()


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int = 1883
    client_id: str = "djua-sms-gateway-001"
    username: str | None = None
    password: str | None = None
    topic_prefix: str = "djua/test"
    qos: int = 1
    retain: bool = False
    keepalive_seconds: int = 60
    connect_timeout_seconds: float = 10.0
    publish_timeout_seconds: float = 10.0
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    tls: bool = False

    def validate(self) -> "MqttConfig":
        host = self.host.strip()
        client_id = self.client_id.strip()
        prefix = self.topic_prefix.strip().strip("/")
        if not host:
            raise ValueError("MQTT_HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("MQTT_PORT must be between 1 and 65535")
        if not client_id:
            raise ValueError("MQTT_CLIENT_ID must not be empty")
        if client_id.startswith("djua-DJUA-"):
            raise ValueError("MQTT_CLIENT_ID must be a gateway ID, not an ESP32 device client ID")
        if any(ch.isspace() for ch in client_id):
            raise ValueError("MQTT_CLIENT_ID must not contain whitespace")
        if not prefix or "+" in prefix or "#" in prefix:
            raise ValueError("MQTT_TOPIC_PREFIX must be non-empty and contain no MQTT wildcards")
        if self.qos not in (0, 1, 2):
            raise ValueError("MQTT_QOS must be 0, 1 or 2")
        if self.keepalive_seconds <= 0:
            raise ValueError("MQTT_KEEPALIVE_SECONDS must be > 0")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("MQTT_CONNECT_TIMEOUT_SECONDS must be > 0")
        if self.publish_timeout_seconds <= 0:
            raise ValueError("MQTT_PUBLISH_TIMEOUT_SECONDS must be > 0")
        if self.retry_base_seconds <= 0:
            raise ValueError("MQTT_RETRY_BASE_SECONDS must be > 0")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("MQTT_RETRY_MAX_SECONDS must be >= MQTT_RETRY_BASE_SECONDS")
        if self.password and not self.username:
            raise ValueError("MQTT_USERNAME is required when MQTT_PASSWORD is set")
        return self

    @property
    def normalized_topic_prefix(self) -> str:
        return self.topic_prefix.strip().strip("/")

    @classmethod
    def from_env(cls) -> "MqttConfig":
        username = os.getenv("MQTT_USERNAME") or None
        password = os.getenv("MQTT_PASSWORD") or None
        config = cls(
            host=os.getenv("MQTT_HOST", ""),
            port=_env_int("MQTT_PORT", 1883),
            client_id=os.getenv("MQTT_CLIENT_ID", "djua-sms-gateway-001"),
            username=username,
            password=password,
            topic_prefix=os.getenv("MQTT_TOPIC_PREFIX", "djua/test"),
            qos=_env_int("MQTT_QOS", 1),
            retain=_env_bool("MQTT_RETAIN", False),
            keepalive_seconds=_env_int("MQTT_KEEPALIVE_SECONDS", 60),
            connect_timeout_seconds=_env_float("MQTT_CONNECT_TIMEOUT_SECONDS", 10.0),
            publish_timeout_seconds=_env_float("MQTT_PUBLISH_TIMEOUT_SECONDS", 10.0),
            retry_base_seconds=_env_float("MQTT_RETRY_BASE_SECONDS", 2.0),
            retry_max_seconds=_env_float("MQTT_RETRY_MAX_SECONDS", 300.0),
            tls=_env_bool("MQTT_TLS", False),
        )
        return config.validate()


@dataclass(frozen=True)
class AppConfig:
    database_path: str = "data/djua_sms_gateway.db"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(database_path=os.getenv("DATABASE_PATH", "data/djua_sms_gateway.db"))
