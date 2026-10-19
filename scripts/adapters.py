"""CLI command/output adapters. Process ownership and protocol writes stay in peer.py."""

import json
import os
import re
import subprocess

import chat


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class Legacy:
    prompt_schema = False

    def __init__(self, backend, npm_entries):
        self.backend = backend
        self.npm_entries = npm_entries

    def command(self, args, directory, run_directory, info, prefix, answer_path, RESPONSE_SCHEMA):
        backend = self.backend
        if backend == "claude":
            command = prefix + ["-p", "--output-format", "json", "--json-schema", json.dumps(RESPONSE_SCHEMA),
                                "--tools", "Read,Glob,Grep", "--allowedTools", "Read,Glob,Grep",
                                "--permission-mode", "dontAsk", "--strict-mcp-config", "--mcp-config",
                                '{"mcpServers":{}}', "--max-turns", "12"]
            if getattr(args, "model", None):
                command += ["--model", args.model]
            if info.get("native_session_id"):
                command += ["--resume", info["native_session_id"]]
        elif backend == "codex":
            schema_path = run_directory / "response-schema.json"
            write_json(schema_path, RESPONSE_SCHEMA)
            # Parent exec flags also apply to resume. Protocol writes happen in this
            # runner; the model gets a read-only sandbox and no approval bypass.
            command = prefix + ["exec", "--sandbox", "read-only", "--cd", args.cwd,
                                "-c", 'approval_policy="never"']
            if getattr(args, "model", None):
                command += ["--model", args.model]
            if info.get("native_session_id"):
                command += ["resume"]
            command += ["--json", "--skip-git-repo-check", "--output-schema", str(schema_path),
                        "--output-last-message", str(answer_path)]
            if info.get("native_session_id"):
                command += [info["native_session_id"]]
            command += ["-"]
        return command, None

    def parse(self, output_path, answer_path, directory, info):
        backend = self.backend
        if backend == "codex":
            records = [json.loads(line) for line in output_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in records):
                chat.fail(f"invalid Codex JSONL output; see {output_path}")
            if any(row.get("type") in ("error", "turn.failed") for row in records):
                chat.fail(f"Codex reported a failed turn; see {output_path}")
            session = next((row.get("thread_id") for row in records if row.get("type") == "thread.started"),
                           info.get("native_session_id"))
            result = json.loads(answer_path.read_text(encoding="utf-8-sig"))
            if not isinstance(result, dict):
                chat.fail("Codex returned an invalid structured response")
            if not isinstance(session, str) or not session or len(session) > 200 or session.startswith("-"):
                chat.fail("missing or invalid Codex thread ID in result")
            if info.get("native_session_id") and session != info["native_session_id"]:
                chat.fail("Codex resumed a different thread; refusing to silently replace context")
            return result, session
        envelope = json.loads(output_path.read_text(encoding="utf-8-sig"))
        if not isinstance(envelope, dict) or envelope.get("is_error"):
            chat.fail(f"Claude reported an error; see {output_path}")
        if envelope.get("permission_denials"):
            chat.fail(f"Claude could not access required resources; see {output_path}")
        result = envelope.get("structured_output")
        if not isinstance(result, dict):
            chat.fail(f"Claude returned no structured_output; update Claude Code or inspect {output_path}")
        session = envelope.get("session_id")
        if not isinstance(session, str) or not session or len(session) > 200 or session.startswith("-"):
            chat.fail("missing or invalid Claude session ID in result")
        if info.get("native_session_id") and session != info["native_session_id"]:
            chat.fail("Claude resumed a different session; refusing to silently replace context")
        return result, session


def probe(prefix, flag, cwd):
    try:
        result = subprocess.run(prefix + [flag], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=10, cwd=cwd)
    except subprocess.TimeoutExpired:
        chat.fail("agent CLI capability check timed out; inspect its installation")
    if result.returncode:
        chat.fail("agent CLI capability check failed; inspect its installation")
    return result.stdout


def session_ids(rows, key, event_type=None):
    sessions = set()
    for row in rows:
        if event_type and row.get("type") != event_type:
            continue
        value = row.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value or len(value) > 200 or value.startswith("-"):
            chat.fail("agent returned an invalid native session ID")
        sessions.add(value)
    if len(sessions) != 1:
        chat.fail("agent did not report exactly one native session")
    return next(iter(sessions))


