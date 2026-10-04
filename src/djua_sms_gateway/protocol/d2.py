"""Pure D2T/D2E codec, validation, authentication and backend mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import base64
import hashlib
import hmac
import re
import string
from typing import Iterable


class D2ProtocolError(ValueError):
    """Deterministic D2 protocol/security error with a stable machine code."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.field = field
        prefix = f"{field}: " if field else ""
        super().__init__(f"{code}: {prefix}{message}")


class D2AuthStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"


@dataclass(frozen=True)
class D2TMessage:
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
    flags: int
    auth: str
    signed_part: str = field(repr=False)
    raw_message: str = field(repr=False)

    @property
    def rtc_valid(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def gps_valid(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def battery_valid(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def solar_valid(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def ac_valid(self) -> bool:
        return bool(self.flags & 0x10)

    @property
    def solar_energy_complete(self) -> bool:
        return bool(self.flags & 0x20)

    @property
    def ac_energy_complete(self) -> bool:
        return bool(self.flags & 0x40)


@dataclass(frozen=True)
class D2EMessage:
    protocol_version: str
    device_id: str
    sequence: int
    rtc_epoch_s: int | None
    uptime_ms: int
    event_code: str
    latitude: float | None
    longitude: float | None
    distance_m: int | None
    flags: int
    auth: str
    signed_part: str = field(repr=False)
    raw_message: str = field(repr=False)

    @property
    def rtc_valid(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def gps_valid(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def distance_valid(self) -> bool:
        return bool(self.flags & 0x04)


D2Message = D2TMessage | D2EMessage

D2T_FIELD_COUNT = 22
D2E_FIELD_COUNT = 11
D2_MAX_SEPTETS = 160
UINT32_MAX = 0xFFFFFFFF
RTC_MIN_EPOCH_S = 946684800
RTC_MAX_EPOCH_S = 4102444799

DEVICE_ID_RE = re.compile(r"^[A-Z0-9-]{1,32}$")
BASE36_RE = re.compile(r"^[0-9A-Z]+$")
AUTH_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")

D2_ALLOWED_CHARS = frozenset(string.ascii_letters + string.digits + ",-_")

GSM7_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ "
    "!\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENSION = frozenset("^{}\\[~]|€\f")


def gsm7_septet_count(value: str) -> int:
    """Return the real GSM 03.38 septet cost or reject non-GSM text."""

    count = 0
    for char in value:
        if char in GSM7_BASIC:
            count += 1
        elif char in GSM7_EXTENSION:
            count += 2
        else:
            raise D2ProtocolError(
                "NON_GSM7",
                "character is not representable in GSM 03.38",
            )
    return count


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
            "whitespace is not allowed in D2",
        )


def encode_base36(value: int) -> str:
    if value < 0:
        raise ValueError("encode_base36 expects an unsigned integer")
    if value == 0:
        return "0"

    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = ""
    while value:
        value, remainder = divmod(value, 36)
        out = chars[remainder] + out
    return out


def _decode_u36(
    token: str,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    fixed_width: int | None = None,
) -> int:
    if fixed_width is not None and len(token) != fixed_width:
        raise D2ProtocolError(
            "NON_CANONICAL_BASE36",
            f"expected exactly {fixed_width} characters",
            field_name,
        )
    if not token or BASE36_RE.fullmatch(token) is None:
        raise D2ProtocolError(
            "INVALID_BASE36",
            "expected uppercase base36",
            field_name,
        )
    if fixed_width is None and len(token) > 1 and token.startswith("0"):
        raise D2ProtocolError(
            "NON_CANONICAL_BASE36",
            "leading zero is forbidden",
            field_name,
        )

    value = int(token, 36)
    if value < minimum or (maximum is not None and value > maximum):
        raise D2ProtocolError(
            "OUT_OF_RANGE",
            f"decoded value {value} is outside the allowed range",
            field_name,
        )
    return value


def _decode_optional_u36(
    token: str,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int | None:
    if token == "-":
        return None
    return _decode_u36(
        token,
        field_name,
        minimum=minimum,
        maximum=maximum,
    )


def _decode_optional_s36(
    token: str,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    if token == "-":
        return None

    negative = token.startswith("-")
    digits = token[1:] if negative else token
    value = _decode_u36(digits, field_name)

    if negative:
        if value == 0:
            raise D2ProtocolError(
                "NON_CANONICAL_BASE36",
                "-0 is forbidden",
                field_name,
            )
        value = -value

    if value < minimum or value > maximum:
        raise D2ProtocolError(
            "OUT_OF_RANGE",
            f"decoded value {value} is outside the allowed range",
            field_name,
        )
    return value


def _scaled(value: int | None, divisor: int | float) -> float | None:
    return None if value is None else value / divisor


def _validate_auth_shape(auth: str) -> None:
    if auth == "-":
        return
    if AUTH_RE.fullmatch(auth) is None:
        raise D2ProtocolError(
            "INVALID_AUTH",
            "expected '-' or exactly 11 base64url characters",
            "auth",
        )


def _presence(flag: bool, values: Iterable[object | None], name: str) -> None:
    values = tuple(values)
    if flag and any(value is None for value in values):
        raise D2ProtocolError(
            "FLAG_VALUE_MISMATCH",
            f"{name} flag requires all fields to be present",
            name,
        )
    if not flag and any(value is not None for value in values):
        raise D2ProtocolError(
            "FLAG_VALUE_MISMATCH",
            f"{name} fields must be '-' when flag is clear",
            name,
        )


def validate_d2_message(message: D2Message) -> None:
    if DEVICE_ID_RE.fullmatch(message.device_id) is None:
        raise D2ProtocolError(
            "INVALID_DEVICE_ID",
            "expected [A-Z0-9-]{1,32}",
            "device_id",
        )

    if isinstance(message, D2TMessage):
        if message.flags & ~0x7F:
            raise D2ProtocolError(
                "INVALID_FLAGS",
                "reserved D2T flag bits must be zero",
                "flags",
            )
        if message.solar_energy_complete and not message.solar_valid:
            raise D2ProtocolError(
                "FLAG_DEPENDENCY",
                "solar energy complete requires solar valid",
                "flags",
            )
        if message.ac_energy_complete and not message.ac_valid:
            raise D2ProtocolError(
                "FLAG_DEPENDENCY",
                "AC energy complete requires AC valid",
                "flags",
            )

        _presence(message.rtc_valid, (message.rtc_epoch_s,), "rtc")
        _presence(message.gps_valid, (message.latitude, message.longitude), "gps")
        _presence(
            message.battery_valid,
            (
                message.battery_voltage,
                message.battery_current,
                message.battery_power,
            ),
            "battery",
        )
        _presence(
            message.solar_valid,
            (
                message.solar_voltage,
                message.solar_current,
                message.solar_power,
            ),
            "solar",
        )
        _presence(
            message.solar_energy_complete,
            (message.solar_energy_interval_wh,),
            "solar_energy",
        )
        _presence(
            message.ac_valid,
            (
                message.ac_voltage,
                message.ac_current,
                message.ac_active_power,
                message.ac_apparent_power,
            ),
            "ac",
        )
        _presence(
            message.ac_energy_complete,
            (message.ac_energy_interval_wh,),
            "ac_energy",
        )
    else:
        if message.flags & ~0x07:
            raise D2ProtocolError(
                "INVALID_FLAGS",
                "reserved D2E flag bits must be zero",
                "flags",
            )
        if message.distance_valid and not message.gps_valid:
            raise D2ProtocolError(
                "FLAG_DEPENDENCY",
                "distance valid requires GPS valid",
                "flags",
            )

        _presence(message.rtc_valid, (message.rtc_epoch_s,), "rtc")
        _presence(message.gps_valid, (message.latitude, message.longitude), "gps")
        _presence(message.distance_valid, (message.distance_m,), "distance")


def parse_d2(raw_message: str) -> D2Message:
    _validate_wire(raw_message)
    fields = raw_message.split(",")
    protocol = fields[0]

    if protocol == "D2T":
        if len(fields) != D2T_FIELD_COUNT:
            raise D2ProtocolError(
                "FIELD_COUNT",
                f"D2T requires {D2T_FIELD_COUNT} fields, got {len(fields)}",
            )

        (
            _,
            device_id,
            sequence_raw,
            rtc_raw,
            uptime_raw,
            interval_raw,
            latitude_raw,
            longitude_raw,
            battery_voltage_raw,
            battery_current_raw,
            battery_power_raw,
            solar_voltage_raw,
            solar_current_raw,
            solar_power_raw,
            solar_energy_raw,
            ac_voltage_raw,
            ac_current_raw,
            ac_active_power_raw,
            ac_apparent_power_raw,
            ac_energy_raw,
            flags_raw,
            auth,
        ) = fields

        _validate_auth_shape(auth)
        flags = _decode_u36(
            flags_raw,
            "flags",
            maximum=0x7F,
            fixed_width=2,
        )
        signed_part = ",".join(fields[:-1])

        message: D2Message = D2TMessage(
            protocol_version="D2T",
            device_id=device_id,
            sequence=_decode_u36(
                sequence_raw,
                "sequence",
                minimum=1,
                maximum=UINT32_MAX,
            ),
            rtc_epoch_s=_decode_optional_u36(
                rtc_raw,
                "rtc",
                minimum=RTC_MIN_EPOCH_S,
                maximum=RTC_MAX_EPOCH_S,
            ),
            uptime_ms=_decode_u36(
                uptime_raw,
                "uptime_ms",
                maximum=UINT32_MAX,
            ),
            interval_seconds=_decode_u36(
                interval_raw,
                "interval_seconds",
                minimum=10,
                maximum=86400,
            ),
            latitude=_scaled(
                _decode_optional_s36(
                    latitude_raw,
                    "latitude",
                    minimum=-9000000,
                    maximum=9000000,
                ),
                100000,
            ),
            longitude=_scaled(
                _decode_optional_s36(
                    longitude_raw,
                    "longitude",
                    minimum=-18000000,
                    maximum=18000000,
                ),
                100000,
            ),
            battery_voltage=_scaled(
                _decode_optional_u36(
                    battery_voltage_raw,
                    "battery_voltage",
                    maximum=32000,
                ),
                1000,
            ),
            battery_current=_scaled(
                _decode_optional_s36(
                    battery_current_raw,
                    "battery_current",
                    minimum=-200000,
                    maximum=200000,
                ),
                1000,
            ),
            battery_power=_scaled(
                _decode_optional_s36(
                    battery_power_raw,
                    "battery_power",
                    minimum=-64000,
                    maximum=64000,
                ),
                10,
            ),
            solar_voltage=_scaled(
                _decode_optional_u36(
                    solar_voltage_raw,
                    "solar_voltage",
                    maximum=100000,
                ),
                1000,
            ),
            solar_current=_scaled(
                _decode_optional_s36(
                    solar_current_raw,
                    "solar_current",
                    minimum=-100000,
                    maximum=100000,
                ),
                1000,
            ),
            solar_power=_scaled(
                _decode_optional_s36(
                    solar_power_raw,
                    "solar_power",
                    minimum=-100000,
                    maximum=100000,
                ),
                10,
            ),
            solar_energy_interval_wh=_scaled(
                _decode_optional_s36(
                    solar_energy_raw,
                    "solar_energy",
                    minimum=-24000000,
                    maximum=24000000,
                ),
                100,
            ),
            ac_voltage=_scaled(
                _decode_optional_u36(
                    ac_voltage_raw,
                    "ac_voltage",
                    maximum=4000,
                ),
                10,
            ),
            ac_current=_scaled(
                _decode_optional_u36(
                    ac_current_raw,
                    "ac_current",
                    maximum=3000,
                ),
                100,
            ),
            ac_active_power=_scaled(
                _decode_optional_s36(
                    ac_active_power_raw,
                    "ac_active_power",
                    minimum=-120000,
                    maximum=120000,
                ),
                10,
            ),
            ac_apparent_power=_scaled(
                _decode_optional_u36(
                    ac_apparent_power_raw,
                    "ac_apparent_power",
                    maximum=120000,
                ),
                10,
            ),
            ac_energy_interval_wh=_scaled(
                _decode_optional_s36(
                    ac_energy_raw,
                    "ac_energy",
                    minimum=-28800000,
                    maximum=28800000,
                ),
                100,
            ),
            flags=flags,
            auth=auth,
            signed_part=signed_part,
            raw_message=raw_message,
        )

    elif protocol == "D2E":
        if len(fields) != D2E_FIELD_COUNT:
            raise D2ProtocolError(
                "FIELD_COUNT",
                f"D2E requires {D2E_FIELD_COUNT} fields, got {len(fields)}",
            )

        (
            _,
            device_id,
            sequence_raw,
            rtc_raw,
            uptime_raw,
            event_code,
            latitude_raw,
            longitude_raw,
            distance_raw,
            flags_raw,
            auth,
        ) = fields

        _validate_auth_shape(auth)
        if event_code not in {"GX", "GE"}:
            raise D2ProtocolError(
                "UNSUPPORTED_EVENT",
                "D2E v1 supports only GX and GE",
                "event",
            )

        flags = _decode_u36(
            flags_raw,
            "flags",
            maximum=0x07,
            fixed_width=2,
        )
        signed_part = ",".join(fields[:-1])

        message = D2EMessage(
            protocol_version="D2E",
            device_id=device_id,
            sequence=_decode_u36(
                sequence_raw,
                "sequence",
                minimum=1,
                maximum=UINT32_MAX,
            ),
            rtc_epoch_s=_decode_optional_u36(
                rtc_raw,
                "rtc",
                minimum=RTC_MIN_EPOCH_S,
                maximum=RTC_MAX_EPOCH_S,
            ),
            uptime_ms=_decode_u36(
                uptime_raw,
                "uptime_ms",
                maximum=UINT32_MAX,
            ),
            event_code=event_code,
            latitude=_scaled(
                _decode_optional_s36(
                    latitude_raw,
                    "latitude",
                    minimum=-9000000,
                    maximum=9000000,
                ),
                100000,
            ),
            longitude=_scaled(
                _decode_optional_s36(
                    longitude_raw,
                    "longitude",
                    minimum=-18000000,
                    maximum=18000000,
                ),
                100000,
            ),
            distance_m=_decode_optional_u36(
                distance_raw,
                "distance_m",
                maximum=1000000,
            ),
            flags=flags,
            auth=auth,
            signed_part=signed_part,
            raw_message=raw_message,
        )
    else:
        raise D2ProtocolError(
            "UNSUPPORTED_PROTOCOL",
            "expected D2T or D2E",
            "protocol",
        )

    validate_d2_message(message)
    return message


def calculate_hmac_tag(signed_part: str, key: bytes) -> str:
    if len(key) != 32:
        raise D2ProtocolError(
            "AUTH_KEY_INVALID",
            "D2 device key must contain exactly 32 bytes",
        )
    digest = hmac.new(
        key,
        signed_part.encode("ascii"),
        hashlib.sha256,
    ).digest()[:8]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_d2_security(
    message: D2Message,
    *,
    mode: str,
    key: bytes | None,
    sender: str | None = None,
    allowed_senders: Iterable[str] | None = None,
) -> D2AuthStatus:
    mode_value = mode.strip().lower()
    if mode_value not in {"development", "production"}:
        raise ValueError("D2 auth mode must be development or production")

    if message.auth == "-":
        if mode_value == "production":
            raise D2ProtocolError(
                "AUTH_REQUIRED",
                "production D2 requires HMAC",
                "auth",
            )
        return D2AuthStatus.NOT_VERIFIED

    if key is None:
        raise D2ProtocolError(
            "AUTH_KEY_MISSING",
            "no HMAC key configured for device",
            "auth",
        )

    expected = calculate_hmac_tag(message.signed_part, key)
    if not hmac.compare_digest(expected, message.auth):
        raise D2ProtocolError(
            "AUTH_INVALID",
            "HMAC verification failed",
            "auth",
        )

    if mode_value == "production":
        if sender is None or E164_RE.fullmatch(sender) is None:
            raise D2ProtocolError(
                "SENDER_INVALID",
                "production sender must be canonical E.164",
                "sender",
            )
        configured = tuple(allowed_senders or ())
        if not configured:
            raise D2ProtocolError(
                "SENDER_BINDING_REQUIRED",
                "no sender binding configured for device",
                "sender",
            )
        if sender not in configured:
            raise D2ProtocolError(
                "SENDER_DEVICE_MISMATCH",
                "sender is not bound to device_id",
                "sender",
            )

    return D2AuthStatus.VERIFIED


def derive_message_id(message: D2Message) -> str:
    return f"D2:{message.device_id}:{encode_base36(message.sequence)}"


def _formatted_timestamp(epoch_s: int) -> str:
    local = datetime.fromtimestamp(
        epoch_s,
        timezone.utc,
    ).astimezone(timezone(timedelta(hours=1)))
    return local.isoformat(timespec="seconds")


def backend_topic(
    message: D2Message,
    prefix: str = "djua/test",
) -> str:
    suffix = (
        "telemetry"
        if isinstance(message, D2TMessage)
        else "geofence/events"
    )
    return f"{prefix.rstrip('/')}/{message.device_id}/{suffix}"


def normalize_d2_to_backend(
    message: D2Message,
    *,
    gateway_received_at: str,
    auth_status: D2AuthStatus,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol": message.protocol_version,
        "message_id": derive_message_id(message),
        "sequence": message.sequence,
        "kit_id": message.device_id,
        "uptime_ms": message.uptime_ms,
        "gateway_received_at": gateway_received_at,
    }

    if message.rtc_valid:
        payload["timestamp"] = _formatted_timestamp(
            message.rtc_epoch_s  # type: ignore[arg-type]
        )
        payload["timezone"] = "GMT+1"

    if isinstance(message, D2TMessage):
        payload.update(
            {
                "timestamp_ms": message.uptime_ms,
                "interval_seconds": message.interval_seconds,
                "latitude": (
                    message.latitude if message.gps_valid else None
                ),
                "longitude": (
                    message.longitude if message.gps_valid else None
                ),
                "battery": {
                    "voltage_v": (
                        message.battery_voltage
                        if message.battery_valid
                        else None
                    ),
                    "current_a": (
                        message.battery_current
                        if message.battery_valid
                        else None
                    ),
                    "power_w": (
                        message.battery_power
                        if message.battery_valid
                        else None
                    ),
                },
                "solar": {
                    "voltage_v": (
                        message.solar_voltage
                        if message.solar_valid
                        else None
                    ),
                    "current_a": (
                        message.solar_current
                        if message.solar_valid
                        else None
                    ),
                    "power_w": (
                        message.solar_power
                        if message.solar_valid
                        else None
                    ),
                    "energy_interval_wh": (
                        message.solar_energy_interval_wh
                        if message.solar_energy_complete
                        else None
                    ),
                },
                "ac_load": {
                    "voltage_v": (
                        message.ac_voltage
                        if message.ac_valid
                        else None
                    ),
                    "current_a": (
                        message.ac_current
                        if message.ac_valid
                        else None
                    ),
                    "active_power_w": (
                        message.ac_active_power
                        if message.ac_valid
                        else None
                    ),
                    "apparent_power_va": (
                        message.ac_apparent_power
                        if message.ac_valid
                        else None
                    ),
                    "energy_interval_wh": (
                        message.ac_energy_interval_wh
                        if message.ac_energy_complete
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
                },
                "auth_status": auth_status.value,
            }
        )
    else:
        event = (
            "GEOFENCE_EXIT"
            if message.event_code == "GX"
            else "GEOFENCE_ENTER"
        )
        state = "OUTSIDE" if message.event_code == "GX" else "INSIDE"
        payload.update(
            {
                "event": event,
                "state": state,
                "position_usable": message.gps_valid,
                "latitude": (
                    message.latitude if message.gps_valid else None
                ),
                "longitude": (
                    message.longitude if message.gps_valid else None
                ),
                "distance_m": (
                    message.distance_m if message.distance_valid else None
                ),
                "validity": {
                    "rtc": message.rtc_valid,
                    "gps": message.gps_valid,
                    "distance": message.distance_valid,
                },
                "auth_status": auth_status.value,
            }
        )

    return payload
