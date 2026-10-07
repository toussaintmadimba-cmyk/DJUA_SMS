# DJUA SMS Protocol D2T2 — compact telemetry with DC load

Status: **gateway contract implemented** in DJUA_SMS. The transmitter firmware is not implemented in this repository.

D2T2 is a new telemetry wire format. It does not modify the existing D2T or D2E contracts.

## 1. Purpose

D2T2 solves one specific constraint:

```text
keep every D2T measurement
+ add DC-load voltage/current/power/energy
+ HMAC authentication
+ one GSM-7 SMS only
```

The new transmitter does not need to implement D2T. It can implement:

```text
D2T2 -> periodic telemetry
D2E  -> urgent geofence events
```

DJUA_SMS continues to accept legacy D2T messages for compatibility.

## 2. Wire grammar

Exactly four comma-separated fields:

```text
D2T2,DEV,PAYLOAD,AUTH
```

Where:

- `DEV` is the technical device id: `[A-Z0-9-]{1,32}`;
- `PAYLOAD` is exactly 60 packed bytes encoded as exactly 80 unpadded Base64URL characters;
- `AUTH` is the existing 11-character D2 HMAC tag, or `-` only in development mode.

Allowed wire characters remain:

```text
A-Z a-z 0-9 , - _
```

No concatenated SMS, no truncation and no UCS-2 fallback.

## 3. Size proof

A maximum device id has 32 characters.

```text
D2T2       4
commas     3
DEV       32
PAYLOAD   80
AUTH      11
----------------
TOTAL    130 septets
```

Therefore the authenticated worst case is:

```text
130 <= 160 GSM-7 septets
```

D2T2 keeps 30 septets of headroom while carrying the additional DC-load block.

## 4. Payload bit encoding

The payload is exactly 480 bits = 60 bytes.

Rules:

- fields are appended from bit 0 to bit 479 in the order below;
- bit 0 is the most-significant bit of the first payload byte;
- unsigned fields are ordinary fixed-width unsigned integers;
- signed fields use fixed-width two's-complement;
- bytes are Base64URL encoded without `=` padding;
- the final six reserved bits must be zero.

| Field | Bits | Width | Encoding |
| --- | ---: | ---: | --- |
| SEQ | 0..31 | 32 | unsigned |
| RTC | 32..63 | 32 | unsigned |
| UP | 64..95 | 32 | unsigned |
| INT | 96..112 | 17 | unsigned |
| LAT | 113..137 | 25 | signed two's-complement |
| LON | 138..163 | 26 | signed two's-complement |
| BV | 164..178 | 15 | unsigned |
| BI | 179..197 | 19 | signed two's-complement |
| BP | 198..214 | 17 | signed two's-complement |
| SV | 215..231 | 17 | unsigned |
| SI | 232..249 | 18 | signed two's-complement |
| SP | 250..267 | 18 | signed two's-complement |
| SE | 268..293 | 26 | signed two's-complement |
| AV | 294..305 | 12 | unsigned |
| AI | 306..317 | 12 | unsigned |
| AP | 318..335 | 18 | signed two's-complement |
| AS | 336..352 | 17 | unsigned |
| AE | 353..378 | 26 | signed two's-complement |
| DV | 379..395 | 17 | unsigned |
| DI | 396..413 | 18 | signed two's-complement |
| DP | 414..431 | 18 | signed two's-complement |
| DE | 432..457 | 26 | signed two's-complement |
| FLAGS | 458..473 | 16 | unsigned |
| RESERVED | 474..479 | 6 | must be zero |

## 5. Units, resolution and ranges

D2T2 keeps the existing D2T resolutions and ranges. DC load uses an envelope chosen to cover a 0–100 V / +/-100 A / +/-10 kW channel.