def records(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        chat.fail(f"invalid CLI JSONL output; see {path}")
    return rows


def response(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {"action", "text", "decision", "conclusion"}:
        chat.fail("agent returned no valid discussion response object")
    if value["action"] not in ("send", "propose", "review") or not isinstance(value["text"], str) or value["decision"] not in ("none", "accept", "reject"):
        chat.fail("invalid agent response action, text or decision")
    conclusion = value["conclusion"]
    expected = {"summary", "agreements", "disagreements", "open_questions", "evidence_message_ids"}
    if not isinstance(conclusion, dict) or set(conclusion) != expected or not isinstance(conclusion["summary"], str):
        chat.fail("invalid agent response conclusion")
    for key in ("agreements", "disagreements", "open_questions"):
        if not isinstance(conclusion[key], list) or any(not isinstance(item, str) for item in conclusion[key]):
            chat.fail("invalid conclusion list in agent response")
    ids = conclusion["evidence_message_ids"]
    if not isinstance(ids, list) or any(type(item) is not int or item < 1 for item in ids):
        chat.fail("invalid evidence IDs in agent response")
    return value


class Pi:
    prompt_schema = True
    npm_entries = ("@earendil-works/pi-coding-agent/dist/bundle/cli.js",
                   "@mariozechner/pi-coding-agent/dist/cli.js")

    @staticmethod
    def session_file(directory):
        return directory / "native-session.jsonl"

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        session_file = self.session_file(directory)
        if info.get("native_session_id"):
            if not session_file.is_file() or session_file.stat().st_size == 0:
                chat.fail("pi's original session file is missing; refusing to start a replacement")
            with session_file.open(encoding="utf-8") as handle:
                header = json.loads(handle.readline())
            if not isinstance(header, dict) or header.get("type") != "session" or header.get("id") != info["native_session_id"]:
                chat.fail("pi session file does not match the original session")
        command = prefix + ["--print", "--mode", "json", "--session", str(session_file),
                            "--tools", "read,grep,find,ls", "--no-extensions", "--no-skills",
                            "--no-prompt-templates"]
        # Extensions are disabled. Built-in MCP on newer pi also requires an
        # explicit disable; older releases have no built-in MCP or this flag.
        if "--no-mcp" in probe(prefix, "--help", args.cwd):
            command += ["--no-mcp"]
        if getattr(args, "model", None):
            command += ["--model", args.model]
        return command, None

    def parse(self, output_path, answer_path, directory, info):
        rows = records(output_path)
        session = session_ids(rows, "id", "session")
        session_file = self.session_file(directory)
        if not session_file.is_file():
            chat.fail("pi did not persist its native session file")
        with session_file.open(encoding="utf-8") as handle:
            header = json.loads(handle.readline())
        if not isinstance(header, dict) or header.get("type") != "session" or header.get("id") != session:
            chat.fail("pi returned a different session from its saved session file")
        messages = [r["message"] for r in rows if r.get("type") == "message_end"
                    and isinstance(r.get("message"), dict) and r["message"].get("role") == "assistant"]
        if not messages or messages[-1].get("stopReason") not in ("stop", "end_turn"):
            chat.fail("pi did not complete a successful assistant response")
        if not any(row.get("type") in ("agent_end", "agent_settled") for row in rows):
            chat.fail("pi did not finish its agent run")
        content = messages[-1].get("content")
        if not isinstance(content, list) or any(not isinstance(part, dict) for part in content):
            chat.fail("pi returned invalid assistant content")
        texts = [part.get("text") for part in content if part.get("type") == "text"]
        if any(not isinstance(text, str) for text in texts):
            chat.fail("pi returned invalid assistant text")
        text = "".join(texts)
        return response(text), session


class OpenCode:
    prompt_schema = True
    # These npm launchers require Bun; use the native platform binary instead.
    npm_entries = ()

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        match = re.search(r"\b([12])\.\d+\.\d+", probe(prefix, "--version", args.cwd))
        if not match:
            chat.fail("supported OpenCode version not detected (requires run JSON mode in 1.x or 2.x)")
        major = int(match.group(1))
        readonly = {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow", "list": "allow"}
        # A separate agent prevents built-in build/plan permissions overriding
        # the discussion tool allowlist. This is per-process, never saved globally.
        agent = {"mode": "primary", "description": "Read-only Agent Chat participant", "permission": readonly}
        overlay = {"agent": {"agent-chat": agent}, "permission": readonly, "share": "disabled"}
        environment = os.environ.copy()
        if environment.get("OPENCODE_CONFIG_CONTENT"):
            chat.fail("OPENCODE_CONFIG_CONTENT is already set; refusing to silently replace caller configuration")
        environment.update(OPENCODE_CONFIG_CONTENT=json.dumps(overlay),
                           OPENCODE_PERMISSION=json.dumps(readonly), OPENCODE_DISABLE_AUTOUPDATE="1")
        command = prefix + ["run", "--format", "json", "--agent", "agent-chat"]
        if major == 2:
            # A managed daemon could keep old environment/configuration. A leased
            # standalone service inherits this call's overlay and ends with it.
            command += ["--standalone"]
        if info.get("native_session_id"):
            command += ["--session", info["native_session_id"]]
        if getattr(args, "model", None):
            command += ["--model", args.model]
        return command, environment

    def parse(self, output_path, answer_path, directory, info):
        rows = records(output_path)
        if any(row.get("type") == "error" for row in rows):
            chat.fail(f"OpenCode reported a failed turn; see {output_path}")
        session = session_ids(rows, "sessionID")
        if any(not isinstance(row.get("part"), dict) for row in rows if row.get("type") in ("text", "step_finish")):
            chat.fail("OpenCode returned an invalid text or step record")
        finishes = [row.get("part", {}).get("reason") for row in rows if row.get("type") == "step_finish"]
        if not finishes or finishes[-1] not in ("stop", "end_turn"):
            chat.fail("OpenCode did not complete a successful assistant response")
        texts = {}
        for row in rows:
            if row.get("type") == "text":
                part = row.get("part", {})
                message = part.get("messageID")
                if not isinstance(message, str) or not message or not isinstance(part.get("text"), str):
                    chat.fail("OpenCode text has no assistant message ID")
                texts.setdefault(message, []).append(part.get("text", ""))
        if not texts:
            chat.fail("OpenCode returned no assistant text")
        return response("".join(list(texts.values())[-1])), session


REGISTRY = {
    "claude": Legacy("claude", ("@anthropic-ai/claude-code/cli.js",)),
    "codex": Legacy("codex", ("@openai/codex/bin/codex.js",)),
    "pi": Pi(),
    "opencode": OpenCode(),
}
BACKENDS = tuple(REGISTRY)


def get(backend):
    if backend not in REGISTRY:
        chat.fail("unsupported agent backend; choose " + ", ".join(BACKENDS))
    return REGISTRY[backend]
