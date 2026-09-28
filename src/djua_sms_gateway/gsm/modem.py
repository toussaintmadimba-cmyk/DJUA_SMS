"""SIM800L modem operations above the generic AT protocol."""

from __future__ import annotations

import csv
import io
import logging
import re
import time

from .at_protocol import AtProtocol
from .models import (
    CmtiNotification,
    ModemInitializationReport,
    ModemSms,
    NetworkRegistration,
    SignalQuality,
    SimStatus,
    SmsStorage,
)

logger = logging.getLogger(__name__)

_CMTI_RE = re.compile(r'^\+CMTI:\s*"([^"]+)"\s*,\s*(\d+)\s*$')
_CREG_RE = re.compile(r"^\+CREG:\s*(?:\d+\s*,\s*)?(\d+)(?:\s*,.*)?$")
_CSQ_RE = re.compile(r"^\+CSQ:\s*(\d+)\s*,\s*(\d+)\s*$")
_STORAGE_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


class ModemError(RuntimeError):
    pass


class ModemCommandError(ModemError):
    pass


class ModemInitializationError(ModemError):
    pass


def _csv_fields(text: str) -> list[str]:
    return next(csv.reader(io.StringIO(text), skipinitialspace=True))


def parse_cmti(line: str) -> CmtiNotification:
    match = _CMTI_RE.fullmatch(line.strip())
    if match is None:
        raise ValueError("malformed +CMTI notification")
    return CmtiNotification(storage=match.group(1), index=int(match.group(2)))


def parse_sim_status(lines: tuple[str, ...]) -> SimStatus:
    for line in lines:
        if line.startswith("+CPIN:"):
            value = line.split(":", 1)[1].strip()
            if value == "READY":
                return SimStatus.READY
            if value == "SIM PIN":
                return SimStatus.PIN_REQUIRED
            if value == "SIM PUK":
                return SimStatus.PUK_REQUIRED
            return SimStatus.UNKNOWN
    return SimStatus.UNKNOWN


def parse_network_registration(lines: tuple[str, ...]) -> NetworkRegistration:
    for line in lines:
        match = _CREG_RE.fullmatch(line)
        if match:
            stat = int(match.group(1))
            return {
                0: NetworkRegistration.NOT_REGISTERED,
                1: NetworkRegistration.HOME,
                2: NetworkRegistration.SEARCHING,
                3: NetworkRegistration.DENIED,
                4: NetworkRegistration.UNKNOWN,
                5: NetworkRegistration.ROAMING,
            }.get(stat, NetworkRegistration.UNKNOWN)
    return NetworkRegistration.UNKNOWN


def parse_signal_quality(lines: tuple[str, ...]) -> SignalQuality | None:
    for line in lines:
        match = _CSQ_RE.fullmatch(line)
        if match:
            return SignalQuality(rssi=int(match.group(1)), ber=int(match.group(2)))
    return None


def parse_storage(lines: tuple[str, ...], known_name: str | None = None) -> SmsStorage | None:
    for line in lines:
        if not line.startswith("+CPMS:"):
            continue
        fields = _csv_fields(line.split(":", 1)[1].strip())
        if not fields:
            return None
        if fields[0] and not fields[0].isdigit():
            if len(fields) < 3:
                return None
            return SmsStorage(fields[0], int(fields[1]), int(fields[2]))
        if known_name is not None and len(fields) >= 2:
            return SmsStorage(known_name, int(fields[0]), int(fields[1]))
    return None


def _parse_cmgr_header(line: str) -> tuple[str, str, str | None]:
    if not line.startswith("+CMGR:"):
        raise ValueError("missing +CMGR header")
    fields = _csv_fields(line.split(":", 1)[1].strip())
    if len(fields) < 2:
        raise ValueError("malformed +CMGR header")
    status = fields[0].strip()
    sender = fields[1].strip()
    timestamp = fields[3].strip() if len(fields) >= 4 and fields[3].strip() else None
    return status, sender, timestamp


