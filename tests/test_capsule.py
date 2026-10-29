"""T4-T8: tamper detection, missing segments, export determinism, roundtrip, verify modes."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from jian.capsule import (
    append_event,
    export_capsule,
    import_capsule,
    init_store,
    inspect_capsule,
    seal_store,
    verify_path,
)
from jian.cli import main
from jian.errors import (
    E_CHAIN_MISSING,
    E_HEADER_MISMATCH,
    E_IO,
    E_NOT_CANONICAL,
    E_SCHEMA,
    E_TAMPER,
    JianError,
)
from jian.event import GENESIS_PREV, new_event


def _stamp(index: int) -> str:
    minute = (index // 60) % 60
    second = index % 60
    return f"2026-10-29T06:{minute:02d}:{second:02d}Z"


def _make_store(store: Path, count: int, *, sealed: bool = True) -> None:
    init_store(store)
    for index in range(1, count + 1):
        role = "user" if index % 2 else "assistant"
        append_event(store, role, f"msg-{index:04d}", _stamp(index))
    if sealed:
        seal_store(store)


def _manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def _rewrite_zip(src: Path, dst: Path, mutate) -> None:
    with zipfile.ZipFile(src, "r") as archive:
        entries = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    entries = mutate(entries)
    with zipfile.ZipFile(dst, "w") as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])


class TamperTest(unittest.TestCase):
    """T4: tamper, escaped-slash and CRLF evidence are reported precisely."""

    def test_tamper_one_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 30)
            path = store / "evidence" / "seg-0001.jsonl"
            original = path.read_bytes()
            marker = b'"text":"msg-0005"'
            self.assertEqual(original.count(marker), 1)
            path.write_bytes(original.replace(marker, b'"text":"msg-0006"'))
            with self.assertRaises(JianError) as context:
                verify_path(store)
            self.assertEqual(context.exception.code, E_TAMPER)
            self.assertEqual(context.exception.event_id, "ev_000005")

    def test_noncanonical_slash_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            init_store(store)
            append_event(store, "user", "a/b", _stamp(1))
            seal_store(store)
            path = store / "evidence" / "seg-0001.jsonl"
            original = path.read_bytes()
            self.assertEqual(original.count(b'"text":"a/b"'), 1)
            path.write_bytes(original.replace(b'"text":"a/b"', b'"text":"a\\/b"'))
            with self.assertRaises(JianError) as context:
                verify_path(store)
            self.assertEqual(context.exception.code, E_NOT_CANONICAL)

    def test_noncanonical_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 5)
            path = store / "evidence" / "seg-0001.jsonl"
            original = path.read_bytes()
            marker = b',"type":"turn","v":1}\n'
            self.assertEqual(original.count(marker), 5)
            path.write_bytes(original.replace(marker, b',"type":"turn","v":1}\r\n', 1))
            with self.assertRaises(JianError) as context:
                verify_path(store)
            self.assertEqual(context.exception.code, E_NOT_CANONICAL)


class MissingSegmentTest(unittest.TestCase):
    """T5: deleting a segment is reported as E_CHAIN_MISSING."""

    def test_missing_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 250)
            (store / "evidence" / "seg-0002.jsonl").unlink()
            with self.assertRaises(JianError) as context:
                verify_path(store)
            self.assertEqual(context.exception.code, E_CHAIN_MISSING)


class ZipDeterminismTest(unittest.TestCase):
    """T6: identical bytes on repeated export, stable created, sealed required."""

    def test_zip_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 20)
            created_before = _manifest(store)["created"]
            first = Path(tmp) / "a.aiem"
            second = Path(tmp) / "b.aiem"
            export_capsule(store, first)
            export_capsule(store, second)
            digest_first = hashlib.sha256(first.read_bytes()).hexdigest()
            digest_second = hashlib.sha256(second.read_bytes()).hexdigest()
            self.assertEqual(digest_first, digest_second)
            self.assertEqual(_manifest(store)["created"], created_before)
            with zipfile.ZipFile(first, "r") as archive:
                capsule_manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(capsule_manifest["created"], created_before)

            unsealed = Path(tmp) / "unsealed"
            _make_store(unsealed, 3, sealed=False)
            with self.assertRaises(JianError) as context:
                export_capsule(unsealed, Path(tmp) / "c.aiem")
            self.assertEqual(context.exception.code, E_SCHEMA)


def _build_big_store(store: Path, count: int) -> None:
    init_store(store)
    previous = GENESIS_PREV
    for segment in range(1, count // 100 + 1):
        episode = f"seg-{segment:04d}"
        lines = []
        for slot in range(100):
            sequence = (segment - 1) * 100 + slot + 1
            event = new_event(sequence, episode, _stamp(sequence), "user", f"msg-{sequence:05d}", previous)
            previous = event.hash
            lines.append(event.to_line())
        (store / "evidence" / f"{episode}.jsonl").write_bytes(b"".join(lines))
    seal_store(store)


class RoundtripPerfTest(unittest.TestCase):
    """T7: byte-identical roundtrip, preserved created, 10k verify without O(n^2).

    The 2s assertion only guards against quadratic regressions; the real
    target (<200ms) is reported by ``tools/bench.py`` and is not a test gate.
    """

    def test_roundtrip_and_perf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 30)
            first = Path(tmp) / "first.aiem"
            export_capsule(store, first)
            imported = Path(tmp) / "imported"
            import_capsule(first, imported)
            second = Path(tmp) / "second.aiem"
            export_capsule(imported, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first, "r") as archive:
                created_first = json.loads(archive.read("manifest.json"))["created"]
            with zipfile.ZipFile(second, "r") as archive:
                created_second = json.loads(archive.read("manifest.json"))["created"]
            self.assertEqual(created_first, created_second)

            big = Path(tmp) / "big"
            _build_big_store(big, 10000)
            start = time.perf_counter()
            result = verify_path(big)
            elapsed = time.perf_counter() - start
            self.assertEqual(result.events, 10000)
            self.assertEqual(result.segments, 100)
            self.assertLess(elapsed, 2.0)


class VerifyModesTest(unittest.TestCase):
    """T8: directory state reporting and capsule header mismatches."""

    def test_verify_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unsealed = Path(tmp) / "unsealed"
            _make_store(unsealed, 5, sealed=False)
            result = verify_path(unsealed)
            self.assertEqual(result.state, "unsealed")
            output = self._run(["verify", str(unsealed)])
            self.assertEqual(output[0], 0)
            self.assertIn("state=unsealed", output[1])

            store = Path(tmp) / "mem"
            _make_store(store, 10)
            capsule = Path(tmp) / "good.aiem"
            export_capsule(store, capsule)

            no_manifest = Path(tmp) / "no-manifest.aiem"
            _rewrite_zip(
                capsule,
                no_manifest,
                lambda entries: {k: v for k, v in entries.items() if k != "manifest.json"},
            )
            with self.assertRaises(JianError) as context:
                verify_path(no_manifest)
            self.assertEqual(context.exception.code, E_HEADER_MISMATCH)

            bad_header = Path(tmp) / "bad-header.aiem"

            def _tamper(entries: dict[str, bytes]) -> dict[str, bytes]:
                manifest = json.loads(entries["manifest.json"])
                manifest["files"][0]["sha256"] = "0" * 64
                entries["manifest.json"] = json.dumps(manifest).encode("utf-8")
                return entries

            _rewrite_zip(capsule, bad_header, _tamper)
            with self.assertRaises(JianError) as context:
                verify_path(bad_header)
            self.assertEqual(context.exception.code, E_HEADER_MISMATCH)

            broken = Path(tmp) / "broken"
            _make_store(broken, 4)
            (broken / "chain.json").unlink()
            with self.assertRaises(JianError) as context:
                verify_path(broken)
            self.assertEqual(context.exception.code, E_HEADER_MISMATCH)
            failed = self._run(["verify", str(broken)])
            self.assertEqual(failed[0], 2)
            self.assertIn("E_HEADER_MISMATCH", failed[1])
            self.assertIn("seal", failed[1])

            repaired = self._run(["seal", str(broken)])
            self.assertEqual(repaired[0], 0)
            self.assertEqual(verify_path(broken).state, "sealed")
            self.assertIn("state=sealed", self._run(["verify", str(broken)])[1])

    @staticmethod
    def _run(args: list[str]) -> tuple[int, str]:
        import contextlib
        import io

        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue() + err.getvalue()


class CapsuleUnitsTest(unittest.TestCase):
    """Unit coverage for init/append/inspect/import failure paths."""

    def test_inspect_capsule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 25)
            capsule = Path(tmp) / "mem.aiem"
            export_capsule(store, capsule)
            info = inspect_capsule(capsule)
            self.assertEqual(info.schema, "jian.capsule/1")
            self.assertEqual(info.version, 1)
            self.assertEqual(info.events, 25)
            self.assertEqual(info.segments, 1)
            self.assertEqual(info.created, _manifest(store)["created"])

    def test_import_refuses_non_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 3)
            capsule = Path(tmp) / "mem.aiem"
            export_capsule(store, capsule)
            target = Path(tmp) / "target"
            target.mkdir()
            (target / "note.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(JianError) as context:
                import_capsule(capsule, target)
            self.assertEqual(context.exception.code, E_IO)


if __name__ == "__main__":
    unittest.main()
