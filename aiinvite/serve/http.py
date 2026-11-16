"""HTTP entry point for ``MemoryService`` (M43).

``MemoryService`` is a Python object. A Deno edge function, a Node backend or a
Go service cannot call a Python object, and starting a new interpreter per turn
would pay an import and a cold store read on every message -- the 30 ms the
engine spent getting fast would be given straight back to process startup. So
the service runs once, for as long as the container lives, and speaks a small
JSON protocol over HTTP: the backend calls it the way it calls any other
service on its network.

Four decisions worth stating, because each is a bug when reversed:

* **A non-loopback bind requires a token.** Whoever can POST ``/v1/turn`` reads
  the user's memory back through the prompt it returns. A missing token on
  ``0.0.0.0`` raises before the socket opens, rather than after the first
  stranger finds the port.
* **The store key travels in the body, never in the path.** ``check_key`` already
  refuses separators, parent references and Windows device names; a path
  segment would additionally have to survive URL decoding identically in the
  proxy and here, and one decoder difference is a traversal.
* **``/v1/reply`` exists but cannot be enforced from here.** It is the actuation
  gate. A backend that skips it keeps the memory and loses the persona
  enforcement, and the service has no way to tell -- but refusals land in the
  evidence chain, so the console can show the difference.
* **Queries are not logged.** The default ``BaseHTTPRequestHandler`` log line
  includes the query string, and ``/v1/view?key=...`` would put user ids into
  ``docker logs`` forever. The access log keeps the path only.

Deliberately absent: TLS (terminate it at nginx, or keep the service on an
internal docker network), rate limiting, and any write to derived data.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aiinvite.errors import E_ARG, E_IO, E_LOCK, AiInviteError
from aiinvite.kernel.errors import KernelError
from aiinvite.serve import MemoryService

BODY_LIMIT = 64 * 1024
LOOPBACK = ("127.0.0.1", "localhost", "::1")
POST_ROUTES = ("turn", "reply", "remember", "pin", "unpin")

_STATUS = {E_ARG: 400, E_LOCK: 409}


def _status_for(exc: Exception) -> int:
    """Map one engine error to an HTTP status; anything unknown is a 500."""
    if isinstance(exc, AiInviteError):
        return _STATUS.get(exc.code, 500)
    if isinstance(exc, KernelError):
        return 500
    return 500


def _payload(exc: Exception) -> dict:
    """Return a JSON body for an error without leaking a traceback."""
    code = getattr(exc, "code", "E_IO")
    message = getattr(exc, "message", None) or str(exc)
    return {"error": {"code": code, "message": message}}


class MemoryHTTPServer(ThreadingHTTPServer):
    """One warm ``MemoryService`` behind a threaded stdlib server."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service, token=None):
        """Bind the socket to a service instance and an optional shared token."""
        super().__init__(address, _Handler)
        self.service = service
        self.token = token or ""

    @property
    def url(self) -> str:
        """Return the base URL, with the port the OS actually assigned."""
        host, port = self.server_address[0], self.server_address[1]
        if ":" in str(host):
            host = f"[{host}]"
        return f"http://{host}:{port}"

    def close(self) -> None:
        """Close the socket and drop the warm sessions; evidence stays on disk."""
        try:
            self.server_close()
        finally:
            self.service.close()


