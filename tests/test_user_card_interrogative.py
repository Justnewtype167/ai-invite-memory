# -*- coding: utf-8 -*-
import pathlib, sys, tempfile, shutil, unittest
ROOT = pathlib.Path(r"D:\projects\Memory"); sys.path.insert(0, str(ROOT))
from aiinvite.capsule import init_store, append_event, seal_store
from aiinvite.kernel.kernel import Policy
import aiinvite.persona as JP

class TestInterrogative(unittest.TestCase):
    def _card(self, text):
        root = pathlib.Path(tempfile.mkdtemp(prefix="interr_")); self.addCleanup(shutil.rmtree, root, True)
        s = root / "m"; init_store(s)
        append_event(s, "user", text, "2026-11-01T09:00:00+08:00"); seal_store(s)
        v = JP.build_persona_view(s, policy=Policy(now="2026-11-01T10:00:00+08:00"))
        return v.user_card.to_payload()["address"].get("call") or ""

    def test_question_is_not_a_name(self):
        for q in ("我叫什么名字\uff1f", "我的名字是什么", "我叫谁"):
            self.assertEqual(self._card(q), "", q)

    def test_real_intro_still_works(self):
        self.assertEqual(self._card("我叫老周"), "老周")

if __name__ == "__main__":
    unittest.main()