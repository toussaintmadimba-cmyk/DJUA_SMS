"""Thin MQTT client boundary around paho-mqtt.

Paho is imported lazily so unit tests can inject a fake client without network
or an installed broker dependency. Production use requires paho-mqtt==2.1.0.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Callable, Protocol

from djua_sms_gateway.config import MqttConfig

logger = logging.getLogger(__name__)


class MqttError(RuntimeError):
    pass


class MqttConnectionError(MqttError):
    pass


class MqttPublishError(MqttError):
    pass


@dataclass(frozen=True)
class PublishReceipt:
    mid: int


class MqttClientProtocol(Protocol):
    @property
    def connected(self) -> bool: ...
    def set_publish_ack_handler(self, handler: Callable[[int], None]) -> None: ...
    def set_disconnect_handler(self, handler: Callable[[], None]) -> None: ...
    def connect(self) -> None: ...
    def reconnect(self) -> None: ...
    def disconnect(self) -> None: ...
    def publish(self, topic: str, payload: str, *, qos: int, retain: bool) -> PublishReceipt: ...


def _reason_is_failure(reason_code: object) -> bool:
    if hasattr(reason_code, "is_failure"):
        return bool(getattr(reason_code, "is_failure"))
    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        return bool(reason_code)


class PahoMqttClient:
    def __init__(self, config: MqttConfig, *, client: object | None = None) -> None:
        self.config = config.validate()
        self._connected = False
        self._loop_started = False
        self._connect_event = threading.Event()
        self._connect_error: str | None = None
        self._ack_handler: Callable[[int], None] | None = None
        self._disconnect_handler: Callable[[], None] | None = None

        if client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError as exc:
                raise RuntimeError(
                    "paho-mqtt is required for real MQTT transport; install requirements.txt"
                ) from exc
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.config.client_id,
                protocol=mqtt.MQTTv311,
                reconnect_on_failure=True,
            )
        self._client = client
        self._configure_client()

    def _configure_client(self) -> None:
        if self.config.username:
            self._client.username_pw_set(self.config.username, self.config.password)
        if self.config.tls:
            self._client.tls_set()
        if hasattr(self._client, "reconnect_delay_set"):
            self._client.reconnect_delay_set(
                min_delay=max(1, int(self.config.retry_base_seconds)),
                max_delay=max(1, int(self.config.retry_max_seconds)),
            )
        self._client.on_connect = self._on_connect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish

    @property
    def connected(self) -> bool:
        return self._connected

    def set_publish_ack_handler(self, handler: Callable[[int], None]) -> None:
        self._ack_handler = handler

    def set_disconnect_handler(self, handler: Callable[[], None]) -> None:
        self._disconnect_handler = handler

    def connect(self) -> None:
        if self._connected:
            return
        logger.info(
            "MQTT_CONNECTING client_id=%s host=%s port=%s",
            self.config.client_id,
            self.config.host,
            self.config.port,
        )
        self._connect_event.clear()
        self._connect_error = None
        try:
            if not self._loop_started:
                rc = self._client.connect_async(
                    self.config.host,
                    self.config.port,
                    self.config.keepalive_seconds,
                )
                if rc not in (None, 0):
                    raise MqttConnectionError(f"connect_async rc={rc}")
                self._client.loop_start()
                self._loop_started = True
            else:
                rc = self._client.reconnect()
                if rc not in (None, 0):
                    raise MqttConnectionError(f"reconnect rc={rc}")
        except Exception as exc:
            if isinstance(exc, MqttConnectionError):
                raise
            raise MqttConnectionError(str(exc)) from exc

        if not self._connect_event.wait(self.config.connect_timeout_seconds):
            raise MqttConnectionError("MQTT connection timeout")
        if not self._connected:
            raise MqttConnectionError(self._connect_error or "MQTT connection refused")

    def reconnect(self) -> None:
        self.connect()

    def disconnect(self) -> None:
        try:
            if self._loop_started:
                self._client.disconnect()
        finally:
            if self._loop_started:
                self._client.loop_stop()
                self._loop_started = False
            self._connected = False
            logger.info("MQTT_DISCONNECTED intentional=true")

    def publish(self, topic: str, payload: str, *, qos: int, retain: bool) -> PublishReceipt:
        if not self._connected:
            raise MqttPublishError("MQTT client is not connected")
        info = self._client.publish(topic, payload=payload, qos=qos, retain=retain)
        rc = getattr(info, "rc", 0)
        if rc != 0:
            raise MqttPublishError(f"publish rc={rc}")
        mid = int(getattr(info, "mid"))
        return PublishReceipt(mid=mid)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if _reason_is_failure(reason_code):
            self._connected = False
            self._connect_error = f"broker rejected connection: {reason_code}"
        else:
            self._connected = True
            self._connect_error = None
            logger.info("MQTT_CONNECTED client_id=%s", self.config.client_id)
        self._connect_event.set()

    def _on_connect_fail(self, client, userdata) -> None:
        self._connected = False
        self._connect_error = "TCP/DNS connection failed"
        self._connect_event.set()

    def _on_disconnect(self, client, userdata, *args) -> None:
        self._connected = False
        logger.warning("MQTT_DISCONNECTED intentional=false")
        if self._disconnect_handler:
            self._disconnect_handler()

    def _on_publish(self, client, userdata, mid, *args) -> None:
        if self._ack_handler:
            self._ack_handler(int(mid))