def _parse_cmgl_header(line: str) -> tuple[int, str, str, str | None]:
    if not line.startswith("+CMGL:"):
        raise ValueError("missing +CMGL header")
    fields = _csv_fields(line.split(":", 1)[1].strip())
    if len(fields) < 3:
        raise ValueError("malformed +CMGL header")
    index = int(fields[0])
    status = fields[1].strip()
    sender = fields[2].strip()
    timestamp = fields[4].strip() if len(fields) >= 5 and fields[4].strip() else None
    return index, status, sender, timestamp


class Sim800Modem:
    def __init__(
        self,
        at: AtProtocol,
        *,
        init_retries: int = 3,
        command_timeout_seconds: float = 5.0,
        sms_storage: str | None = None,
        cnmi: str = "2,1,0,0,0",
        sleep=time.sleep,
    ) -> None:
        if init_retries <= 0:
            raise ValueError("init_retries must be > 0")
        self.at = at
        self.init_retries = init_retries
        self.command_timeout_seconds = command_timeout_seconds
        self.sms_storage = sms_storage or None
        self.cnmi = cnmi
        self._sleep = sleep
        self._selected_storage: str | None = None

    def open(self) -> None:
        self.at.transport.open()

    def close(self) -> None:
        self.at.transport.close()

    def reconnect(self) -> ModemInitializationReport:
        self.at.transport.reconnect()
        return self.initialize()

    def _required(self, command: str):
        response = self.at.execute(command, timeout_seconds=self.command_timeout_seconds)
        if not response.ok:
            raise ModemCommandError(f"{command}: {response.error}")
        return response

    def initialize(self) -> ModemInitializationReport:
        if not self.at.transport.is_open:
            self.open()

        detected = False
        for attempt in range(self.init_retries):
            response = self.at.execute("AT", timeout_seconds=self.command_timeout_seconds)
            if response.ok:
                detected = True
                break
            if attempt + 1 < self.init_retries:
                self._sleep(0.2)
        if not detected:
            raise ModemInitializationError("SIM800L did not answer AT")
        logger.info("MODEM_DETECTED")

        self._required("AT+CMEE=2")

        cpin = self.at.execute("AT+CPIN?", timeout_seconds=self.command_timeout_seconds)
        sim_status = parse_sim_status(cpin.lines) if cpin.ok else SimStatus.UNKNOWN
        if sim_status is SimStatus.READY:
            logger.info("SIM_READY")
        elif sim_status in {SimStatus.PIN_REQUIRED, SimStatus.PUK_REQUIRED}:
            logger.warning("SIM_LOCKED state=%s", sim_status.value)

        creg = self.at.execute("AT+CREG?", timeout_seconds=self.command_timeout_seconds)
        registration = (
            parse_network_registration(creg.lines)
            if creg.ok
            else NetworkRegistration.UNKNOWN
        )
        if registration.registered:
            logger.info("NETWORK_REGISTERED state=%s", registration.value)
        else:
            logger.warning("NETWORK_NOT_REGISTERED state=%s", registration.value)

        csq = self.at.execute("AT+CSQ", timeout_seconds=self.command_timeout_seconds)
        signal = parse_signal_quality(csq.lines) if csq.ok else None
        if signal is not None:
            logger.info("GSM_SIGNAL rssi=%s ber=%s", signal.rssi, signal.ber)

        cmgf = self.at.execute("AT+CMGF=1", timeout_seconds=self.command_timeout_seconds)
        sms_text_mode = cmgf.ok

        if self.sms_storage:
            self.select_storage(self.sms_storage)
        storage = self.get_storage_status()

        cnmi_configured = self.configure_cnmi(self.cnmi)
        return ModemInitializationReport(
            modem_present=True,
            sim_status=sim_status,
            network_registration=registration,
            signal=signal,
            sms_text_mode=sms_text_mode,
            storage=storage,
            cnmi_configured=cnmi_configured,
        )

    def select_storage(self, storage: str) -> SmsStorage | None:
        if _STORAGE_RE.fullmatch(storage) is None:
            raise ValueError("invalid SMS storage name")
        response = self._required(f'AT+CPMS="{storage}"')
        self._selected_storage = storage
        parsed = parse_storage(response.lines, known_name=storage)
        if parsed:
            logger.info(
                "SMS_STORAGE name=%s used=%s total=%s",
                parsed.name,
                parsed.used,
                parsed.total,
            )
        return parsed

    def get_storage_status(self) -> SmsStorage | None:
        response = self.at.execute("AT+CPMS?", timeout_seconds=self.command_timeout_seconds)
        if not response.ok:
            return None
        storage = parse_storage(response.lines, known_name=self._selected_storage)
        if storage:
            self._selected_storage = storage.name
            logger.info(
                "SMS_STORAGE name=%s used=%s total=%s",
                storage.name,
                storage.used,
                storage.total,
            )
        return storage

    def configure_cnmi(self, value: str | None = None) -> bool:
        cnmi = value or self.cnmi
        if re.fullmatch(r"\d+(?:,\d+){4}", cnmi) is None:
            raise ValueError("CNMI must contain five comma-separated integers")
        response = self.at.execute(
            f"AT+CNMI={cnmi}",
            timeout_seconds=self.command_timeout_seconds,
        )
        return response.ok

    def _ensure_storage(self, storage: str) -> None:
        if self._selected_storage != storage:
            self.select_storage(storage)

    def read_sms(self, storage: str, index: int) -> ModemSms:
        if index < 0:
            raise ValueError("SMS index must be >= 0")
        self._ensure_storage(storage)
        response = self.at.execute(
            f"AT+CMGR={index}",
            timeout_seconds=self.command_timeout_seconds,
        )
        if not response.ok:
            raise ModemCommandError(f"AT+CMGR={index}: {response.error}")

        header_pos = next(
            (i for i, line in enumerate(response.lines) if line.startswith("+CMGR:")),
            None,
        )
        if header_pos is None:
            raise ModemCommandError("AT+CMGR response has no +CMGR header")
        status, sender, timestamp = _parse_cmgr_header(response.lines[header_pos])
        body_lines = response.lines[header_pos + 1 :]
        body = "\n".join(body_lines)
        logger.info("SMS_READ storage=%s index=%s sender=%s", storage, index, sender)
        return ModemSms(
            storage=storage,
            index=index,
            status=status,
            sender=sender,
            modem_timestamp=timestamp,
            raw_body=body,
        )

    def delete_sms(self, storage: str, index: int) -> None:
        self._ensure_storage(storage)
        response = self.at.execute(
            f"AT+CMGD={index}",
            timeout_seconds=self.command_timeout_seconds,
        )
        if not response.ok:
            raise ModemCommandError(f"AT+CMGD={index}: {response.error}")

    def list_all_sms(self) -> list[ModemSms]:
        response = self.at.execute(
            'AT+CMGL="ALL"',
            timeout_seconds=self.command_timeout_seconds,
        )
        if not response.ok:
            raise ModemCommandError(f'AT+CMGL="ALL": {response.error}')

        storage = self._selected_storage or "UNKNOWN"
        result: list[ModemSms] = []
        current: tuple[int, str, str, str | None] | None = None
        body_lines: list[str] = []

        def flush() -> None:
            nonlocal current, body_lines
            if current is None:
                return
            index, status, sender, timestamp = current
            result.append(
                ModemSms(
                    storage=storage,
                    index=index,
                    status=status,
                    sender=sender,
                    modem_timestamp=timestamp,
                    raw_body="\n".join(body_lines),
                )
            )
            current = None
            body_lines = []

        for line in response.lines:
            if line.startswith("+CMGL:"):
                flush()
                current = _parse_cmgl_header(line)
            elif current is not None:
                body_lines.append(line)
        flush()
        return result

    def poll_notification(self, *, timeout_seconds: float = 0.0) -> CmtiNotification | None:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        first = True
        while first or time.monotonic() < deadline:
            first = False
            remaining = max(0.0, deadline - time.monotonic())
            line = self.at.poll_urc(timeout_seconds=remaining if timeout_seconds else 0.0)
            if line is None:
                return None
            if line.startswith("+CMTI:"):
                try:
                    notification = parse_cmti(line)
                except ValueError:
                    logger.warning("SMS_NOTIFICATION_MALFORMED")
                    continue
                logger.info(
                    "SMS_NOTIFICATION storage=%s index=%s",
                    notification.storage,
                    notification.index,
                )
                return notification
            logger.info("GSM_URC kind=%s", line.split(":", 1)[0])
        return None
