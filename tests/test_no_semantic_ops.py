"""V4: only the five v2 operators exist; no fuzzy or legacy matching remains."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.pcs.judge import ALLOWED_OPERATORS
from aiinvite.pcs.probes import V2_OPERATORS, load_all_probes

JUDGE_SOURCE = ROOT / "aiinvite/pcs" / "judge.py"
PROBES_SOURCE = ROOT / "aiinvite/pcs" / "probes.py"
LEGACY_TOKENS = (
    "must_not_apologize",
    "max_agreement_shifts",
    "ask_before",
    "contains_any_of",
    "sequencematcher",
    "difflib",
    "rapidfuzz",
)


class TestNoSemanticOps(unittest.TestCase):
    def test_allowed_operator_set_is_exactly_v2(self) -> None:
        """V4: the judge's whitelist equals the v2 operator tuple."""
        print(f"V4 allowed={ALLOWED_OPERATORS} v2={V2_OPERATORS}")
        self.assertEqual(set(ALLOWED_OPERATORS), set(V2_OPERATORS))
        self.assertEqual(len(ALLOWED_OPERATORS), 5)

    def test_source_has_no_legacy_operators(self) -> None:
        """V4: judge.py and probes.py contain no legacy or fuzzy matching."""
        found = []
        for name, path in (("judge.py", JUDGE_SOURCE), ("probes.py", PROBES_SOURCE)):
            text = path.read_text(encoding="utf-8").lower()
            for token in LEGACY_TOKENS:
                if token in text:
                    found.append((name, token))
        print(f"V4 legacy tokens={found}")
        self.assertEqual(found, [])

    def test_every_probe_uses_a_whitelisted_operator(self) -> None:
        """V4: no probe can smuggle an operator outside the v2 list."""
        probes = load_all_probes()
        unknown = sorted({
            probe.expect.op for probe in probes
            if probe.expect.op not in V2_OPERATORS
        })
        print(f"V4 probes={len(probes)} unknown_ops={unknown}")
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