| Field | Resolution | Allowed decoded range |
| --- | --- | --- |
| SEQ | integer | 1..4294967295 |
| RTC | Unix UTC seconds | 2000-01-01..2099-12-31, or absent by flag |
| UP | 1 ms | 0..4294967295 ms |
| INT | 1 s | 10..86400 s |
| LAT | 1e-5 degree | -90..+90 |
| LON | 1e-5 degree | -180..+180 |
| BV | 1 mV | 0..32 V |
| BI | 1 mA | -200..+200 A |
| BP | 0.1 W | -6400..+6400 W |
| SV | 1 mV | 0..100 V |
| SI | 1 mA | -100..+100 A |
| SP | 0.1 W | -10000..+10000 W |
| SE | 0.01 Wh | -240000..+240000 Wh |
| AV | 0.1 V RMS | 0..400 V |
| AI | 0.01 A RMS | 0..30 A |
| AP | 0.1 W | -12000..+12000 W |
| AS | 0.1 VA | 0..12000 VA |
| AE | 0.01 Wh | -288000..+288000 Wh |
| DV | 1 mV | 0..100 V |
| DI | 1 mA | -100..+100 A |
| DP | 0.1 W | -10000..+10000 W |
| DE | 0.01 Wh | -240000..+240000 Wh |

These are protocol representation limits, not electrical safety limits.

## 6. Sign convention

The existing conventions are retained:

```text
battery:
  + current/power = charge into battery
  - current/power = discharge

solar:
  + power/energy = production toward the system
  - power/energy = reverse flow

AC load:
  + active power/energy = consumption
  - active power/energy = export/return
```

New DC-load convention:

```text
DC load:
  + current/power/energy = consumption by the DC load
  - current/power/energy = reverse/regenerative flow toward the source
```

## 7. Flags

FLAGS occupies 16 bits. D2T2 v1 defines bits 0..8 only. Bits 9..15 must be zero.

```text
bit0 RTC_VALID
bit1 GPS_VALID
bit2 BATTERY_VALID
bit3 SOLAR_VALID
bit4 AC_VALID
bit5 SOLAR_ENERGY_COMPLETE
bit6 AC_ENERGY_COMPLETE
bit7 DC_LOAD_VALID
bit8 DC_LOAD_ENERGY_COMPLETE
bits9..15 RESERVED = 0
```

Dependencies:

```text
SOLAR_ENERGY_COMPLETE -> SOLAR_VALID
AC_ENERGY_COMPLETE    -> AC_VALID
DC_LOAD_ENERGY_COMPLETE -> DC_LOAD_VALID
```

## 8. Canonical absence

D2T used the text token `-` for unavailable values. Packed D2T2 instead uses flags.

When a validity/completeness bit is zero, every packed numeric slot belonging only to that flag must be binary zero.

Examples:

```text
GPS_VALID=0
-> LAT raw = 0
-> LON raw = 0

DC_LOAD_VALID=0
-> DV raw = 0
-> DI raw = 0
-> DP raw = 0

DC_LOAD_ENERGY_COMPLETE=0
-> DE raw = 0
```

This zeroing rule is canonical encoding. It prevents multiple byte representations of the same logical message.

A valid measured zero is still distinguishable because its validity bit is one.

## 9. Energy completeness

D2T2 keeps the D2 energy semantics:

```text
ENERGY_SAMPLE_PERIOD = 10 s
ENERGY_MAX_GAP       = 20 s
ELECTRICAL_MAX_AGE   = 20 s
GPS_MAX_AGE          = 5 s
nominal telemetry interval = 1800 s, configurable
```

Solar, AC and DC-load interval energy use timestamped trapezoidal integration:

```text
dE_Wh = ((P0 + P1) / 2) * dt / 3600
```

A segment is integrated only when both samples are valid and:

```text
0 < dt <= 20 s
```

An invalid sample or a gap greater than 20 s makes that channel's energy incomplete for the telemetry interval. Partial missing energy is not extrapolated.

The new `DC_LOAD_ENERGY_COMPLETE` follows the same rule as the existing solar and AC completeness flags.

## 10. Sequence and identity

D2T2 does not introduce another sequence counter.

One device uses one global uint32 sequence namespace shared by:

```text
D2T
D2T2
D2E
```

For a new firmware that no longer emits D2T, the practical sequence is simply shared by D2T2 and D2E.

The gateway message id remains:

```text
D2:<device_id>:<SEQ_BASE36>
```

Therefore reuse of the same sequence by D2T and D2T2 for one device is an explicit `MESSAGE_ID_CONFLICT`, not two valid messages.

## 11. Authentication

D2T2 reuses D2 security exactly.

Signed ASCII bytes:

```text
D2T2,DEV,PAYLOAD
```

No final comma, no CR/LF and no whitespace normalization.

