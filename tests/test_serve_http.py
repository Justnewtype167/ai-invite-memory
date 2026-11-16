"""M43: the HTTP face of MemoryService -- token, key, and a real socket."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.errors import AiInviteError
from aiinvite.serve.http import _Handler, make_server

TOKEN = "t" * 32


class TestMemoryHTTP(unittest.TestCase):
    """H1-H9: every call goes over a real socket, not a fake handler."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_http_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.server = make_server(self.root, "qwen3.5:9b", token=TOKEN)
        self.addCleanup(self.server.close)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    # -- helpers -------------------------------------------------------
    def _call(self, path: str, body=None, token: str | None = TOKEN,
              method: str = "POST"):
        """Return (status, parsed body) for one call, never raising HTTPError."""
        data = None if body is None else (
            body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # -- tests ---------------------------------------------------------
    def test_health_needs_no_token(self) -> None:
        """H1: liveness is answerable without credentials, and exposes no memory."""
        status, body = self._call("/health", token=None, method="GET")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["model"], "qwen3.5:9b")
        self.assertNotIn("store", body)
        self.assertNotIn("prompt", body)

    def test_missing_or_wrong_token_is_refused(self) -> None:
        """H2: no bearer token, wrong token and a prefix of it all get 401."""
        for token in (None, "wrong", TOKEN[:-1]):
            status, body = self._call("/v1/turn", {"key": "u1", "text": "你好"},
                                      token=token)
            self.assertEqual(status, 401, token)
            self.assertEqual(body["error"]["code"], "E_ARG")
            self.assertNotIn("prompt", body)

    def test_turn_then_reply_then_view(self) -> None:
        """H3: the three calls a backend makes per message all work over HTTP."""
        status, turn = self._call("/v1/turn", {"key": "u1", "text": "我叫老周"})
        self.assertEqual(status, 200)
        self.assertIn("## this turn", turn["prompt"])
        self.assertIn("我叫老周", turn["prompt"])
        self.assertTrue(turn["event_id"].startswith("ev_"))

        status, reply = self._call("/v1/reply", {"key": "u1", "text": "记住了，老周。"})
        self.assertEqual(status, 200)
        self.assertTrue(reply["allowed"])
        self.assertEqual(reply["rule"], "")

        status, view = self._call("/v1/view?key=u1", token=TOKEN, method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(view["card"]["address"]["call"], "老周")
        self.assertEqual(view["events"], 2)

    def test_keys_never_come_from_the_path(self) -> None:
        """H4: a traversal-shaped key is refused by check_key, not resolved."""
        status, body = self._call("/v1/turn", {"key": "../escape", "text": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "E_ARG")
        self.assertFalse((self.root.parent / "escape").exists())

    def test_bad_input_is_a_400_with_a_code(self) -> None:
        """H5: malformed JSON, a missing field and an empty body each answer 400."""
        status, body = self._call("/v1/turn", b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "E_ARG")
        status, body = self._call("/v1/turn", {"key": "u1"})
        self.assertEqual(status, 400)
        self.assertIn("text", body["error"]["message"])
        status, body = self._call("/v1/turn", b"")
        self.assertEqual(status, 400)

    def test_unknown_route_is_404(self) -> None:
        """H6: an unlisted operation never reaches the service."""
        status, _ = self._call("/v1/delete", {"key": "u1", "text": "x"})
        self.assertEqual(status, 404)
        status, _ = self._call("/nope", method="GET")
        self.assertEqual(status, 404)

    def test_public_bind_requires_a_token(self) -> None:
        """H7: 0.0.0.0 without a token raises before any socket is opened."""
        with self.assertRaises(AiInviteError) as caught:
            make_server(self.root, "m", host="0.0.0.0")
        self.assertEqual(caught.exception.code, "E_ARG")
        # Loopback without a token is still allowed: that is the local demo.
        local = make_server(self.root, "m")
        self.addCleanup(local.close)
        self.assertEqual(local.token, "")

    def test_pin_and_unpin_round_trip(self) -> None:
        """H8: the console write paths work over HTTP and change the view."""
        _, turn = self._call("/v1/turn", {"key": "u1", "text": "我对花生过敏"})
        event_id = turn["event_id"]
        status, view = self._call("/v1/pin", {"key": "u1", "event_id": event_id})
        self.assertEqual(status, 200)
        self.assertEqual([pin["event_id"] for pin in view["pins"]], [event_id])
        status, view = self._call("/v1/unpin", {"key": "u1", "event_id": event_id})
        self.assertEqual(status, 200)
        self.assertEqual(view["pins"], [])

    def test_access_log_drops_the_query_string(self) -> None:
        """H9: /v1/view?key=u1 must not put a user id into docker logs."""
        handler = object.__new__(_Handler)
        handler.path = "/v1/view?key=secret-user-42"
        handler.address_string = lambda: "10.0.0.2"
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            _Handler.log_message(handler, '"%s" %s', "GET", 200)
        logged = buffer.getvalue()
        self.assertIn("/v1/view", logged)
        self.assertNotIn("secret-user-42", logged)


if __name__ == "__main__":
    unittest.main()
