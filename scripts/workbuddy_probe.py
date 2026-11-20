#!/usr/bin/env python3
"""Experimental, local WorkBuddy Desktop connection check. Uses only Python stdlib."""

import argparse
from contextlib import suppress
import http.client
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ACP = "/api/v1/acp"
MAX_FRAME = 512 * 1024


class ProbeError(Exception):
    pass


def gateway_endpoint(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")
                and parts.port and parts.path in ("", "/") and parts.username is None
                and parts.password is None and "?" not in url and "#" not in url):
            return ("127.0.0.1" if parts.hostname == "localhost" else parts.hostname, parts.port)
    except ValueError:
        pass
    raise ProbeError("gateway_must_be_loopback_http_with_port")


def discover(home=None):
    roots = [Path(home).expanduser()] if home else [Path.home() / name for name in (".workbuddy", ".workbuddy-ai")]
    candidates = set()
    for root in roots:
        sessions = root / "sessions"
        for file in sessions.glob("*.json"):
            try:
                if not file.is_file() or file.resolve().parent != sessions.resolve():
                    continue
                with file.open("rb") as handle:
                    raw = handle.read(65537)
                if len(raw) > 65536:
                    continue
                data = json.loads(raw)
                if not isinstance(data, dict):
                    continue
                if not 0 <= time.time() * 1000 - data["lastHeartbeat"] <= 30000:
                    continue
                # Only the desktop host, never a worker attached to an existing task.
                if Path(data.get("cwd", "")).name.lower() != "workbuddy-host-cli":
                    continue
                candidates.add(gateway_endpoint(data["endpoint"]))
            except (OSError, ValueError, KeyError, TypeError, ProbeError):
                continue
    if len(candidates) != 1:
        raise ProbeError("desktop_gateway_not_found" if not candidates else "multiple_desktop_gateways")
    return candidates.pop()


