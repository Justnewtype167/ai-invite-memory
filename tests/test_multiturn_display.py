"""W4: multi-turn rows show the whole dialogue and end on the last user turn."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jian_pcs.probes import load_hard_probes


def _builder():
    path = ROOT / "tools" / "build_human_eval.py"
    spec = importlib.util.spec_from_file_location("build_human_eval_w4", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMultiturnDisplay(unittest.TestCase):
    def test_every_user_turn_is_visible_and_last_turn_is_final(self) -> None:
        """W4: the input column keeps every turn, one line each, last turn last."""
        dialogue_input = _builder().dialogue_input
        probes = load_hard_probes()
        problems = []
        for probe in probes:
            lines = dialogue_input(probe).split("\n")
            if len(lines) != len(probe.turns):
                problems.append((probe.probe_id, "line-count"))
                continue
            for turn, line in zip(probe.turns, lines):
                if line != f"用户：{turn}":
                    problems.append((probe.probe_id, "turn-missing"))
                    break
            if not lines[-1].endswith(f"用户：{probe.turns[-1]}"):
                problems.append((probe.probe_id, "last-turn-missing"))
        print(f"W4 probes={len(probes)} problems={problems}")
        self.assertEqual(len(probes), 18)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
