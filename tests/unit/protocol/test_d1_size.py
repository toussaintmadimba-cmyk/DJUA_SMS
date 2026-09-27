import string
import unittest

from tests.fixtures.d1_messages import D1_VALID_ALL, SIZE_MESSAGES

GSM7_SAFE_FOR_D1 = set(string.ascii_letters + string.digits + ".,-_+")


class D1SizeTests(unittest.TestCase):
    def test_documented_no_auth_example_is_149_characters(self) -> None:
        self.assertEqual(len(D1_VALID_ALL), 149)

    def test_typical_compact_auth_example_is_159_characters(self) -> None:
        self.assertEqual(len(SIZE_MESSAGES["typical"]), 159)
        self.assertLessEqual(len(SIZE_MESSAGES["typical"]), 160)

    def test_fixture_lengths_expose_overflow_risk(self) -> None:
        expected = {
            "minimal": 48,
            "typical": 159,
            "large_values": 189,
            "negative_values": 167,
            "maximum_reasonable": 224,
        }
        actual = {name: len(message) for name, message in SIZE_MESSAGES.items()}
        self.assertEqual(actual, expected)

    def test_realistic_large_cases_can_exceed_one_sms(self) -> None:
        self.assertGreater(len(SIZE_MESSAGES["large_values"]), 160)
        self.assertGreater(len(SIZE_MESSAGES["negative_values"]), 160)
        self.assertGreater(len(SIZE_MESSAGES["maximum_reasonable"]), 160)

    def test_size_fixtures_use_only_d1_safe_gsm7_characters(self) -> None:
        for name, message in SIZE_MESSAGES.items():
            with self.subTest(name=name):
                self.assertTrue(message.isascii())
                self.assertFalse(any(char.isspace() for char in message))
                self.assertTrue(set(message) <= GSM7_SAFE_FOR_D1)


if __name__ == "__main__":
    unittest.main()
