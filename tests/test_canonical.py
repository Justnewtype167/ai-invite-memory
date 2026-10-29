"""T1/T2: canonical JSON golden vectors and rejection cases."""

from __future__ import annotations

import unittest

from jian.canonical import dumps
from jian.errors import E_NOT_CANONICAL, JianError


class CanonicalVectorsTest(unittest.TestCase):
    """T1: exact byte output for ten golden vectors."""

    def test_canonical_vectors(self) -> None:
        vectors = [
            ({}, b"{}"),
            ({"b": 1, "a": 2}, b'{"a":2,"b":1}'),
            ({"s": "a/b"}, b'{"s":"a/b"}'),
            ({"s": "cafe\u0301"}, b'{"s":"caf\xc3\xa9"}'),
            ({"s": "中文"}, b'{"s":"\xe4\xb8\xad\xe6\x96\x87"}'),
            ({"s": "a\u0001b"}, b'{"s":"a\\u0001b"}'),
            ({"s": "q\"b\\"}, b'{"s":"q\\"b\\\\"}'),
            ({"n": 9007199254740991}, b'{"n":9007199254740991}'),
            ({"n": -9007199254740991}, b'{"n":-9007199254740991}'),
            (
                {"z": None, "a": [True, False], "m": {"y": 0, "x": "s"}},
                b'{"a":[true,false],"m":{"x":"s","y":0},"z":null}',
            ),
        ]
        for index, (value, expected) in enumerate(vectors, start=1):
            with self.subTest(vector=index):
                self.assertEqual(dumps(value), expected)

    def test_dumps_returns_bytes_without_newline(self) -> None:
        result = dumps({"a": 1})
        self.assertIsInstance(result, bytes)
        self.assertFalse(result.endswith(b"\n"))

    def test_control_character_uses_lowercase_hex(self) -> None:
        self.assertEqual(dumps({"s": "\u001f"}), b'{"s":"\\u001f"}')

    def test_nfc_is_applied_before_sorting(self) -> None:
        self.assertEqual(dumps({"s": "e\u0301"}), b'{"s":"\xc3\xa9"}')


class CanonicalRejectsTest(unittest.TestCase):
    """T2: non-canonical inputs raise E_NOT_CANONICAL."""

    def test_canonical_rejects(self) -> None:
        bad_values = [
            1.5,
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.0,
            {"s": "\ud800"},
            [1],
            "text",
            1,
            None,
            2 ** 53,
            -(2 ** 53),
            {"nested": {"value": 0.5}},
        ]
        for value in bad_values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(JianError) as context:
                    dumps(value)
                self.assertEqual(context.exception.code, E_NOT_CANONICAL)

    def test_non_string_key_rejected(self) -> None:
        with self.assertRaises(JianError) as context:
            dumps({1: "x"})
        self.assertEqual(context.exception.code, E_NOT_CANONICAL)


if __name__ == "__main__":
    unittest.main()