```text
digest = HMAC-SHA-256(device_key, signed_bytes)
tag_bytes = digest[0:8]
AUTH = base64url(tag_bytes) without "="
```

AUTH is exactly 11 characters.

Development mode may use:

```text
AUTH=-
```

Production mode requires:

- valid HMAC;
- configured 32-byte device key;
- sender in canonical E.164 format;
- configured sender-to-device binding.

A present but incorrect HMAC is rejected even in development mode.

## 12. MQTT/backend mapping

D2T2 uses the same telemetry topic as D2T:

```text
djua/test/<device_id>/telemetry
```

DJUA_SMS decodes the compact payload before MQTT. The backend never needs to understand the packed bytes.

The D2T2 JSON keeps all D2T business groups and adds `dc_load`:

```json
{
  "protocol": "D2T2",
  "message_id": "D2:DJUA-KIN-000001:9IX",
  "sequence": 12345,
  "kit_id": "DJUA-KIN-000001",
  "uptime_ms": 123456789,
  "timestamp_ms": 123456789,
  "interval_seconds": 1800,
  "latitude": -4.3251,
  "longitude": 15.3222,
  "battery": {
    "voltage_v": 12.4,
    "current_a": 0.5,
    "power_w": 6.2
  },
  "solar": {
    "voltage_v": 18.2,
    "current_a": 1.23,
    "power_w": 22.4,
    "energy_interval_wh": 11.2
  },
  "ac_load": {
    "voltage_v": 230.1,
    "current_a": 1.25,
    "active_power_w": 244.5,
    "apparent_power_va": 287.6,
    "energy_interval_wh": 122.25
  },
  "dc_load": {
    "voltage_v": 12.35,
    "current_a": 3.2,
    "power_w": 39.5,
    "energy_interval_wh": 19.76
  }
}
```

The payload also contains `gateway_received_at`, `validity`, `auth_status`, and `timestamp/timezone` when RTC is valid.

Unavailable D2T2 measurements become JSON `null`; a valid measured zero remains numeric zero.

## 13. Typical conformance vector

Public test key, tests only:

```text
000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F
```

Typical authenticated SMS:

```text
D2T2,DJUA-KIN-000001,AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_A,rHcRllcP4gs
```

Length:

```text
113 GSM-7 septets
```

It decodes, among the other existing measurements, to:

```text
DC voltage = 12.35 V
DC current = 3.2 A
DC power   = 39.5 W
DC energy  = 19.76 Wh
```

## 14. Maximum conformance vector

```text
D2T2,DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD,______SGVv______qMBdqvAu1XgPoBPLAgwBhqCeWCeWCkcoA-gu4itA6mBJEYAYagnlgnlgpHKAAH_A,OFXyFxdsTns
```

Length:

```text
130 GSM-7 septets
```

Machine-readable vectors are in:

```text
tests/vectors/d2t2_conformance.json
```

## 15. Gateway compatibility

The gateway dispatch is:

```text
D1,   -> historical D1
D2T,  -> legacy D2 telemetry
D2T2, -> compact telemetry + DC load
D2E,  -> urgent event
other -> INVALID
```

D2T2 reuses the existing durable chain:

```text
SIM868
-> raw SMS persisted in SQLite
-> D2T2 parse/validate/security
-> message-id dedupe/conflict handling
-> persistent MQTT outbox
-> MQTT QoS 1
```

No SQLite schema migration is required because the existing D2 metadata columns and generic outbox already store D2T2.

## 16. Compatibility and migration

D2T remains accepted and unchanged.

```text
old transmitter -> D2T  -> DJUA_SMS -> telemetry topic
new transmitter -> D2T2 -> DJUA_SMS -> telemetry topic
```

A future new transmitter may be implemented from this document without implementing the legacy D2T encoder.

D2E remains unchanged.

## 17. Validation status

At the time this contract is added:

```text
D2T2 codec/parser/security mapping : implemented in DJUA_SMS
D2T2 SQLite/outbox path            : implemented
D2T2 simulated GSM/MQTT tests      : covered by automated tests
D2T2 real transmitter SMS          : not yet validated
D2T2 real backend compatibility    : not yet validated
DJUA transmitter firmware          : not modified
```

Do not claim hardware or backend end-to-end validation until those tests are actually performed.
