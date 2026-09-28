"""Portable serial transport for SIM800L using pyserial."""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from djua_sms_gateway.config import GsmConfig

logger = logging.getLogger(__name__)


class SerialTransportError(IOError):
    pass


class SerialTransportProtocol(Protocol):
    @property
    def is_open(self) -> bool: ...
    def open(self) -> None: ...
    def close(self) -> None: ...
    def reconnect(self) -> None: ...
    def write_line(self, line: str) -> None: ...
    def read_line(self) -> str | None: ...
    def reset_buffers(self) -> None: ...


class PySerialTransport:
    def __init__(
        self,
        config: GsmConfig,
        *,
        serial_factory: Callable[..., object] | None = None,
    ) -> None:
        self.config = config.validate()
        self._serial_factory = serial_factory
        self._serial: object | None = None

    @property
    def is_open(self) -> bool:
        return bool(self._serial is not None and getattr(self._serial, "is_open", True))

    def _factory(self) -> Callable[..., object]:
        if self._serial_factory is not None:
            return self._serial_factory
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is required for real GSM serial transport; install requirements.txt"
            ) from exc
        return serial.Serial

    def open(self) -> None:
        if self.is_open:
            return
        if not self.config.serial_port:
            raise SerialTransportError("SERIAL_PORT is empty")
        try:
            self._serial = self._factory()(
                port=self.config.serial_port,
                baudrate=self.config.baud_rate,
                timeout=self.config.serial_timeout_seconds,
                write_timeout=self.config.serial_write_timeout_seconds,
            )
            logger.info(
                "GSM_PORT_OPEN port=%s baud=%s",
                self.config.serial_port,
                self.config.baud_rate,
            )
        except Exception as exc:
            self._serial = None
            raise SerialTransportError(str(exc)) from exc

    def close(self) -> None:
        serial_obj = self._serial
        self._serial = None
        if serial_obj is not None:
            try:
                serial_obj.close()
            except Exception:
                logger.exception("GSM_PORT_CLOSE_FAILED")

    def reconnect(self) -> None:
        self.close()
        self.open()

    def _require_open(self) -> object:
        if not self.is_open or self._serial is None:
            raise SerialTransportError("serial port is not open")
        return self._serial

    def _mark_lost(self, exc: Exception) -> SerialTransportError:
        logger.warning("GSM_PORT_LOST port=%s", self.config.serial_port)
        self.close()
        return SerialTransportError(str(exc))

    def write_line(self, line: str) -> None:
        serial_obj = self._require_open()
        try:
            data = (line + "\r").encode("ascii")
            serial_obj.write(data)
            flush = getattr(serial_obj, "flush", None)
            if flush:
                flush()
        except Exception as exc:
            raise self._mark_lost(exc) from exc

    def read_line(self) -> str | None:
        serial_obj = self._require_open()
        try:
            raw = serial_obj.readline()
        except Exception as exc:
            raise self._mark_lost(exc) from exc
        if not raw:
            return None
        if isinstance(raw, str):
            return raw.rstrip("\r\n")
        return bytes(raw).decode("utf-8", errors="replace").rstrip("\r\n")

    def reset_buffers(self) -> None:
        serial_obj = self._require_open()
        try:
            reset_in = getattr(serial_obj, "reset_input_buffer", None)
            reset_out = getattr(serial_obj, "reset_output_buffer", None)
            if reset_in:
                reset_in()
            if reset_out:
                reset_out()
        except Exception as exc:
            raise self._mark_lost(exc) from exc
