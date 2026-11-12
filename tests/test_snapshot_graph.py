"""P4b: the snapshot keeps its graph in a sidecar file, without changing kid."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.errors import E_KN_SNAPSHOT, KernelError
from aiinvite.kernel.incremental import compile_kernel_incremental
from aiinvite.kernel.kernel import Policy
from aiinvite.kernel.snapshot import (
    DIGEST_PREFIX,
    GRAPH_FILE,
    SNAPSHOT_FILE,
    digest_of,
)

NOW = "2026-10-29T10:00:00+08:00"


class TestSnapshotGraph(unittest.TestCase):
    def _store(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_graph_"))
        self.addCleanup(shutil.rmtree, root, True)
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(12))
        return root

    def _compiled(self):
        root = self._store()
        kernel = compile_kernel_incremental(root, Policy(now=NOW))
        return root, kernel

    def _snapshot(self, root):
        return json.loads((root / "kernel" / SNAPSHOT_FILE).read_bytes())

    def test_graph_lives_in_its_own_file(self):
        """G1: the payload holds a digest, the bytes live in graph.json."""
        root, _kernel = self._compiled()
        data = self._snapshot(root)
        print("G1 keys=" + ",".join(sorted(data)))
        self.assertNotIn("graph", data)
        digest = data["graph_digest"]
        self.assertTrue(digest.startswith(DIGEST_PREFIX))
        raw = (root / "kernel" / GRAPH_FILE).read_bytes()
        self.assertEqual(DIGEST_PREFIX + hashlib.sha256(raw).hexdigest(), digest)
        graph = json.loads(raw)
        self.assertIn("edges", graph)
        self.assertIn("anchors", graph)

    def test_edited_graph_is_refused(self):
        """G2: a hand-edited graph no longer matches the snapshot digest."""
        root, _kernel = self._compiled()
        path = root / "kernel" / GRAPH_FILE
        graph = json.loads(path.read_bytes())
        graph["edges"] = graph["edges"][:-1]
        path.write_bytes(json.dumps(graph, ensure_ascii=False).encode("utf-8"))
        with self.assertRaises(KernelError) as caught:
            compile_kernel_incremental(root, Policy(now=NOW))
        print("G2 edited graph -> " + caught.exception.code)
        self.assertEqual(caught.exception.code, E_KN_SNAPSHOT)

    def test_missing_graph_is_refused(self):
        """G3: half a snapshot is refused instead of guessed."""
        root, _kernel = self._compiled()
        (root / "kernel" / GRAPH_FILE).unlink()
        with self.assertRaises(KernelError) as caught:
            compile_kernel_incremental(root, Policy(now=NOW))
        print("G3 missing graph -> " + caught.exception.code)
        self.assertEqual(caught.exception.code, E_KN_SNAPSHOT)

    def test_format_one_snapshot_still_loads(self):
        """G4: an inline v1 snapshot written by 0.40 loads with the same kid."""
        root, kernel = self._compiled()
        path = root / "kernel" / SNAPSHOT_FILE
        data = self._snapshot(root)
        graph = json.loads((root / "kernel" / GRAPH_FILE).read_bytes())
        legacy = {key: value for key, value in data.items() if key != "graph_digest"}
        legacy["format"] = 1
        legacy["graph"] = graph
        legacy.pop("digest")
        legacy["digest"] = digest_of(legacy)
        path.write_bytes(json.dumps(legacy, ensure_ascii=False).encode("utf-8"))
        (root / "kernel" / GRAPH_FILE).unlink()
        again = compile_kernel_incremental(root, Policy(now=NOW))
        print("G4 legacy kid=" + again.kid[:12])
        self.assertEqual(again.kid, kernel.kid)
        self.assertEqual(again.files(1), kernel.files(1))


if __name__ == "__main__":
    unittest.main()
