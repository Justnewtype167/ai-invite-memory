"""D1-D5: the demo engine keeps the four promises without a window."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.demo.engine import DemoEngine, EngineError, ollama_caller


class FakeModel:
    """A caller that answers deterministically and records the prompts."""

    def __init__(self, reply="在的。"):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt, model):
        self.prompts.append((model, prompt))
        return self.reply


class TestDemoEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="demo_test_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        self.model = FakeModel()
        self.engine = DemoEngine(self.store, model="qwen3.5:9b", caller=self.model)

    def test_turn_records_both_sides(self) -> None:
        """D1: one send appends the user turn and the gated reply."""
        turn = self.engine.send("我叫老周")
        self.assertFalse(turn.refused)
        self.assertEqual(self.engine.verify(), 2)
        self.assertEqual([t.role for t in self.engine.turns], ["user", "assistant"])

    def test_model_switch_keeps_identity(self) -> None:
        """D2: switching the model changes no evidence and no kid."""
        self.engine.send("我叫老周")
        before = self.engine.snapshot()
        self.engine.switch_model("glm4:9b")
        after = self.engine.snapshot()
        self.assertEqual(before["kid"], after["kid"])
        self.assertEqual(before["events"], after["events"])
        self.assertEqual(after["model"], "glm4:9b")
        self.engine.send("在吗")
        self.assertEqual(self.model.prompts[-1][0], "glm4:9b")

    def test_snapshot_shows_the_card(self) -> None:
        """D3: the vault panel reads a real user card out of evidence."""
        self.engine.send("我叫老周")
        snap = self.engine.snapshot()
        self.assertIn("老周", snap["card"])
        self.assertTrue(snap["kid"])

    def test_export_import_round_trip(self) -> None:
        """D4: the carrier survives a copy to another folder."""
        self.engine.send("我叫老周")
        kid = self.engine.snapshot()["kid"]
        carrier = self.root / "carrier"
        self.engine.export_to(carrier)
        other = DemoEngine(self.root / "other", caller=self.model)
        other.import_from(carrier)
        self.assertEqual(other.snapshot()["kid"], kid)

    def test_empty_input_is_refused(self) -> None:
        """D5: an empty send is a clean error, not a crash."""
        with self.assertRaises(EngineError):
            self.engine.send("   ")

    def test_unreachable_ollama_is_a_demo_error(self) -> None:
        """D5: a dead endpoint surfaces as EngineError with the URL."""
        with self.assertRaises(EngineError) as caught:
            ollama_caller("hi", "no-such-model", timeout=1)
        self.assertIn("11434", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
