#!/usr/bin/env python3
"""A local, dependency-free viewer for one Agent Chat discussion."""

import argparse
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import chat
import consult
import peer

WEB = Path(__file__).resolve().parent.parent / "web"
ASSETS = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css",
          "/vendor/marked-17.0.5.js": "vendor/marked-17.0.5.js",
          "/vendor/dompurify-3.4.17.js": "vendor/dompurify-3.4.17.js"}


def directory(room):
    return Path(str(Path(room).resolve()) + ".view")


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def snapshot(room):
    with chat.database(room) as conn:
        status = chat.state(conn)
        events = [chat.event(row) for row in conn.execute("SELECT * FROM events ORDER BY id")]
    config = read_json(consult.directory(room) / "config.json")
    model = read_json(consult.directory(room) / "status.json")
    reviewer = config.get("reviewer", status["participants"][1])
    worker = peer.read_status(peer.paths(room, reviewer))
    # Expose progress and errors, never CLI arguments, native IDs or filesystem logs.
    return {"status": status, "events": events, "briefing": config.get("briefing"),
            "main": config.get("main", status["participants"][0]), "reviewer": reviewer,
            "model": {key: model[key] for key in ("state", "detail") if key in model},
            "worker": {key: worker[key] for key in ("state", "detail") if key in worker}}


class Viewer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, room):
        self.room = str(Path(room).resolve())
        self.token = secrets.token_urlsafe(32)
        self.closing = False
        super().__init__(("127.0.0.1", 0), Handler)
        self.timeout = 0.5
        self.origin = "http://127.0.0.1:" + str(self.server_port)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, body, content_type="application/json; charset=utf-8", **headers):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for name, value in {
            "Content-Type": content_type, "Content-Length": str(len(body)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            **headers,
        }.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            self.respond(403, {"error": "invalid host"})
            return False
        if self.headers.get("Origin") not in (None, self.server.origin):
            self.respond(403, {"error": "invalid origin"})
            return False
        if self.path.startswith("/api/") and not hmac.compare_digest(
                self.headers.get("Authorization", "").encode("utf-8"),
                ("Bearer " + self.server.token).encode("utf-8")):
            self.respond(401, {"error": "viewer token required; use the full local URL"})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        try:
            if self.path == "/api/state":
                self.respond(200, snapshot(self.server.room))
            elif self.path == "/api/health":
                self.respond(200, {"ok": True, "pid": os.getpid()})
            elif self.path == "/api/export":
                with tempfile.TemporaryDirectory(prefix="agent-chat-export-") as temp:
                    output = Path(temp) / "report.md"
                    chat.export(argparse.Namespace(room=self.server.room, output=output))
                    self.respond(200, output.read_bytes(), "text/markdown; charset=utf-8",
                                 **{"Content-Disposition": 'attachment; filename="agent-chat-report.md"'})
            elif self.path in ASSETS:
                path = WEB / ASSETS[self.path]
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.respond(200, path.read_bytes(), mime + "; charset=utf-8")
            else:
                self.respond(404, {"error": "not found"})
        except (chat.ChatError, OSError, ValueError, sqlite3.Error) as exc:
            self.respond(500, {"error": str(exc)})

    def do_POST(self):
        if not self.allowed():
            return
        # These actions have no request body and never accept arbitrary paths or commands.
        if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
            self.respond(400, {"error": "request body not accepted"})
            return
        try:
            if self.path == "/api/stop":
                result = chat.stop(argparse.Namespace(room=self.server.room, reason="用户从讨论页面停止"))
                self.respond(200, result)
            elif self.path == "/api/shutdown":
                self.respond(200, {"ok": True})
                self.server.closing = True
            else:
                self.respond(404, {"error": "not found"})
        except (chat.ChatError, OSError, ValueError, sqlite3.Error) as exc:
            self.respond(500, {"error": str(exc)})


def request(info, path, method="GET"):
    origin = info.get("origin", "")
    # Status files must not redirect the local control command to another host.
    from urllib.parse import urlsplit
    parts = urlsplit(origin)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port or parts.path:
        raise ValueError("invalid local viewer address")
    req = urllib.request.Request(origin + path, method=method,
                                 headers={"Authorization": "Bearer " + info["token"]})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        NoRedirect())
    with opener.open(req, timeout=2) as response:
        return json.load(response)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def running(room):
    info = read_json(directory(room) / "status.json")
    if info.get("state") == "running":
        try:
            health = request(info, "/api/health")
            if health.get("pid") == info.get("pid"):
                return info
        except (OSError, ValueError, KeyError):
            pass
    return None


def serve(room, run_id):
    root = directory(room)
    with peer.participant_lock(root):
        snapshot(room)
        with Viewer(room) as server:
            info = {"state": "running", "pid": os.getpid(), "origin": server.origin,
                    "token": server.token, "url": server.origin + "/#" + server.token,
                    "run_id": run_id}
            peer.write_json(root / "status.json", info)
            if os.name != "nt":
                (root / "status.json").chmod(0o600)
            try:
                while not server.closing:
                    server.handle_request()
            finally:
                peer.write_json(root / "status.json", {**info, "state": "closed"})
                if os.name != "nt":
                    (root / "status.json").chmod(0o600)


def start(args):
    snapshot(args.room)
    root = directory(args.room)
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    with peer.participant_lock(root / "launcher"):
        info = running(args.room)
        duplicate = bool(info)
        if not info:
            run_id = secrets.token_hex(12)
            kwargs = {"start_new_session": True} if os.name != "nt" else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
            with (root / "server.log").open("ab") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_serve",
                                            "--room", str(Path(args.room).resolve()), "--run-id", run_id],
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    chat.fail("viewer failed to start; inspect " + str(root / "server.log"))
                info = running(args.room)
                if info and info.get("run_id") == run_id:
                    break
                time.sleep(0.1)
            else:
                process.terminate()
                process.wait(timeout=3)
                chat.fail("viewer startup timed out")
    result = {"url": info["url"], "pid": info["pid"], "duplicate": duplicate}
    if args.open:
        try:
            result["browser_opened"] = bool(webbrowser.open(info["url"]))
        except webbrowser.Error:
            result["browser_opened"] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "status", "close", "_serve"):
        p = sub.add_parser(command)
        p.add_argument("--room", required=True)
        if command == "start":
            p.add_argument("--open", action="store_true", help="open the local page in the default browser")
        if command == "_serve":
            p.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "start":
            result = start(args)
        elif args.command == "_serve":
            serve(args.room, args.run_id)
            return 0
        else:
            info = running(args.room)
            if info and args.command == "close":
                request(info, "/api/shutdown", "POST")
            result = {"running": bool(info) and args.command != "close"}
            if info and args.command == "status":
                result["url"] = info["url"]
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except (chat.ChatError, peer.AlreadyRunning, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