def read_json(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ProbeError("unexpected_gateway_response") from None


def frames(response):
    if "text/event-stream" not in response.getheader("Content-Type", ""):
        raw = response.read(MAX_FRAME + 1)
        if len(raw) > MAX_FRAME:
            raise ProbeError("gateway_response_too_large")
        if raw.strip():
            yield read_json(raw)
        return
    data, length = [], 0
    while True:
        line = response.readline(MAX_FRAME + 1)
        if len(line) > MAX_FRAME:
            raise ProbeError("gateway_event_too_large")
        if not line or line in (b"\n", b"\r\n"):
            if data:
                yield read_json(b"\n".join(data))
                data, length = [], 0
            if not line:
                return
        elif line.startswith(b"data:"):
            length += len(line)
            if length > MAX_FRAME:
                raise ProbeError("gateway_event_too_large")
            data.append(line[5:].strip())


class Gateway:
    def __init__(self, endpoint, timeout):
        self.endpoint = endpoint
        self.timeout = timeout
        self.headers = {"X-CodeBuddy-Request": "1", "Accept": "application/json, text/event-stream"}
        if os.environ.get("WORKBUDDY_GATEWAY_TOKEN"):
            self.headers["Authorization"] = "Bearer " + os.environ["WORKBUDDY_GATEWAY_TOKEN"]
        self.messages = queue.Queue(maxsize=1024)
        self.closed = threading.Event()
        self.request_id = 0
        self.session = None
        self.output = []
        self.output_length = 0
        self.saw_tool = False

    def http(self, method, path, payload=None, timeout=None):
        # A literal loopback connection, without proxying or following redirects.
        conn = http.client.HTTPConnection(*self.endpoint, timeout=timeout or self.timeout)
        try:
            headers = self.headers.copy()
            if payload is not None:
                headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                raise ProbeError("gateway_http_" + str(response.status))
            yield from frames(response)
        except (OSError, http.client.HTTPException):
            raise ProbeError("gateway_unreachable_or_connection_closed") from None
        finally:
            conn.close()

    def start(self, method, path, payload=None, request_id=None):
        def read():
            try:
                for message in self.http(method, path, payload):
                    if self.closed.is_set():
                        return
                    self.messages.put((request_id, message), timeout=1)
            except ProbeError as exc:
                # Some versions deliver replies in POST SSE and omit GET SSE.
                if request_id is not None and not self.closed.is_set():
                    with suppress(queue.Full):
                        self.messages.put((request_id, exc), timeout=1)
            except queue.Full:
                return
        threading.Thread(target=read, daemon=True).start()

    def __enter__(self):
        replies = list(self.http("POST", ACP + "/connect"))
        connection = replies[0] if len(replies) == 1 else None
        if isinstance(connection, dict):
            connection = connection.get("data", connection)
        if not isinstance(connection, dict):
            raise ProbeError("missing_acp_connection")
        for key, header in (("connectionId", "acp-connection-id"), ("sessionToken", "acp-session-token")):
            value = connection.get(key)
            if key == "sessionToken" and value is None:
                continue
            if not isinstance(value, str) or not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise ProbeError("missing_or_invalid_" + key)
            self.headers[header] = value
        self.start("GET", ACP)
        try:
            self.init = self.request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {"_meta": {"codebuddy.ai": {"question": False, "promptSuggestion": False}}},
                "clientInfo": {"name": "agent-meet-workbuddy-probe", "version": "0.1.0"},
            })
            if self.init.get("protocolVersion") != 1:
                raise ProbeError("unsupported_acp_protocol")
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        self.closed.set()
        # This closes only the ACP connection created by the probe.
        with suppress(ProbeError):
            list(self.http("DELETE", ACP, timeout=min(self.timeout, 3)))

    def request(self, method, params):
        self.request_id += 1
        key = self.request_id
        self.start("POST", ACP, {"jsonrpc": "2.0", "id": key, "method": method, "params": params}, request_id=key)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                stream_id, item = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise ProbeError(method + "_timed_out") from None
            if stream_id is not None and stream_id != key:
                continue
            if isinstance(item, ProbeError):
                raise item
            if not isinstance(item, dict):
                raise ProbeError("invalid_acp_frame")
            if time.monotonic() >= deadline:
                raise ProbeError(method + "_timed_out")
            if isinstance(item.get("method"), str):
                self.notification(item)
                continue
            if item.get("id") != key:
                continue
            if "error" in item:
                raise ProbeError(method + "_rejected")
            if not isinstance(item.get("result"), dict):
                raise ProbeError(method + "_bad_result")
            return item["result"]

    def notification(self, item):
        method = item["method"]
        if "id" in item:
            # Only permission questions are interpreted. Never approve an operation.
            if method in ("session/request_permission", "requestPermission"):
                value = {"result": {"outcome": {"outcome": "cancelled"}}}
            else:
                value = {"error": {"code": -32601, "message": "Unsupported by this probe"}}
            self.start("POST", ACP, {"jsonrpc": "2.0", "id": item["id"], **value})
            return
        params = item.get("params")
        if method not in ("session/update", "sessionUpdate") or not isinstance(params, dict):
            return
        if self.session is None or params.get("sessionId") != self.session:
            return
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        if update.get("sessionUpdate") in ("tool_call", "tool_call_update"):
            self.saw_tool = True
        if update.get("sessionUpdate") != "agent_message_chunk":
            return
        content = update.get("content", {})
        if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
            chunk = content["text"]
            self.output_length += len(chunk)
            if self.output_length > MAX_FRAME:
                raise ProbeError("prompt_reply_too_large")
            self.output.append(chunk)

    def use_session(self, cwd, previous=None):
        params = {"cwd": str(cwd), "mcpServers": []}
        if previous is None:
            result = self.request("session/new", params)
            session = result.get("sessionId")
            if not isinstance(session, str) or not session or len(session) > 256:
                raise ProbeError("missing_session_id")
        else:
            result = self.request("session/load", {**params, "sessionId": previous})
            session = result.get("sessionId", previous)
            if session != previous:
                raise ProbeError("resume_changed_session")
        # Before any model turn, require a negotiated plan mode on the probe session.
        modes = result.get("modes")
        if isinstance(modes, dict):
            entries = modes.get("availableModes", [])
            if modes.get("currentModeId") == "plan":
                return session
            if isinstance(entries, list) and any(isinstance(mode, dict) and mode.get("id") == "plan" for mode in entries):
                self.request("session/set_mode", {"sessionId": session, "modeId": "plan"})
                return session
        options = result.get("configOptions", [])
        if not isinstance(options, list):
            raise ProbeError("invalid_acp_config_options")
        for option in options:
            if isinstance(option, dict) and option.get("category") == "mode":
                if option.get("currentValue") == "plan":
                    return session
                choices = option.get("options")
                if (isinstance(option.get("id"), str) and isinstance(choices, list)
                        and any(isinstance(entry, dict) and entry.get("value") == "plan" for entry in choices)):
                    self.request("session/set_config_option", {
                        "sessionId": session, "configId": option["id"], "type": "select", "value": "plan",
                    })
                    return session
        raise ProbeError("no_plan_mode_advertised")

    def prompt(self, session, text):
        self.session = session
        self.output = []
        self.output_length = 0
        self.saw_tool = False
        try:
            result = self.request("session/prompt", {
                "sessionId": session, "prompt": [{"type": "text", "text": text}],
            })
            reason = result.get("stopReason")
            if reason != "end_turn":
                known = ("refusal", "cancelled", "max_tokens", "max_turn_requests")
                raise ProbeError("prompt_" + reason if reason in known else "prompt_missing_success_receipt")
            if self.saw_tool:
                raise ProbeError("probe_turn_used_tools")
            return "".join(self.output).strip()
        except (ProbeError, KeyboardInterrupt):
            with suppress(ProbeError):
                list(self.http("POST", ACP, {
                    "jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session},
                }, timeout=min(self.timeout, 3)))
            raise
        finally:
            self.session = None


