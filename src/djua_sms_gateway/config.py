"""Environment-backed configuration for DJUA_SMS."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
import re
from urllib.parse import urlparse


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


class DeliveryMode(str, Enum):
    MQTT_ONLY = "MQTT_ONLY"
    HTTP_ONLY = "HTTP_ONLY"
    MQTT_AND_HTTP = "MQTT_AND_HTTP"

    @property
    def mqtt_enabled(self) -> bool:
        return self in {self.MQTT_ONLY, self.MQTT_AND_HTTP}

    @property
    def http_enabled(self) -> bool:
        return self in {self.HTTP_ONLY, self.MQTT_AND_HTTP}

    @classmethod
    def from_env(cls) -> "DeliveryMode":
        raw = os.getenv("DELIVERY_MODE", cls.MQTT_ONLY.value).strip().upper()
        try:
            return cls(raw)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"DELIVERY_MODE must be one of: {allowed}"
            ) from exc


@dataclass(frozen=True)
class HttpConfig:
    backend_url: str
    event_url: str | None = None
    timeout_seconds: float = 10.0
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    api_key_header: str | None = "x-device-token"
    api_key: str | None = None

    def validate(self) -> "HttpConfig":
        for name, value in (
            ("HTTP_BACKEND_URL", self.backend_url),
            ("HTTP_EVENT_URL", self.event_url or self.backend_url),
        ):
            parsed = urlparse(value.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(
                    f"{name} must be an absolute http:// or https:// URL"
                )
        if self.timeout_seconds <= 0:
            raise ValueError("HTTP_TIMEOUT_SECONDS must be > 0")
        if self.retry_base_seconds <= 0:
            raise ValueError("HTTP_RETRY_BASE_SECONDS must be > 0")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError(
                "HTTP_RETRY_MAX_SECONDS must be >= HTTP_RETRY_BASE_SECONDS"
            )
        if self.api_key and not (self.api_key_header or "").strip():
            raise ValueError(
                "HTTP_API_KEY_HEADER is required when HTTP_API_KEY is set"
            )
        return self

    @property
    def normalized_backend_url(self) -> str:
        return self.backend_url.strip()

    @property
    def normalized_event_url(self) -> str:
        return (self.event_url or self.backend_url).strip()

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {(self.api_key_header or "x-device-token").strip(): self.api_key}

    @classmethod
    def from_env(cls) -> "HttpConfig":
        return cls(
            backend_url=os.getenv("HTTP_BACKEND_URL", ""),
            event_url=os.getenv("HTTP_EVENT_URL") or None,
            timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 10.0),
            retry_base_seconds=_env_float(
                "HTTP_RETRY_BASE_SECONDS",
                2.0,
            ),
            retry_max_seconds=_env_float(
                "HTTP_RETRY_MAX_SECONDS",
                300.0,
            ),
            api_key_header=(
                os.getenv("HTTP_API_KEY_HEADER", "x-device-token") or None
            ),
            api_key=os.getenv("HTTP_API_KEY") or None,
        ).validate()


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
        if (
            self.sms_storage
            and re.fullmatch(r"[A-Za-z0-9]{1,8}", self.sms_storage)
            is None
        ):
            raise ValueError("GSM_SMS_STORAGE contains invalid characters")
        if re.fullmatch(r"\d+(?:,\d+){4}", self.cnmi) is None:
            raise ValueError(
                "GSM_CNMI must contain five comma-separated integers"
            )
        return self

    @classmethod
    def from_env(cls) -> "GsmConfig":
        config = cls(
            serial_port=os.getenv("SERIAL_PORT", ""),
            baud_rate=_env_int("SERIAL_BAUD_RATE", 9600),
            serial_timeout_seconds=_env_float(
                "SERIAL_TIMEOUT_SECONDS",
                0.5,
            ),
            serial_write_timeout_seconds=_env_float(
                "SERIAL_WRITE_TIMEOUT_SECONDS",
                2.0,
            ),
            init_retries=_env_int("GSM_INIT_RETRIES", 3),
            command_timeout_seconds=_env_float(
                "GSM_COMMAND_TIMEOUT_SECONDS",
                5.0,
            ),
            reconnect_seconds=_env_float(
                "GSM_RECONNECT_SECONDS",
                5.0,
            ),
            sms_storage=os.getenv("GSM_SMS_STORAGE") or None,
            cnmi=os.getenv("GSM_CNMI", "2,1,0,0,0"),
        )
        return config.validate()


@dataclass(frozen=True)
class D2SecurityConfig:
    mode: str = "development"
    hmac_keys: dict[str, bytes] = field(default_factory=dict)
    sender_bindings: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )

    def validate(self) -> "D2SecurityConfig":
        if self.mode not in {"development", "production"}:
            raise ValueError(
                "D2_AUTH_MODE must be development or production"
            )

        device_re = re.compile(r"^[A-Z0-9-]{1,32}$")
        e164_re = re.compile(r"^\+[1-9][0-9]{7,14}$")

        for device_id, key in self.hmac_keys.items():
            if device_re.fullmatch(device_id) is None:
                raise ValueError(
                    f"invalid D2 key device_id: {device_id!r}"
                )
            if len(key) != 32:
                raise ValueError(
                    f"D2 HMAC key for {device_id} must be 32 bytes"
                )

        for device_id, senders in self.sender_bindings.items():
            if device_re.fullmatch(device_id) is None:
                raise ValueError(
                    f"invalid D2 sender device_id: {device_id!r}"
                )
            if not senders:
                raise ValueError(
                    f"D2 sender binding for {device_id} is empty"
                )
            for sender in senders:
                if e164_re.fullmatch(sender) is None:
                    raise ValueError(
                        f"D2 sender for {device_id} must be E.164"
                    )
        return self

    def key_for(self, device_id: str) -> bytes | None:
        return self.hmac_keys.get(device_id)

    def senders_for(self, device_id: str) -> tuple[str, ...]:
        return self.sender_bindings.get(device_id, ())

    @classmethod
    def from_env(cls) -> "D2SecurityConfig":
        mode = os.getenv("D2_AUTH_MODE", "development").strip().lower()

        try:
            raw_keys = json.loads(
                os.getenv("D2_HMAC_KEYS_JSON", "{}")
            )
            raw_bindings = json.loads(
                os.getenv("D2_SENDER_BINDINGS_JSON", "{}")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "D2 security JSON environment variable is invalid"
            ) from exc

        if not isinstance(raw_keys, dict):
            raise ValueError("D2_HMAC_KEYS_JSON must be a JSON object")
        if not isinstance(raw_bindings, dict):
            raise ValueError(
                "D2_SENDER_BINDINGS_JSON must be a JSON object"
            )

        keys: dict[str, bytes] = {}
        for device_id, value in raw_keys.items():
            if not isinstance(value, str):
                raise ValueError(
                    "D2_HMAC_KEYS_JSON values must be hex strings"
                )
            try:
                keys[str(device_id)] = bytes.fromhex(value)
            except ValueError as exc:
                raise ValueError(
                    f"D2 HMAC key for {device_id} is not valid hex"
                ) from exc

        bindings: dict[str, tuple[str, ...]] = {}
        for device_id, value in raw_bindings.items():
            if isinstance(value, str):
                senders = (value,)
            elif (
                isinstance(value, list)
                and all(isinstance(item, str) for item in value)
            ):
                senders = tuple(value)
            else:
                raise ValueError(
                    "D2_SENDER_BINDINGS_JSON values must be strings "
                    "or arrays of strings"
                )
            bindings[str(device_id)] = senders

        return cls(
            mode=mode,
            hmac_keys=keys,
            sender_bindings=bindings,
        ).validate()


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
            raise ValueError(
                "MQTT_CLIENT_ID must be a gateway ID, not an ESP32 device client ID"
            )
        if any(ch.isspace() for ch in client_id):
            raise ValueError(
                "MQTT_CLIENT_ID must not contain whitespace"
            )
        if not prefix or "+" in prefix or "#" in prefix:
            raise ValueError(
                "MQTT_TOPIC_PREFIX must be non-empty and contain no MQTT wildcards"
            )
        if self.qos not in (0, 1, 2):
            raise ValueError("MQTT_QOS must be 0, 1 or 2")
        if self.keepalive_seconds <= 0:
            raise ValueError("MQTT_KEEPALIVE_SECONDS must be > 0")
        if self.connect_timeout_seconds <= 0:
            raise ValueError(
                "MQTT_CONNECT_TIMEOUT_SECONDS must be > 0"
            )
        if self.publish_timeout_seconds <= 0:
            raise ValueError(
                "MQTT_PUBLISH_TIMEOUT_SECONDS must be > 0"
            )
        if self.retry_base_seconds <= 0:
            raise ValueError("MQTT_RETRY_BASE_SECONDS must be > 0")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError(
                "MQTT_RETRY_MAX_SECONDS must be >= MQTT_RETRY_BASE_SECONDS"
            )
        if self.password and not self.username:
            raise ValueError(
                "MQTT_USERNAME is required when MQTT_PASSWORD is set"
            )
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
            client_id=os.getenv(
                "MQTT_CLIENT_ID",
                "djua-sms-gateway-001",
            ),
            username=username,
            password=password,
            topic_prefix=os.getenv(
                "MQTT_TOPIC_PREFIX",
                "djua/test",
            ),
            qos=_env_int("MQTT_QOS", 1),
            retain=_env_bool("MQTT_RETAIN", False),
            keepalive_seconds=_env_int(
                "MQTT_KEEPALIVE_SECONDS",
                60,
            ),
            connect_timeout_seconds=_env_float(
                "MQTT_CONNECT_TIMEOUT_SECONDS",
                10.0,
            ),
            publish_timeout_seconds=_env_float(
                "MQTT_PUBLISH_TIMEOUT_SECONDS",
                10.0,
            ),
            retry_base_seconds=_env_float(
                "MQTT_RETRY_BASE_SECONDS",
                2.0,
            ),
            retry_max_seconds=_env_float(
                "MQTT_RETRY_MAX_SECONDS",
                300.0,
            ),
            tls=_env_bool("MQTT_TLS", False),
        )
        return config.validate()


@dataclass(frozen=True)
class AppConfig:
    database_path: str = "data/djua_sms_gateway.db"
    delivery_mode: DeliveryMode = DeliveryMode.MQTT_ONLY
    http: HttpConfig | None = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        mode = DeliveryMode.from_env()
        http = HttpConfig.from_env() if mode.http_enabled else None
        return cls(
            database_path=os.getenv(
                "DATABASE_PATH",
                "data/djua_sms_gateway.db",
            ),
            delivery_mode=mode,
            http=http,
        )
