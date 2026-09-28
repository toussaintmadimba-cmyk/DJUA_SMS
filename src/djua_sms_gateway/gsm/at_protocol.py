"""Synchronous AT command protocol with a small unsolicited-result queue."""

from __future__ import annotations

from collections import deque
import time

from .models import AtResponse
from .serial_transport import SerialTransportProtocol


_ERROR_PREFIXES = ("+CME ERROR", "+CMS ERROR")
_ALWAYS_URC_PREFIXES = ("+CMTI:", "+CDS:", "+CUSD:", "+CGEV:")
_ALWAYS_URC_LINES = {
    "RDY",
    "Call Ready",
    "SMS Ready",
    "NORMAL POWER DOWN",
}


class AtProtocol:
    def __init__(
        self,
        transport: SerialTransportProtocol,
        *,
        command_timeout_seconds: float = 5.0,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be > 0")
        self.transport = transport
        self.command_timeout_seconds = command_timeout_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._urcs: deque[str] = deque()

    def _is_urc(self, line: str, command: str) -> bool:
        if line in _ALWAYS_URC_LINES or line.startswith(_ALWAYS_URC_PREFIXES):
            return True
        if line.startswith("+CREG:") and command != "AT+CREG?":
            return True
        if line.startswith("+CGREG:") and command != "AT+CGREG?":
            return True
        return False

    def execute(self, command: str, *, timeout_seconds: float | None = None) -> AtResponse:
        timeout = self.command_timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self.transport.write_line(command)
        deadline = self._monotonic() + timeout
        lines: list[str] = []

        while self._monotonic() < deadline:
            line = self.transport.read_line()
            if line is None:
                self._sleep(min(0.01, max(0.0, deadline - self._monotonic())))
                continue

            line = line.strip("\r\n")
            if not line:
                continue
            if line == command:
                continue
            if self._is_urc(line, command):
                self._urcs.append(line)
                continue
            if line == "OK":
                return AtResponse(command=command, lines=tuple(lines), ok=True)
            if line == "ERROR" or line.startswith(_ERROR_PREFIXES):
                return AtResponse(
                    command=command,
                    lines=tuple(lines),
                    ok=False,
                    error=line,
                )
            lines.append(line)

        return AtResponse(
            command=command,
            lines=tuple(lines),
            ok=False,
            error="TIMEOUT",
            timed_out=True,
        )

    def pop_urc(self) -> str | None:
        return self._urcs.popleft() if self._urcs else None

    def drain_urcs(self) -> tuple[str, ...]:
        items = tuple(self._urcs)
        self._urcs.clear()
        return items

    def poll_urc(self, *, timeout_seconds: float = 0.0) -> str | None:
        queued = self.pop_urc()
        if queued is not None:
            return queued

        deadline = self._monotonic() + max(0.0, timeout_seconds)
        first = True
        while first or self._monotonic() < deadline:
            first = False
            line = self.transport.read_line()
            if line is not None:
                stripped = line.strip("\r\n")
                if stripped:
                    return stripped
            if timeout_seconds <= 0:
                break
            self._sleep(min(0.01, max(0.0, deadline - self._monotonic())))
        return None
