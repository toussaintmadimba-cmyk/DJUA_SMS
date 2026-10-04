import unittest

from djua_sms_gateway.protocol.d2 import (
    D2AuthStatus,
    D2ProtocolError,
    calculate_hmac_tag,
    encode_base36,
    gsm7_septet_count,
    normalize_d2_to_backend,
    parse_d2,
    verify_d2_security,
)
from djua_sms_gateway.protocol.dispatch import detect_protocol


TEST_KEY = bytes.fromhex(
    "000102030405060708090A0B0C0D0E0F"
    "101112131415161718191A1B1C1D1E1F"
)

D2T_TYPICAL = (
    "D2T,DJUA-KIN-000001,9IX,TM14E0,21I3V9,1E0,"
    "-99Q6,WU9O,9KG,DW,1Q,E1K,Y6,68,V4,1RX,3H,1VX,27W,9FL,3J,"
    "e0kwQvzx35g"
)

D2T_MAX = (
    "D2T,DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD,1Z141Z3,1VUHMNZ,"
    "1Z141Z3,1UO0,-5CWG0,-APSW0,OOW,-4ABK,-1DDS,255S,-255S,"
    "-255S,-EAEIO,334,2BC,-2KLC,2KLC,-H5A80,3J,B087JbAshro"
)


def flags36(value: int) -> str:
    return encode_base36(value).rjust(2, "0")


def make_d2t(flags: int) -> str:
    rtc = "TM14E0" if flags & 0x01 else "-"
    lat, lon = ("-99Q6", "WU9O") if flags & 0x02 else ("-", "-")
    battery = ("9KG", "DW", "1Q") if flags & 0x04 else ("-", "-", "-")
    solar = ("E1K", "Y6", "68") if flags & 0x08 else ("-", "-", "-")
    solar_energy = "V4" if flags & 0x20 else "-"
    ac = ("1RX", "3H", "1VX", "27W") if flags & 0x10 else ("-", "-", "-", "-")
    ac_energy = "9FL" if flags & 0x40 else "-"
    return ",".join(
        [
            "D2T",
            "DJUA-KIN-000001",
            "1",
            rtc,
            "0",
            "A",
            lat,
            lon,
            *battery,
            *solar,
            solar_energy,
            *ac,
            ac_energy,
            flags36(flags),
            "-",
        ]
    )


def make_d2e(flags: int) -> str:
    rtc = "TM14E0" if flags & 0x01 else "-"
    lat, lon = ("-99Q6", "WU9O") if flags & 0x02 else ("-", "-")
    distance = "2N" if flags & 0x04 else "-"
    return ",".join(
        [
            "D2E",
            "DJUA-KIN-000001",
            "1",
            rtc,
            "0",
            "GX",
            lat,
            lon,
            distance,
            flags36(flags),
            "-",
        ]
    )


