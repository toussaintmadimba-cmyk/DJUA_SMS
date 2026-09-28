"""Models for the SIM800L/AT transport layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class AtResponse:
    command: str
    lines: tuple[str, ...] = ()
    ok: bool = False
    error: str | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class CmtiNotification:
    storage: str
    index: int


@dataclass(frozen=True)
class ModemSms:
    storage: str
    index: int
    status: str
    sender: str
    modem_timestamp: str | None
    raw_body: str


class SimStatus(str, Enum):
    READY = "READY"
    PIN_REQUIRED = "SIM PIN"
    PUK_REQUIRED = "SIM PUK"
    UNKNOWN = "UNKNOWN"


class NetworkRegistration(str, Enum):
    NOT_REGISTERED = "NOT_REGISTERED"
    HOME = "HOME"
    SEARCHING = "SEARCHING"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"
    ROAMING = "ROAMING"

    @property
    def registered(self) -> bool:
        return self in {NetworkRegistration.HOME, NetworkRegistration.ROAMING}


@dataclass(frozen=True)
class SignalQuality:
    rssi: int
    ber: int

    @property
    def known(self) -> bool:
        return self.rssi != 99


@dataclass(frozen=True)
class SmsStorage:
    name: str
    used: int
    total: int


@dataclass(frozen=True)
class ModemInitializationReport:
    modem_present: bool
    sim_status: SimStatus
    network_registration: NetworkRegistration
    signal: SignalQuality | None
    sms_text_mode: bool
    storage: SmsStorage | None
    cnmi_configured: bool

    @property
    def sim_ready(self) -> bool:
        return self.sim_status is SimStatus.READY

    @property
    def network_registered(self) -> bool:
        return self.network_registration.registered

    @property
    def sms_ready(self) -> bool:
        return self.sim_ready and self.sms_text_mode and self.cnmi_configured
