"""Check the WorkBuddy probe against a loopback HTTP/ACP gateway fixture."""

from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workbuddy_probe as probe


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status=200, body=None, events=None):
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream" if events else "application/json")
        self.end_headers()
        if events:
            for event in events:
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
        elif body is not None:
            self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if not self.server.get_stream:
            self.reply(204)
            return
        connection = self.headers["acp-connection-id"]
        events = self.server.streams[connection]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        while True:
            try:
                item = events.get(timeout=3)
                if item is None:
                    return
                self.wfile.write(b"data: " + json.dumps(item).encode() + b"\n\n")
                self.wfile.flush()
            except (queue.Empty, OSError):
                return

    def do_DELETE(self):
        connection = self.headers["acp-connection-id"]
        self.server.closed.append(connection)
        self.server.streams[connection].put(None)
        self.reply(204)

    def do_POST(self):
        server = self.server
        if self.path == probe.ACP + "/connect":
            if server.require_token and self.headers.get("Authorization") != "Bearer fixture-auth":
                self.reply(401)
                return
            server.next_connection += 1
            value = "conn-" + str(server.next_connection)
            server.streams[value] = queue.Queue()
            self.reply(body={"data": {"connectionId": value, "sessionToken": "fixture-session-token"}})
            return
        connection = self.headers["acp-connection-id"]
        if self.headers["acp-session-token"] != "fixture-session-token":
            self.reply(403)
            return
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = msg.get("method")
        if method is None:
            server.permission_answers.put(msg)
            self.reply(204)
            return
        params = msg["params"]
        session = params.get("sessionId")
        server.calls.append((connection, method, params))
        response = {"jsonrpc": "2.0", "id": msg.get("id"), "result": {}}
        if method == "initialize":
            response["result"] = {"protocolVersion": 1}
        elif method == "session/new":
            session = "room-" + str(len(server.sessions))
            response["result"] = {"sessionId": session, "modes": self.modes()}
            server.sessions[session] = (params["cwd"], None)
        elif method == "session/load":
            if server.reject_load or server.sessions[session][0] != params["cwd"]:
                self.reply(body={**response, "error": {"code": -32000, "message": "load failed"}})
                return
            response["result"] = {"modes": self.modes()}
        elif method == "session/set_mode":
            server.plans.add((connection, session))
        elif method == "session/prompt":
            if (connection, session) not in server.plans:
                self.reply(403)
                return
            cwd, marker = server.sessions[session]
            match = re.search(r"AM-[a-f0-9]+", params["prompt"][0]["text"])
            if match:
                marker = match[0]
                server.sessions[session] = (cwd, marker)
            elif server.leak_marker:
                marker = server.sessions["room-0"][1]
            if server.no_prompt_result:
                self.reply(202)
                return
            response["result"] = {"stopReason": "end_turn"}
            frames = [
                self.chunk("other-session", "unrelated"),
                self.chunk(session, marker or "NONE"),
                response,
            ]
            if server.request_permissions:
                frames.insert(0, {
                    "jsonrpc": "2.0", "id": "permission-1", "method": "session/request_permission",
                    "params": {"sessionId": session},
                })
            if server.get_stream:
                for event in frames:
                    server.streams[connection].put(event)
                self.reply(202)
            else:
                self.reply(events=frames)
            return
        elif method == "session/cancel":
            self.reply(204)
            return
        self.reply(body=response)

    @staticmethod
    def modes():
        return {"currentModeId": "default", "availableModes": [{"id": "plan"}]}

    @staticmethod
    def chunk(session, text):
        return {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": session, "update": {"sessionUpdate": "agent_message_chunk",
                                             "content": {"type": "text", "text": text}},
        }}


class WorkBuddyProbeTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = self.server.server_address
        self.server.next_connection = 0
        self.server.closed = []
        self.server.calls = []
        self.server.sessions = {}
        self.server.plans = set()
        self.server.streams = {}
        self.server.permission_answers = queue.Queue()
        self.server.require_token = False
        self.server.reject_load = False
        self.server.leak_marker = False
        self.server.get_stream = False
        self.server.no_prompt_result = False
        self.server.request_permissions = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_recovers_original_session_across_connections_and_tests_isolation(self):
        output = StringIO()
        with redirect_stdout(output):
            probe.verify(self.endpoint, 3)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row["step"] for row in rows],
                         ["first_turn", "second_room_isolated", "same_session_after_reconnect"])
        first, second, resumed = [(connection, params["sessionId"]) for connection, method, params
                                  in self.server.calls if method == "session/prompt"]
        self.assertEqual(first[1], resumed[1])
        self.assertNotEqual(first[0], resumed[0])
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(len(self.server.closed), 3)

    def test_async_gateway_replies_and_permission_questions(self):
        self.server.get_stream = True
        self.server.request_permissions = True
        with redirect_stdout(StringIO()):
            probe.verify(self.endpoint, 3)
        answer = self.server.permission_answers.get(timeout=3)
        self.assertEqual(answer["result"], {"outcome": {"outcome": "cancelled"}})

    def test_missing_session_fails_without_replacing_it(self):
        self.server.reject_load = True
        with redirect_stdout(StringIO()), self.assertRaisesRegex(probe.ProbeError, "session/load_rejected"):
            probe.verify(self.endpoint, 3)
        methods = [method for _, method, _ in self.server.calls]
        self.assertEqual(methods.count("session/new"), 2)
        self.assertEqual(methods.count("session/prompt"), 2)
        self.assertEqual(len(self.server.closed), 3)

    def test_detects_cross_room_reply(self):
        self.server.leak_marker = True
        with redirect_stdout(StringIO()), self.assertRaisesRegex(probe.ProbeError, "rooms_not_isolated"):
            probe.verify(self.endpoint, 3)
        self.assertFalse(any(method == "session/load" for _, method, _ in self.server.calls))

    def test_timeout_sends_cancel_without_resending_prompt(self):
        self.server.no_prompt_result = True
        with probe.Gateway(self.endpoint, 1) as link, tempfile.TemporaryDirectory() as cwd:
            session = link.use_session(Path(cwd))
            with self.assertRaisesRegex(probe.ProbeError, "session/prompt_timed_out"):
                link.prompt(session, "brief test")
        calls = [(method, params.get("sessionId")) for _, method, params in self.server.calls]
        self.assertEqual(calls.count(("session/prompt", session)), 1)
        self.assertEqual(calls.count(("session/cancel", session)), 1)

    def test_auth_failure_stops_at_connect_and_valid_token_is_supported(self):
        self.server.require_token = True
        with patch.dict(os.environ, {"WORKBUDDY_GATEWAY_TOKEN": ""}):
            with self.assertRaisesRegex(probe.ProbeError, "gateway_http_401"):
                with probe.Gateway(self.endpoint, 3):
                    self.fail("connected without the required token")
        self.assertEqual(self.server.calls, [])
        with patch.dict(os.environ, {"WORKBUDDY_GATEWAY_TOKEN": "fixture-auth"}):
            with probe.Gateway(self.endpoint, 3) as link:
                self.assertEqual(link.init["protocolVersion"], 1)

    def test_auto_discovery_rejects_nonlocal_worker_and_expired_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sessions").mkdir()
            host = str(root / "workbuddy-host-cli")
            now = time.time() * 1000

            def record(name, url, cwd=host, heartbeat=now):
                (root / "sessions" / (name + ".json")).write_text(json.dumps({
                    "endpoint": url, "cwd": cwd, "lastHeartbeat": heartbeat,
                }), encoding="utf-8")

            record("remote", "http://192.0.2.10:1234")
            record("worker", "http://127.0.0.1:2222", cwd=str(root / "worker"))
            record("expired", "http://127.0.0.1:3333", heartbeat=now - 31000)
            with self.assertRaisesRegex(probe.ProbeError, "desktop_gateway_not_found"):
                probe.discover(root)
            record("host", "http://localhost:4444")
            self.assertEqual(probe.discover(root), ("127.0.0.1", 4444))
            record("host2", "http://127.0.0.1:5555")
            with self.assertRaisesRegex(probe.ProbeError, "multiple_desktop_gateways"):
                probe.discover(root)


if __name__ == "__main__":
    unittest.main()