class D2ProtocolTests(unittest.TestCase):
    def test_dispatch_is_explicit_and_preserves_d1(self):
        self.assertEqual(detect_protocol("D1,x"), "D1")
        self.assertEqual(detect_protocol("D2T,x"), "D2T")
        self.assertEqual(detect_protocol("D2E,x"), "D2E")
        with self.assertRaises(D2ProtocolError):
            detect_protocol("BONJOUR")

    def test_known_hmac_and_exact_sizes(self):
        for raw, expected_size in (
            (D2T_TYPICAL, 109),
            (D2T_MAX, 160),
        ):
            message = parse_d2(raw)
            self.assertEqual(gsm7_septet_count(raw), expected_size)
            self.assertEqual(
                calculate_hmac_tag(message.signed_part, TEST_KEY),
                message.auth,
            )

    def test_all_d2t_flag_combinations(self):
        for flags in range(128):
            invalid = (
                bool(flags & 0x20 and not flags & 0x08)
                or bool(flags & 0x40 and not flags & 0x10)
            )
            if invalid:
                with self.assertRaises(D2ProtocolError):
                    parse_d2(make_d2t(flags))
            else:
                self.assertEqual(parse_d2(make_d2t(flags)).flags, flags)

    def test_all_d2e_flag_combinations(self):
        for flags in range(8):
            invalid = bool(flags & 0x04 and not flags & 0x02)
            if invalid:
                with self.assertRaises(D2ProtocolError):
                    parse_d2(make_d2e(flags))
            else:
                self.assertEqual(parse_d2(make_d2e(flags)).flags, flags)

    def test_gsm_extension_count_is_real_but_extension_is_not_d2(self):
        self.assertEqual(gsm7_septet_count("^"), 2)
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2(D2T_TYPICAL.replace("DJUA", "DJ^A"))
        self.assertEqual(context.exception.code, "D2_CHARSET")

    def test_true_non_gsm7_character_is_rejected(self):
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2(D2T_TYPICAL.replace("DJUA", "DЖUA"))
        self.assertEqual(context.exception.code, "NON_GSM7")

    def test_nan_and_infinity_spellings_are_not_d2_numeric_syntax(self):
        for token in ("NaN", "Infinity"):
            with self.subTest(token=token):
                with self.assertRaises(D2ProtocolError):
                    parse_d2(
                        D2T_TYPICAL.replace(",9KG,", f",{token},")
                    )

    def test_noncanonical_base36_is_rejected(self):
        with self.assertRaises(D2ProtocolError) as context:
            parse_d2(D2T_TYPICAL.replace(",9IX,", ",09IX,"))
        self.assertEqual(context.exception.code, "NON_CANONICAL_BASE36")

        with self.assertRaises(D2ProtocolError) as context:
            parse_d2(D2T_TYPICAL.replace(",-99Q6,", ",-0,"))
        self.assertEqual(context.exception.code, "NON_CANONICAL_BASE36")

    def test_zero_is_distinct_from_absent(self):
        zero = (
            "D2T,DJUA-KIN-000001,1,-,0,A,-,-,-,-,-,"
            "0,0,0,0,-,-,-,-,-,14,-"
        )
        message = parse_d2(zero)
        payload = normalize_d2_to_backend(
            message,
            gateway_received_at="2026-01-01T00:00:00+00:00",
            auth_status=D2AuthStatus.NOT_VERIFIED,
        )
        self.assertEqual(payload["solar"]["power_w"], 0.0)
        self.assertEqual(payload["solar"]["energy_interval_wh"], 0.0)

        absent = parse_d2(
            "D2T,DJUA-KIN-000001,1,-,0,A,-,-,-,-,-,"
            "-,-,-,-,-,-,-,-,-,00,-"
        )
        payload = normalize_d2_to_backend(
            absent,
            gateway_received_at="2026-01-01T00:00:00+00:00",
            auth_status=D2AuthStatus.NOT_VERIFIED,
        )
        self.assertIsNone(payload["solar"]["power_w"])
        self.assertIsNone(payload["solar"]["energy_interval_wh"])

    def test_security_modes_and_sender_binding(self):
        message = parse_d2(D2T_TYPICAL)
        self.assertEqual(
            verify_d2_security(
                message,
                mode="production",
                key=TEST_KEY,
                sender="+243810000001",
                allowed_senders=["+243810000001"],
            ),
            D2AuthStatus.VERIFIED,
        )

        with self.assertRaises(D2ProtocolError) as context:
            verify_d2_security(
                message,
                mode="production",
                key=TEST_KEY,
                sender="+243899999999",
                allowed_senders=["+243810000001"],
            )
        self.assertEqual(
            context.exception.code,
            "SENDER_DEVICE_MISMATCH",
        )

        development = parse_d2(
            "D2E,DJUA-KIN-000001,A,-,0,GX,-,-,-,00,-"
        )
        self.assertEqual(
            verify_d2_security(
                development,
                mode="development",
                key=None,
            ),
            D2AuthStatus.NOT_VERIFIED,
        )

        with self.assertRaises(D2ProtocolError) as context:
            verify_d2_security(
                development,
                mode="production",
                key=TEST_KEY,
                sender="+243810000001",
                allowed_senders=["+243810000001"],
            )
        self.assertEqual(context.exception.code, "AUTH_REQUIRED")

    def test_present_but_bad_hmac_is_rejected_in_development_too(self):
        bad = parse_d2(D2T_TYPICAL[:-1] + "A")
        with self.assertRaises(D2ProtocolError) as context:
            verify_d2_security(
                bad,
                mode="development",
                key=TEST_KEY,
            )
        self.assertEqual(context.exception.code, "AUTH_INVALID")


if __name__ == "__main__":
    unittest.main()