class _Handler(BaseHTTPRequestHandler):
    """The wire protocol: JSON in, JSON out, bearer token on every call."""

    server_version = "AIInviteMemory/1"
    sys_version = ""

    # -- plumbing ------------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        """Log the path without its query string; user ids must not leak."""
        path = str(self.path).split("?", 1)[0]
        sys.stderr.write("%s - %s\n" % (self.address_string(), path))

    def _send(self, status: int, body: dict) -> None:
        """Write one JSON response with an explicit length."""
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorised(self) -> bool:
        """Check the bearer token in constant time; open when none is set."""
        expected = self.server.token
        if not expected:
            return True
        header = self.headers.get("Authorization", "") or ""
        prefix = "Bearer "
        got = header[len(prefix):].strip() if header.startswith(prefix) else ""
        if not got:
            return False
        return hmac.compare_digest(got, expected)

    def _guard(self) -> bool:
        """Return True when the caller may proceed, else answer 401/404/413."""
        if not self._authorised():
            self._send(401, {"error": {"code": E_ARG, "message": "缺少或错误的 token"}})
            return False
        return True

    def _body(self) -> dict:
        """Read and parse the JSON body, raising E_ARG on anything unusable."""
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise AiInviteError(E_ARG, "Content-Length 不合法")
        if length <= 0:
            raise AiInviteError(E_ARG, "请求体为空")
        if length > BODY_LIMIT:
            raise AiInviteError(E_ARG, f"请求体超过 {BODY_LIMIT} 字节")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AiInviteError(E_ARG, "请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise AiInviteError(E_ARG, "请求体必须是 JSON 对象")
        return data

    @staticmethod
    def _text(data: dict, field: str = "text") -> str:
        """Return a required string field, or raise E_ARG."""
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AiInviteError(E_ARG, f"{field} 必须是非空字符串")
        return value

    # -- routes --------------------------------------------------------
    def do_GET(self):  # noqa: N802 - stdlib signature
        """Serve ``/health`` without auth and ``/v1/view`` with it."""
        path = str(self.path).split("?", 1)[0]
        if path == "/health":
            self._send(200, {"ok": True, "model": self.server.service.model,
                             **self.server.service.stats()})
            return
        if path == "/v1/view":
            if not self._guard():
                return
            key = self._query_key()
            if key is None:
                return
            try:
                self._send(200, self.server.service.view(key))
            except Exception as exc:  # noqa: BLE001 - the wire never raises
                self._send(_status_for(exc), _payload(exc))
            return
        self._send(404, {"error": {"code": E_ARG, "message": f"没有这个路由：{path}"}})

    def do_POST(self):  # noqa: N802 - stdlib signature
        """Dispatch one of the five write operations in ``MemoryService``."""
        path = str(self.path).split("?", 1)[0]
        name = path[len("/v1/"):] if path.startswith("/v1/") else ""
        if name not in POST_ROUTES:
            self._send(404, {"error": {"code": E_ARG, "message": f"没有这个路由：{path}"}})
            return
        if not self._guard():
            return
        try:
            data = self._body()
            key = self._text(data, "key")
            service = self.server.service
            if name == "turn":
                result = service.turn(key, self._text(data, "text"), data.get("t"))
            elif name == "reply":
                result = service.reply(key, self._text(data, "text"), data.get("t"))
            elif name == "remember":
                result = service.remember(key, self._text(data, "text"), data.get("t"))
            elif name == "pin":
                result = service.pin(key, self._text(data, "event_id"), data.get("t"))
            else:
                result = service.unpin(key, self._text(data, "event_id"), data.get("t"))
        except Exception as exc:  # noqa: BLE001 - the wire never raises
            self._send(_status_for(exc), _payload(exc))
            return
        self._send(200, result)

    def _query_key(self):
        """Pull ``key`` out of the query string, or answer 400 and return None."""
        from urllib.parse import parse_qs, urlsplit

        query = parse_qs(urlsplit(str(self.path)).query)
        key = (query.get("key") or [""])[0].strip()
        if not key:
            self._send(400, {"error": {"code": E_ARG, "message": "缺少 key"}})
            return None
        return key


def make_server(root, model, host="127.0.0.1", port=0, token=None,
                budget=4096, max_sessions=32):
    """Build a bound server; the caller decides whether to serve in a thread."""
    if not token and host not in LOOPBACK:
        raise AiInviteError(
            E_ARG,
            f"监听 {host} 必须提供 token：任何能访问该端口的人都能读回用户记忆",
        )
    service = MemoryService(root, model, budget=budget, max_sessions=max_sessions)
    return MemoryHTTPServer((host, port), service, token)


def main(argv=None) -> int:
    """Run the service until interrupted; the token comes from the environment."""
    parser = argparse.ArgumentParser(
        prog="python -m aiinvite.serve.http",
        description="用 HTTP 暴露 MemoryService：一轮对话 = /v1/turn + 模型 + /v1/reply",
    )
    parser.add_argument("--root", required=True, help="用户记忆根目录，例如 /data/users")
    parser.add_argument("--model", required=True, help="当前模型名，写进证据，换模型时用来对比")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址；非本机必须配 token")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--budget", type=int, default=4096, help="每轮提示词预算（token）")
    parser.add_argument("--max-sessions", type=int, default=32, help="同时保持热会话的用户数")
    parser.add_argument("--token-env", default="AIINVITE_TOKEN",
                        help="从这个环境变量读 token；未设置则不鉴权（仅限本机）")
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env, "").strip() or None
    try:
        server = make_server(args.root, args.model, host=args.host, port=args.port,
                             token=token, budget=args.budget,
                             max_sessions=args.max_sessions)
    except (AiInviteError, OSError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stderr.write(f"listening on {server.url} (token: {'on' if token else 'off'})\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
