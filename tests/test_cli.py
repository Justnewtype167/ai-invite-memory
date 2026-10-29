"""CLI tests: seven commands, output format and exit codes."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from jian.capsule import append_event, export_capsule, init_store, seal_store, verify_path
from jian.cli import main


def _stamp(index: int) -> str:
    return f"2026-10-29T06:00:{index:02d}Z"


def _make_store(store: Path, count: int, *, sealed: bool = True) -> None:
    init_store(store)
    for index in range(1, count + 1):
        append_event(store, "user" if index % 2 else "assistant", f"msg-{index:04d}", _stamp(index))
    if sealed:
        seal_store(store)


class CliTest(unittest.TestCase):
    def test_help_lists_seven_commands(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as context:
                main(["--help"])
        self.assertEqual(context.exception.code, 0)
        text = buffer.getvalue()
        for command in ("init", "append", "seal", "verify", "export", "import", "inspect"):
            self.assertIn(command, text)

    def test_verify_ok_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 4)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(["verify", str(store)])
            self.assertEqual(code, 0)
            self.assertTrue(buffer.getvalue().startswith("OK events=4 segments=1 head="))
            self.assertIn("state=sealed", buffer.getvalue())

    def test_verify_tamper_exit_two_with_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 10)
            path = store / "evidence" / "seg-0001.jsonl"
            path.write_bytes(path.read_bytes().replace(b"msg-0005", b"msg-0006"))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["verify", str(store)])
            self.assertEqual(code, 2)
            self.assertIn("FAIL E_TAMPER", err.getvalue())
            self.assertIn("[event=ev_000005]", err.getvalue())

    def test_argument_error_exit_one(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["verify"])
        self.assertEqual(code, 1)
        self.assertIn("E_ARG", err.getvalue())

    def test_export_unsealed_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            _make_store(store, 2, sealed=False)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(["export", str(store), str(Path(tmp) / "x.aiem")])
            self.assertEqual(code, 2)
            self.assertIn("E_SCHEMA", err.getvalue())

    def test_full_cli_flow_and_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "mem"
            capsule = Path(tmp) / "mem.aiem"
            init_store(store)
            self.assertEqual(main(["append", str(store), "--role", "user", "--text", "hi"]), 0)
            self.assertEqual(main(["seal", str(store)]), 0)
            self.assertEqual(main(["export", str(store), str(capsule)]), 0)
            self.assertEqual(main(["verify", str(capsule)]), 0)
            copied = Path(tmp) / "copied"
            self.assertEqual(main(["import", str(capsule), str(copied)]), 0)
            self.assertEqual(verify_path(copied).events, 1)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["inspect", str(capsule)]), 0)
            self.assertIn("events=1 segments=1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
