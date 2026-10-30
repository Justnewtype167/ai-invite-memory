"""Q1: proposal provenance fields round-trip and out-of-range values are refused."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian.errors import E_SCHEMA, JianError
from jian.event import Event, new_event, parse_event
from jian_kernel.proposer import record_proposal

STAMP = "2026-10-29T02:00:00Z"
GENESIS = "0" * 64


def _proposal_event(**overrides: object) -> Event:
    kwargs: dict[str, object] = {
        "type": "proposal",
        "target": "self.conduct",
        "model": "qwen3.5:9b",
        "prompt_sha": "ab12cd34",
    }
    kwargs.update(overrides)
    return new_event(
        1, "seg-0001", STAMP, None, "收到负面经历时只确认，不评价情绪",
        GENESIS, **kwargs,
    )


class TestProposalFields(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_q1_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        kn_fixtures.write_store(self.root, kn_fixtures.chat_turns(10))

    def _last_line(self) -> dict[str, object]:
        path = self.root / "evidence" / "seg-0001.jsonl"
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        return json.loads(lines[-1])

    def test_four_fields_round_trip(self) -> None:
        """Q1: quant / weights_sha / temp_milli / seed survive the chain."""
        event = record_proposal(
            self.root, "self.conduct", "收到负面经历时只确认，不评价情绪",
            "qwen3.5:9b", "ab12cd34", STAMP,
            quant="Q4_K_M", weights_sha="9f8e7d6c",
            temp_milli=0, seed=0,
        )
        parsed = parse_event(self._last_line())
        print(
            f"Q1 quant={parsed.quant} weights={parsed.weights_sha} "
            f"temp={parsed.temp_milli} seed={parsed.seed}"
        )
        self.assertEqual(event.quant, "Q4_K_M")
        self.assertEqual(event.weights_sha, "9f8e7d6c")
        self.assertEqual(event.temp_milli, 0)
        self.assertEqual(event.seed, 0)
        self.assertEqual(parsed.quant, "Q4_K_M")
        self.assertEqual(parsed.weights_sha, "9f8e7d6c")
        self.assertEqual(parsed.temp_milli, 0)
        self.assertEqual(parsed.seed, 0)

    def test_out_of_range_values_are_schema(self) -> None:
        """Q1: temp_milli range, negative seed and long quant raise E_SCHEMA."""
        cases: list[tuple[str, dict[str, object]]] = [
            ("temp high", {"temp_milli": 2001}),
            ("temp low", {"temp_milli": -1}),
            ("temp float", {"temp_milli": 1.5}),
            ("seed negative", {"seed": -1}),
            ("seed too big", {"seed": 2 ** 31}),
            ("quant long", {"quant": "Q" * 33}),
            ("weights not hex", {"weights_sha": "zz"}),
        ]
        for label, overrides in cases:
            with self.assertRaises(JianError) as caught:
                _proposal_event(**overrides)
            print(f"Q1 {label} -> {caught.exception.code}")
            self.assertEqual(caught.exception.code, E_SCHEMA)

    def test_parse_rejects_bad_stored_values(self) -> None:
        """Q1: a stored event with bad temp/seed is E_SCHEMA on read."""
        record_proposal(
            self.root, "self.conduct", "只确认不评价", "m", "ab12cd34", STAMP,
            temp_milli=0, seed=1,
        )
        base = self._last_line()
        for name, value in (("temp_milli", 2500), ("seed", -3)):
            broken = dict(base)
            broken[name] = value
            with self.assertRaises(JianError) as caught:
                parse_event(broken)
            print(f"Q1 stored {name}={value} -> {caught.exception.code}")
            self.assertEqual(caught.exception.code, E_SCHEMA)

    def test_temperature_field_is_rejected(self) -> None:
        """Q1: a float ``temperature`` field is not part of the schema."""
        record_proposal(
            self.root, "self.conduct", "只确认不评价", "m", "ab12cd34", STAMP
        )
        broken = self._last_line()
        broken["temperature"] = 0.7
        with self.assertRaises(JianError) as caught:
            parse_event(broken)
        print(f"Q1 temperature field -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_SCHEMA)


if __name__ == "__main__":
    unittest.main()
