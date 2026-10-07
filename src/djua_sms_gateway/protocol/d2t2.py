"""Compact D2T2 telemetry codec with DC-load measurements.

D2T2 is a new wire format. It does not replace or alter D2T/D2E parsing.
The wire shape is exactly:

    D2T2,DEV,PAYLOAD,AUTH

PAYLOAD is exactly 60 bytes encoded as 80 unpadded Base64URL characters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import base64
import binascii
import re
from typing import Iterable

from .d2 import (
    AUTH_RE,
    D2_ALLOWED_CHARS,
    D2AuthStatus,
    D2_MAX_SEPTETS,
    D2ProtocolError,
    DEVICE_ID_RE,
    RTC_MAX_EPOCH_S,
    RTC_MIN_EPOCH_S,
    UINT32_MAX,
    derive_message_id,
    gsm7_septet_count,
    verify_d2_security,
)


D2T2_FIELD_COUNT = 4
D2T2_PAYLOAD_BYTES = 60
D2T2_PAYLOAD_CHARS = 80
D2T2_DEFINED_FLAGS = 0x01FF

D2T2_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{80}$")

# Bit order is network-style: most-significant bit first.
# Signed fields use fixed-width two's-complement.
# name, width, signed
D2T2_LAYOUT = (
    ("sequence", 32, False),
    ("rtc_epoch_s", 32, False),
    ("uptime_ms", 32, False),
    ("interval_seconds", 17, False),
    ("latitude_raw", 25, True),
    ("longitude_raw", 26, True),
    ("battery_voltage_raw", 15, False),
    ("battery_current_raw", 19, True),
    ("battery_power_raw", 17, True),
    ("solar_voltage_raw", 17, False),
    ("solar_current_raw", 18, True),
    ("solar_power_raw", 18, True),
    ("solar_energy_raw", 26, True),
    ("ac_voltage_raw", 12, False),
    ("ac_current_raw", 12, False),
    ("ac_active_power_raw", 18, True),
    ("ac_apparent_power_raw", 17, False),
    ("ac_energy_raw", 26, True),
    ("dc_voltage_raw", 17, False),
    ("dc_current_raw", 18, True),
    ("dc_power_raw", 18, True),
    ("dc_energy_raw", 26, True),
    ("flags", 16, False),
    ("reserved_tail", 6, False),
)

if sum(width for _, width, _ in D2T2_LAYOUT) != D2T2_PAYLOAD_BYTES * 8:
    raise RuntimeError("D2T2 bit layout must occupy exactly 60 bytes")


@dataclass(frozen=True)
class D2T2Message:
    protocol_version: str
    device_id: str
    sequence: int
    rtc_epoch_s: int | None
    uptime_ms: int
    interval_seconds: int
    latitude: float | None
    longitude: float | None
    battery_voltage: float | None
    battery_current: float | None
    battery_power: float | None
    solar_voltage: float | None
    solar_current: float | None
    solar_power: float | None
    solar_energy_interval_wh: float | None
    ac_voltage: float | None
    ac_current: float | None
    ac_active_power: float | None
    ac_apparent_power: float | None
    ac_energy_interval_wh: float | None
    dc_load_voltage: float | None
    dc_load_current: float | None
    dc_load_power: float | None
    dc_load_energy_interval_wh: float | None
    flags: int
    auth: str
    payload: str = field(repr=False)
    signed_part: str = field(repr=False)
    raw_message: str = field(repr=False)

    @property
    def rtc_valid(self) -> bool:
        return bool(self.flags & 0x0001)

    @property
    def gps_valid(self) -> bool:
        return bool(self.flags & 0x0002)

    @property
    def battery_valid(self) -> bool:
        return bool(self.flags & 0x0004)

    @property
    def solar_valid(self) -> bool:
        return bool(self.flags & 0x0008)

    @property
    def ac_valid(self) -> bool:
        return bool(self.flags & 0x0010)

    @property
    def solar_energy_complete(self) -> bool:
        return bool(self.flags & 0x0020)

    @property
    def ac_energy_complete(self) -> bool:
        return bool(self.flags & 0x0040)

    @property
    def dc_load_valid(self) -> bool:
        return bool(self.flags & 0x0080)

    @property
    def dc_load_energy_complete(self) -> bool:
        return bool(self.flags & 0x0100)


def _validate_wire(raw_message: str) -> None:
    if not raw_message:
        raise D2ProtocolError("EMPTY_MESSAGE", "message is empty")

    septets = gsm7_septet_count(raw_message)
    if septets > D2_MAX_SEPTETS:
        raise D2ProtocolError(
            "SMS_TOO_LONG",
            f"{septets} septets exceeds {D2_MAX_SEPTETS}",
        )

    if any(char not in D2_ALLOWED_CHARS for char in raw_message):
        raise D2ProtocolError(
            "D2_CHARSET",
            "character is outside the D2 alphabet",
        )

    if any(char.isspace() for char in raw_message):
        raise D2ProtocolError(
            "UNEXPECTED_WHITESPACE",
            "whitespace is not allowed in D2T2",
        )


def _validate_auth_shape(auth: str) -> None:
    if auth == "-":
        return
    if AUTH_RE.fullmatch(auth) is None:
        raise D2ProtocolError(
            "INVALID_AUTH",
            "expected '-' or exactly 11 base64url characters",
            "auth",
        )


def _decode_payload(payload: str) -> dict[str, int]:
    if D2T2_PAYLOAD_RE.fullmatch(payload) is None:
        raise D2ProtocolError(
            "D2T2_PAYLOAD_SHAPE",
            "payload must be exactly 80 base64url characters",
            "payload",
        )

    try:
        raw = base64.b64decode(
            payload.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise D2ProtocolError(
            "D2T2_PAYLOAD_ENCODING",
            "payload is not canonical base64url",
            "payload",
        ) from exc

    if len(raw) != D2T2_PAYLOAD_BYTES:
        raise D2ProtocolError(
            "D2T2_PAYLOAD_LENGTH",
            f"payload must decode to exactly {D2T2_PAYLOAD_BYTES} bytes",
            "payload",
        )

    canonical = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if canonical != payload:
        raise D2ProtocolError(
            "D2T2_PAYLOAD_ENCODING",
            "payload is not canonical unpadded base64url",
            "payload",
        )

    packed = int.from_bytes(raw, "big")
    remaining = D2T2_PAYLOAD_BYTES * 8
    values: dict[str, int] = {}

    for name, width, signed in D2T2_LAYOUT:
        remaining -= width
        encoded = (packed >> remaining) & ((1 << width) - 1)
        if signed and encoded & (1 << (width - 1)):
            encoded -= 1 << width
        values[name] = encoded

    if remaining != 0:
        raise RuntimeError("D2T2 decoder did not consume the full payload")
    return values


def _require_range(
    value: int,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if value < minimum or value > maximum:
        raise D2ProtocolError(
            "OUT_OF_RANGE",
            f"decoded value {value} is outside the allowed range",
            field_name,
        )


def _require_zero_when_invalid(
    valid: bool,
    values: tuple[int, ...],
    field_name: str,
) -> None:
    if not valid and any(value != 0 for value in values):
        raise D2ProtocolError(
            "NON_CANONICAL_ABSENT",
            f"{field_name} raw slot(s) must be zero when validity flag is clear",
            field_name,
        )


def _scaled(value: int, divisor: int | float) -> float:
    return value / divisor


def parse_d2t2(raw_message: str) -> D2T2Message:
    _validate_wire(raw_message)
    fields = raw_message.split(",")

    if len(fields) != D2T2_FIELD_COUNT:
        raise D2ProtocolError(
            "FIELD_COUNT",
            f"D2T2 requires {D2T2_FIELD_COUNT} fields, got {len(fields)}",
        )

    protocol, device_id, payload, auth = fields
    if protocol != "D2T2":
        raise D2ProtocolError(
            "UNSUPPORTED_PROTOCOL",
            "expected D2T2",
            "protocol",
        )
    if DEVICE_ID_RE.fullmatch(device_id) is None:
        raise D2ProtocolError(
            "INVALID_DEVICE_ID",
            "expected [A-Z0-9-]{1,32}",
            "device_id",
        )

    _validate_auth_shape(auth)
    values = _decode_payload(payload)

    if values["reserved_tail"] != 0:
        raise D2ProtocolError(
            "D2T2_RESERVED_BITS",
            "reserved payload tail bits must be zero",
            "payload",
        )

    flags = values["flags"]
    if flags & ~D2T2_DEFINED_FLAGS:
        raise D2ProtocolError(
            "INVALID_FLAGS",
            "reserved D2T2 flag bits must be zero",
            "flags",
        )

    sequence = values["sequence"]
    _require_range(sequence, "sequence", 1, UINT32_MAX)
    _require_range(
        values["interval_seconds"],
        "interval_seconds",
        10,
        86400,
    )

    rtc_valid = bool(flags & 0x0001)
    gps_valid = bool(flags & 0x0002)
    battery_valid = bool(flags & 0x0004)
    solar_valid = bool(flags & 0x0008)
    ac_valid = bool(flags & 0x0010)
    solar_energy_complete = bool(flags & 0x0020)
    ac_energy_complete = bool(flags & 0x0040)
    dc_load_valid = bool(flags & 0x0080)
    dc_load_energy_complete = bool(flags & 0x0100)

    if solar_energy_complete and not solar_valid:
        raise D2ProtocolError(
            "FLAG_DEPENDENCY",
            "solar energy complete requires solar valid",
            "flags",
        )
    if ac_energy_complete and not ac_valid:
        raise D2ProtocolError(
            "FLAG_DEPENDENCY",
            "AC energy complete requires AC valid",
            "flags",
        )
    if dc_load_energy_complete and not dc_load_valid:
        raise D2ProtocolError(
            "FLAG_DEPENDENCY",
            "DC load energy complete requires DC load valid",
            "flags",
        )

    _require_zero_when_invalid(
        rtc_valid,
        (values["rtc_epoch_s"],),
        "rtc",
    )
    _require_zero_when_invalid(
        gps_valid,
        (values["latitude_raw"], values["longitude_raw"]),
        "gps",
    )
    _require_zero_when_invalid(
        battery_valid,
        (
            values["battery_voltage_raw"],
            values["battery_current_raw"],
            values["battery_power_raw"],
        ),
        "battery",
    )
    _require_zero_when_invalid(
        solar_valid,
        (
            values["solar_voltage_raw"],
            values["solar_current_raw"],
            values["solar_power_raw"],
        ),
        "solar",
    )
    _require_zero_when_invalid(
        solar_energy_complete,
        (values["solar_energy_raw"],),
        "solar_energy",
    )
    _require_zero_when_invalid(
        ac_valid,
        (
            values["ac_voltage_raw"],
            values["ac_current_raw"],
            values["ac_active_power_raw"],
            values["ac_apparent_power_raw"],
        ),
        "ac",
    )
    _require_zero_when_invalid(
        ac_energy_complete,
        (values["ac_energy_raw"],),
        "ac_energy",
    )
    _require_zero_when_invalid(
        dc_load_valid,
        (
            values["dc_voltage_raw"],
            values["dc_current_raw"],
            values["dc_power_raw"],
        ),
        "dc_load",
    )
    _require_zero_when_invalid(
        dc_load_energy_complete,
        (values["dc_energy_raw"],),
        "dc_load_energy",
    )

    if rtc_valid:
        _require_range(
            values["rtc_epoch_s"],
            "rtc",
            RTC_MIN_EPOCH_S,
            RTC_MAX_EPOCH_S,
        )
    if gps_valid:
        _require_range(values["latitude_raw"], "latitude", -9000000, 9000000)
        _require_range(
            values["longitude_raw"],
            "longitude",
            -18000000,
            18000000,
        )
    if battery_valid:
        _require_range(
            values["battery_voltage_raw"],
            "battery_voltage",
            0,
            32000,
        )
        _require_range(
            values["battery_current_raw"],
            "battery_current",
            -200000,
            200000,
        )
        _require_range(
            values["battery_power_raw"],
            "battery_power",
            -64000,
            64000,
        )
    if solar_valid:
        _require_range(
            values["solar_voltage_raw"],
            "solar_voltage",
            0,
            100000,
        )
        _require_range(
            values["solar_current_raw"],
            "solar_current",
            -100000,
            100000,
        )
        _require_range(
            values["solar_power_raw"],
            "solar_power",
            -100000,
            100000,
        )
    if solar_energy_complete:
        _require_range(
            values["solar_energy_raw"],
            "solar_energy",
            -24000000,
            24000000,
        )
    if ac_valid:
        _require_range(values["ac_voltage_raw"], "ac_voltage", 0, 4000)
        _require_range(values["ac_current_raw"], "ac_current", 0, 3000)
        _require_range(
            values["ac_active_power_raw"],
            "ac_active_power",
            -120000,
            120000,
        )
        _require_range(
            values["ac_apparent_power_raw"],
            "ac_apparent_power",
            0,
            120000,
        )
    if ac_energy_complete:
        _require_range(
            values["ac_energy_raw"],
            "ac_energy",
            -28800000,
            28800000,
        )
    if dc_load_valid:
        _require_range(
            values["dc_voltage_raw"],
            "dc_load_voltage",
            0,
            100000,
        )
        _require_range(
            values["dc_current_raw"],
            "dc_load_current",
            -100000,
            100000,
        )
        _require_range(
            values["dc_power_raw"],
            "dc_load_power",
            -100000,
            100000,
        )
    if dc_load_energy_complete:
        _require_range(
            values["dc_energy_raw"],
            "dc_load_energy",
            -24000000,
            24000000,
        )

    signed_part = ",".join(fields[:-1])
    return D2T2Message(
        protocol_version="D2T2",
        device_id=device_id,
        sequence=sequence,
        rtc_epoch_s=values["rtc_epoch_s"] if rtc_valid else None,
        uptime_ms=values["uptime_ms"],
        interval_seconds=values["interval_seconds"],
        latitude=(
            _scaled(values["latitude_raw"], 100000) if gps_valid else None
        ),
        longitude=(
            _scaled(values["longitude_raw"], 100000) if gps_valid else None
        ),
        battery_voltage=(
            _scaled(values["battery_voltage_raw"], 1000)
            if battery_valid
            else None
        ),
        battery_current=(
            _scaled(values["battery_current_raw"], 1000)
            if battery_valid
            else None
        ),
        battery_power=(
            _scaled(values["battery_power_raw"], 10)
            if battery_valid
            else None
        ),
        solar_voltage=(
            _scaled(values["solar_voltage_raw"], 1000)
            if solar_valid
            else None
        ),
        solar_current=(
            _scaled(values["solar_current_raw"], 1000)
            if solar_valid
            else None
        ),
        solar_power=(
            _scaled(values["solar_power_raw"], 10)
            if solar_valid
            else None
        ),
        solar_energy_interval_wh=(
            _scaled(values["solar_energy_raw"], 100)
            if solar_energy_complete
            else None
        ),
        ac_voltage=(
            _scaled(values["ac_voltage_raw"], 10) if ac_valid else None
        ),
        ac_current=(
            _scaled(values["ac_current_raw"], 100) if ac_valid else None
        ),
        ac_active_power=(
            _scaled(values["ac_active_power_raw"], 10)
            if ac_valid
            else None
        ),
        ac_apparent_power=(
            _scaled(values["ac_apparent_power_raw"], 10)
            if ac_valid
            else None
        ),
        ac_energy_interval_wh=(
            _scaled(values["ac_energy_raw"], 100)
            if ac_energy_complete
            else None
        ),
        dc_load_voltage=(
            _scaled(values["dc_voltage_raw"], 1000)
            if dc_load_valid
            else None
        ),
        dc_load_current=(
            _scaled(values["dc_current_raw"], 1000)
            if dc_load_valid
            else None
        ),
        dc_load_power=(
            _scaled(values["dc_power_raw"], 10)
            if dc_load_valid
            else None
        ),
        dc_load_energy_interval_wh=(
            _scaled(values["dc_energy_raw"], 100)
            if dc_load_energy_complete
            else None
        ),
        flags=flags,
        auth=auth,
        payload=payload,
        signed_part=signed_part,
        raw_message=raw_message,
    )


def verify_d2t2_security(
    message: D2T2Message,
    *,
    mode: str,
    key: bytes | None,
    sender: str | None = None,
    allowed_senders: Iterable[str] | None = None,
) -> D2AuthStatus:
    return verify_d2_security(
        message,  # type: ignore[arg-type]
        mode=mode,
        key=key,
        sender=sender,
        allowed_senders=allowed_senders,
    )


def _formatted_timestamp(epoch_s: int) -> str:
    local = datetime.fromtimestamp(
        epoch_s,
        timezone.utc,
    ).astimezone(timezone(timedelta(hours=1)))
    return local.isoformat(timespec="seconds")


def d2t2_backend_topic(
    message: D2T2Message,
    prefix: str = "djua/test",
) -> str:
    return f"{prefix.rstrip('/')}/{message.device_id}/telemetry"


def normalize_d2t2_to_backend(
    message: D2T2Message,
    *,
    gateway_received_at: str,
    auth_status: D2AuthStatus,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol": "D2T2",
        "message_id": derive_message_id(message),  # type: ignore[arg-type]
        "sequence": message.sequence,
        "kit_id": message.device_id,
        "uptime_ms": message.uptime_ms,
        "timestamp_ms": message.uptime_ms,
        "gateway_received_at": gateway_received_at,
        "interval_seconds": message.interval_seconds,
        "latitude": message.latitude if message.gps_valid else None,
        "longitude": message.longitude if message.gps_valid else None,
        "battery": {
            "voltage_v": (
                message.battery_voltage if message.battery_valid else None
            ),
            "current_a": (
                message.battery_current if message.battery_valid else None
            ),
            "power_w": (
                message.battery_power if message.battery_valid else None
            ),
        },
        "solar": {
            "voltage_v": (
                message.solar_voltage if message.solar_valid else None
            ),
            "current_a": (
                message.solar_current if message.solar_valid else None
            ),
            "power_w": (
                message.solar_power if message.solar_valid else None
            ),
            "energy_interval_wh": (
                message.solar_energy_interval_wh
                if message.solar_energy_complete
                else None
            ),
        },
        "ac_load": {
            "voltage_v": (
                message.ac_voltage if message.ac_valid else None
            ),
            "current_a": (
                message.ac_current if message.ac_valid else None
            ),
            "active_power_w": (
                message.ac_active_power if message.ac_valid else None
            ),
            "apparent_power_va": (
                message.ac_apparent_power if message.ac_valid else None
            ),
            "energy_interval_wh": (
                message.ac_energy_interval_wh
                if message.ac_energy_complete
                else None
            ),
        },
        "dc_load": {
            "voltage_v": (
                message.dc_load_voltage
                if message.dc_load_valid
                else None
            ),
            "current_a": (
                message.dc_load_current
                if message.dc_load_valid
                else None
            ),
            "power_w": (
                message.dc_load_power
                if message.dc_load_valid
                else None
            ),
            "energy_interval_wh": (
                message.dc_load_energy_interval_wh
                if message.dc_load_energy_complete
                else None
            ),
        },
        "validity": {
            "rtc": message.rtc_valid,
            "gps": message.gps_valid,
            "battery": message.battery_valid,
            "solar": message.solar_valid,
            "solar_energy": message.solar_energy_complete,
            "ac": message.ac_valid,
            "ac_energy": message.ac_energy_complete,
            "dc_load": message.dc_load_valid,
            "dc_load_energy": message.dc_load_energy_complete,
        },
        "auth_status": auth_status.value,
    }

    if message.rtc_valid:
        payload["timestamp"] = _formatted_timestamp(
            message.rtc_epoch_s  # type: ignore[arg-type]
        )
        payload["timezone"] = "GMT+1"

    return payload