def verify(endpoint, timeout):
    marker = "AM-" + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix="agent-meet-wb-") as root:
        a, b = Path(root) / "room-a", Path(root) / "room-b"
        a.mkdir()
        b.mkdir()
        question = "Without using tools, reply with only the test marker from this conversation. If none was given, reply exactly NONE."
        with Gateway(endpoint, timeout) as link:
            session_a = link.use_session(a)
            answer = link.prompt(session_a, "Do not call tools. Remember and reply with exactly this test marker: " + marker)
            if answer != marker:
                raise ProbeError("first_turn_marker_mismatch")
            print(json.dumps({"step": "first_turn", "ok": True}), flush=True)
        with Gateway(endpoint, timeout) as link:
            session_b = link.use_session(b)
            if session_b == session_a or link.prompt(session_b, question) != "NONE":
                raise ProbeError("rooms_not_isolated")
            print(json.dumps({"step": "second_room_isolated", "ok": True}), flush=True)
        with Gateway(endpoint, timeout) as link:
            restored = link.use_session(a, previous=session_a)
            if link.prompt(restored, question) != marker:
                raise ProbeError("resumed_turn_marker_mismatch")
            print(json.dumps({"step": "same_session_after_reconnect", "ok": True}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", help="explicit loopback root URL, if auto-discovery is unavailable")
    parser.add_argument("--workbuddy-home", help="WorkBuddy runtime directory (default: ~/.workbuddy or ~/.workbuddy-ai)")
    parser.add_argument("--verify", action="store_true", help="send 3 short prompts to test isolation and same-session reconnect")
    parser.add_argument("--timeout", type=int, default=90, choices=range(1, 181), metavar="SECONDS")
    args = parser.parse_args()
    try:
        endpoint = gateway_endpoint(args.gateway) if args.gateway else discover(args.workbuddy_home)
        with Gateway(endpoint, min(args.timeout, 15)) as link:
            print(json.dumps({"step": "desktop_gateway", "ok": True, "protocol": link.init["protocolVersion"]}), flush=True)
        if args.verify:
            verify(endpoint, args.timeout)
    except (ProbeError, OSError, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, ProbeError) else "cancelled" if isinstance(exc, KeyboardInterrupt) else "local_io_error"
        print(json.dumps({"ok": False, "error": reason}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
