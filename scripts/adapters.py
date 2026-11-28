"""CLI command/output adapters. Process ownership and protocol writes stay in peer.py."""

import json
import os
import re
import subprocess
import uuid

import chat
import processes


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class Legacy:
    prompt_schema = False

    def __init__(self, backend, npm_entries):
        self.backend = backend
        self.npm_entries = npm_entries

    def progress(self, event):
        item = event.get("item")
        return (self.backend == "codex" and isinstance(item, dict)
                and event.get("type") in ("item.started", "item.updated", "item.completed")
                and item.get("type") in ("agent_message", "reasoning", "command_execution",
                                         "mcp_tool_call", "web_search"))

    def command(self, args, directory, run_directory, info, prefix, answer_path, RESPONSE_SCHEMA):
        backend = self.backend
        if backend == "claude":
            task = getattr(args, "task_mode", False)
            tools = "Read,Glob,Grep,Edit,Write,Bash" if task else "Read,Glob,Grep"
            command = prefix + ["-p", "--output-format", "json", "--json-schema", json.dumps(RESPONSE_SCHEMA),
                                "--tools", tools, "--allowedTools", tools,
                                "--permission-mode", "dontAsk", "--strict-mcp-config", "--mcp-config",
                                '{"mcpServers":{}}', "--max-turns", "80" if task else "12"]
            if getattr(args, "model", None):
                command += ["--model", args.model]
            if info.get("native_session_id"):
                command += ["--session-id" if task and getattr(args, "task_initial_session", False) else "--resume", info["native_session_id"]]
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


def probe(prefix, flag, cwd, *, env=None, timeout=10):
    try:
        result = subprocess.run(prefix + [flag], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=timeout, cwd=cwd, env=env, **processes.launch_options())
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


def records(path, *, plain_diagnostics=False):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()
            and (not plain_diagnostics or line.lstrip().startswith("{"))]
    if not rows or any(not isinstance(row, dict) for row in rows):
        chat.fail(f"invalid CLI JSONL output; see {path}")
    return rows


def has_text(value):
    return isinstance(value, str) and bool(value)


def message_progress(event):
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if event.get("type") not in ("assistant", "user") or not isinstance(content, list):
        return False
    parts = [part for part in content if isinstance(part, dict)]
    if event["type"] == "user":
        return any(part.get("type") == "tool_result" for part in parts)
    return any(part.get("type") == "tool_use" or has_text(part.get("text")) or has_text(part.get("thinking"))
               for part in parts)


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
    def progress(event):
        if event.get("type") in ("tool_execution_start", "tool_execution_update", "tool_execution_end"):
            return True
        delta = event.get("assistantMessageEvent")
        return (event.get("type") == "message_update" and isinstance(delta, dict)
                and delta.get("type") in ("text_delta", "thinking_delta", "toolcall_delta")
                and has_text(delta.get("delta")))

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

    @staticmethod
    def progress(event):
        part = event.get("part")
        return isinstance(part, dict) and (
            event.get("type") == "tool_use" or
            event.get("type") == "text" and has_text(part.get("text"))
        )

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        match = re.search(r"\b([12])\.\d+\.\d+", probe(prefix, "--version", args.cwd))
        if not match:
            chat.fail("supported OpenCode version not detected (requires run JSON mode in 1.x or 2.x)")
        major = int(match.group(1))
        readonly = {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow", "list": "allow"}
        # A separate agent prevents built-in build/plan permissions overriding
        # the discussion tool allowlist. This is per-process, never saved globally.
        agent = {"mode": "primary", "description": "Read-only Meet participant", "permission": readonly}
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


class DeepSeek:
    prompt_schema = True
    owned_process = True
    supports_web_search = True
    npm_entries = ("@deepseek-ai/dsh/lib/bin.js",)
    version = "0.2.2-rc.5"
    # IDs from the supported release's dsh-base bundle. Keep its file search
    # and reads but drop shell, delegation, writes and interactive workflows.
    disabled = (
        "tool-bash", "tool-pwsh", "tool-jobs", "tool-working-directory", "tool-skill",
        "tool-plugin-manager", "tool-agent-team", "tool-subagent", "tool-subagent-fork",
        "tool-subagent-control", "tool-workflow", "tool-goal", "tool-todo", "plan-mode",
        "tool-executor-ptc", "mcp-resources",
    )

    @staticmethod
    def progress(event):
        return event.get("type") == "text" and has_text(event.get("text"))

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        require_version(prefix, args.cwd, "dsh", self.version)
        overlay = [{"id": row, "disabled": True} for row in self.disabled]
        overlay.append({"id": "tool-fs", "config": {"write": False, "edit": False, "applyPatch": False}})
        overlay.append({"id": "tool-web", "disabled": not getattr(args, "web_search", False),
                        "config": {"fetch": True, "searchTimeoutMs": 60000}})
        if getattr(args, "model", None):
            overlay.append({"id": "agent-default-model", "config": {"provider": "deepseek-official", "model": args.model}})
        patch = run_directory / "dsh-meeting.patch.yml"
        # JSON is valid YAML. Serialize model IDs as values, never patch syntax.
        write_json(patch, overlay)
        command = prefix + ["--profile", "headless", "--patch", str(patch), "--json",
                            "--permission-mode", "read-only", "--approval-policy", "never"]
        if info.get("native_session_id"):
            command += ["--session-id", info["native_session_id"]]
        environment = {**os.environ, "DSH_HOME": str(directory / "dsh-home"), "DSH_PERMISSION_MODE": "read-only"}
        return command + ["-"], environment

    def parse(self, output_path, answer_path, directory, info):
        rows = records(output_path)
        session = session_ids(rows, "sessionId", "session")
        final = rows[-1]
        reason = final.get("reason")
        if (any(row.get("type") in ("error", "final") for row in rows[:-1])
                or final.get("type") != "final" or final.get("sessionId") != session
                or not isinstance(reason, dict) or reason.get("kind") != "completed"
                or not isinstance(final.get("text"), str)):
            chat.fail(f"DSH did not complete a successful response for this session; see {output_path}")
        return response(final["text"]), session


def require_version(prefix, cwd, name, version, *, timeout=10):
    reported = probe(prefix, "--version", cwd, timeout=timeout).strip()
    if reported != version:
        chat.fail(f"{name} adapter requires CLI version {version}; installed version is {reported!r}")


class Qwen:
    prompt_schema = True
    owned_process = True
    npm_entries = ("@qwen-code/qwen-code/cli-entry.js",)
    version = "0.28.0"
    progress = staticmethod(message_progress)
    # --safe-mode ignores --core-tools. Exclude the supported version's
    # built-ins other than read_file, grep_search, glob and list_directory.
    excluded = """
        exec edit write_file zoom_image run_shell_command todo_write save_memory
        manage_memory search_memory agent skill exit_plan_mode enter_plan_mode
        web_fetch web_search image_gen lsp ask_user_question cron_create cron_list
        cron_delete autofix_pr loop_wakeup create_sub_session list_agents task_stop
        task_create task_update task_list team_create team_delete team_plan_approval
        request_shutdown send_message structured_output monitor notebook_edit
        tool_call tool_search read_mcp_resource advisor enter_worktree exit_worktree
        workflow artifact record_artifact record_source report_findings get_goal
        update_goal omni_downsample_image omni_downscale_video omni_downsample_audio
        omni_extract_keyframes omni_extract_audio omni_clip_video omni_convert_image
        omni_transcribe_audio omni_clip_image omni_clip_audio omni_caption_image
        omni_caption_audio omni_ocr_image omni_understand_video_segments
        omni_recall_media_memory propose_goal display_image
    """

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        require_version(prefix, args.cwd, "qwen", self.version)
        command = prefix + ["--safe-mode", "--chat-recording", "--approval-mode", "default", "--input-format", "text",
                            "--output-format", "stream-json", "--exclude-tools", ",".join(self.excluded.split())]
        if info.get("native_session_id"):
            command += ["--resume", info["native_session_id"]]
        if getattr(args, "model", None):
            command += ["--model", args.model]
        return command, {**os.environ, "QWEN_RUNTIME_DIR": str(directory / "qwen-runtime")}

    def parse(self, output_path, answer_path, directory, info):
        rows = records(output_path)
        terminals = [row for row in rows if row.get("type") == "result"]
        if (len(terminals) != 1 or any(row.get("type") == "error"
                or row.get("subtype") == "session_recording_degraded" for row in rows)):
            chat.fail(f"Qwen reported an incomplete or unrecorded response; see {output_path}")
        final = terminals[0]
        session = session_ids([final], "session_id")
        if (final.get("subtype") != "success" or final.get("is_error") is not False
                or not isinstance(final.get("result"), str)):
            chat.fail(f"Qwen did not complete a successful response; see {output_path}")
        starts = [row for row in rows if row.get("type") == "system" and row.get("subtype") == "session_start"]
        if starts and session_ids(starts, "session_id") != session:
            chat.fail("Qwen reported inconsistent session IDs")
        return response(final["result"]), session


class Qoder:
    prompt_schema = True
    owned_process = True
    npm_entries = ("@qoder-ai/qodercli/bundle/qodercli.js",)
    node_scripts = (".js",)
    version = "1.1.93"
    progress = staticmethod(message_progress)
    tools = ("Read", "Glob", "Grep", "WebSearch", "WebFetch")

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        require_version(prefix, args.cwd, "Qoder", self.version, timeout=25)
        command = prefix + ["-p", "--input-format", "text", "--output-format", "stream-json",
                            "--tools", *self.tools, "--permission-mode", "dont_ask",
                            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                            "--setting-sources", "user", "--settings",
                            '{"disableAllHooks":true,"skills":{"enabled":false,"loadFromAgentsDirectory":false}}']
        if info.get("native_session_id"):
            command += ["--resume", info["native_session_id"]]
        if getattr(args, "model", None):
            command += ["--model", args.model]
        return command, None

    def parse(self, output_path, answer_path, directory, info):
        rows = records(output_path)
        final = rows[-1]
        if (any(row.get("type") in ("result", "error") for row in rows[:-1])
                or final.get("type") != "result" or final.get("subtype") != "success"
                or final.get("is_error") is not False or final.get("error_code")
                or final.get("deferred_tool_use")
                or final.get("terminal_reason") not in (None, "completed")
                or not isinstance(final.get("result"), str)):
            chat.fail(f"Qoder did not complete a successful response; see {output_path}")
        session = session_ids(rows, "session_id")
        starts = [row for row in rows if row.get("type") == "system" and row.get("subtype") == "init"]
        if (len(starts) != 1 or starts[0].get("session_id") != session
                or starts[0].get("permissionMode") != "dontAsk"
                or starts[0].get("mcp_servers") != []
                or not isinstance(names := starts[0].get("tools"), list)
                or any(name not in self.tools for name in names)):
            chat.fail(f"Qoder did not report the expected read-only tool configuration; see {output_path}")
        return response(final["result"]), session


class Hermes:
    prompt_schema = True
    owned_process = True
    # This release runs chat locally in the subprocess. Later gateway-backed
    # releases can keep a turn running when the CLI disconnects.
    version = "0.21.5"

    @staticmethod
    def progress(event):
        return (event.get("type") == "text" and has_text(event.get("text"))
                or event.get("type") in ("tool_use", "tool_result") and has_text(event.get("name")))

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "HERMES_ENABLE_PROJECT_PLUGINS": "0"}
        reported = probe(prefix, "--version", args.cwd, env=environment)
        if not re.search(rf"(?m)^Hermes Agent v{re.escape(self.version)}(?:\s|$)", reported):
            chat.fail(f"Hermes adapter requires the Hermes Agent {self.version} CLI")
        # Hermes groups file reads and writes together in its file toolset.
        command = prefix + ["chat", "--query-file", "-", "--format", "stream-json",
                            "--toolsets", "web", "--ignore-rules"]
        if info.get("native_session_id"):
            command += ["--resume", info["native_session_id"]]
        if getattr(args, "model", None):
            command += ["--model", args.model]
        return command, environment

    def parse(self, output_path, answer_path, directory, info):
        # This CLI prints some native startup warnings to stdout even in
        # stream-json mode. Keep them in the log, outside the JSONL protocol.
        rows = records(output_path, plain_diagnostics=True)
        final = rows[-1]
        if (any(row.get("type") in ("result", "error") for row in rows[:-1])
                or final.get("type") != "result" or type(final.get("exit_code")) is not int
                or final["exit_code"] != 0 or final.get("error") or not isinstance(final.get("text"), str)):
            chat.fail(f"Hermes did not complete a successful response; see {output_path}")
        starts = [row for row in rows if row.get("type") == "system" and row.get("subtype") == "init"]
        if len(starts) != 1 or starts[0].get("session_id") != final.get("session_id"):
            chat.fail(f"Hermes returned inconsistent native session IDs; see {output_path}")
        session = session_ids([final], "session_id")
        if any(row.get("type") == "tool_use" and row.get("name") not in ("web_search", "web_extract")
               for row in rows):
            chat.fail(f"Hermes used a tool outside the web toolset; see {output_path}")
        return response(final["text"]), session


class Antigravity:
    prompt_schema = True
    owned_process = True
    npm_entries = ()
    cli = "agy"

    @staticmethod
    def progress(event):
        step = event.get("step_update")
        return event.get("event") == "step_update" and isinstance(step, dict) and (
            step.get("step_type") in ("agent_response", "agent_thought") and has_text(step.get("text_delta"))
            or step.get("state") == "DONE" and has_text(step.get("tool_name"))
        )

    @staticmethod
    def agent_name(directory):
        return "agent-meet-" + uuid.uuid5(uuid.NAMESPACE_URL, directory.as_uri()).hex[:12]

    def workspace(self, directory):
        # CLI custom agents are discovered by name. Keep the definition in
        # the room's data and add the original project as a workspace folder.
        root = directory / "agy-workspace"
        agents = root / ".agents" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        agent = self.agent_name(directory)
        manifest = (
            f"---\nname: {agent}\n"
            "description: Read-only Agent-Meet participant\n"
            "mainAgent: true\nsubagent: false\ncommandExecutionPolicy: off\n"
            "tools: [view_file, search_web, finish]\n"
            "---\n"
            "Evaluate the meeting brief and evidence using only read-only tools.\n"
        )
        definition = agents / (agent + ".md")
        definition.write_text(manifest, encoding="utf-8")
        return root

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        command = prefix + ["--input-format", "stream-json", "--output-format", "stream-json",
                            "--disable-slash-commands", "--agent", self.agent_name(directory),
                            "--add-dir", args.cwd, "--log-file", str(run_directory / "agy.log")]
        if info.get("native_session_id"):
            command += ["--conversation", info["native_session_id"]]
        if getattr(args, "model", None):
            command += ["--model", args.model]
        return command, None

    @staticmethod
    def encode_prompt(prompt):
        return json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"

    def started_session(self, output_path, directory):
        # A timed-out turn can already have a valid, resumable conversation.
        # Read only the complete startup frame, even if the stream ends mid-line.
        try:
            with output_path.open("rb") as output:
                line = output.readline(64 * 1024)
            if not line.endswith(b"\n"):
                return None
            start = json.loads(line.decode("utf-8-sig"))
            if not isinstance(start, dict) or start.get("event") != "init":
                return None
            init = start.get("init")
            session = start.get("conversation_id")
            if isinstance(init, dict) and init.get("agent") == self.agent_name(directory) and isinstance(session, str):
                if str(uuid.UUID(session)) == session:
                    return session
        except (OSError, ValueError):
            pass
        return None

    def parse(self, output_path, answer_path, directory, info):
        rows = records(output_path)
        start, last = rows[0], rows[-1]
        final = last.get("result")
        if (last.get("event") != "result" or not isinstance(final, dict)
                or final.get("status") != "SUCCESS" or final.get("error")
                or any(row.get("event") in ("result", "error") for row in rows[:-1])):
            chat.fail(f"Antigravity did not complete a successful response; see {output_path}")
        init = start.get("init")
        if (start.get("event") != "init" or not isinstance(init, dict)
                or init.get("agent") != self.agent_name(directory)
                or any(row.get("event") == "init" for row in rows[1:])):
            chat.fail(f"Antigravity did not select the meeting's read-only agent; see {output_path}")
        session = session_ids([start, final], "conversation_id")
        if start.get("conversation_id") != session or final.get("conversation_id") != session:
            chat.fail(f"Antigravity did not confirm its native conversation ID; see {output_path}")
        if final.get("finished_reason") == "print_timeout":
            raise chat.CallTimeout(f"Antigravity CLI reached its own print timeout; see {output_path}",
                                   code="backend_timeout")
        if not isinstance(final.get("response"), str):
            chat.fail(f"Antigravity did not complete a successful response; see {output_path}")
        return response(final["response"]), session


class ZCodeConnection:
    """One stdio connection and one correlated meeting turn."""

    def __init__(self, process, log, on_progress):
        self.process = process
        self.log = log
        self.on_progress = on_progress
        self.request_id = 0
        self.session = None
        self.input_id = None
        self.turn_id = None
        self.terminal = None

    def send(self, message):
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def receive(self):
        limit = 8 * 1024 * 1024
        raw = self.process.stdout.readline(limit + 1)
        if not raw:
            chat.fail("ZCode closed its protocol before finishing; see the CLI logs")
        self.log.write(raw)
        self.log.flush()
        if len(raw) > limit or not raw.endswith(b"\n"):
            chat.fail("ZCode returned an oversized or incomplete protocol message")
        row = json.loads(raw)
        if not isinstance(row, dict):
            chat.fail("ZCode returned an invalid protocol message")
        if "method" in row and "id" in row:
            if row["method"] != "session/requestRuntimePreferences":
                chat.fail("ZCode requested an interactive action in a read-only meeting turn")
            self.send({"id": row["id"], "result": {
                "nativeSearchEnhancementsEnabled": False, "toolSearchMode": "off", "memoryEnabled": False,
                "subagentRuntimeConfigEnabled": False, "appControlEnabled": False,
                "askUserQuestionAutoResolutionEnabled": False,
            }})
        event = row.get("params")
        if (self.input_id and row.get("method") == "session/event"
                and isinstance(event, dict) and event.get("sessionId") == self.session):
            self.on_event(event)
        return row

    def on_event(self, event):
        kind, payload = event.get("type"), event.get("payload")
        if kind in ("permission.requested", "userInput.requested", "session.closed"):
            chat.fail("ZCode could not complete this read-only meeting turn")
        if not isinstance(payload, dict):
            return
        same_input = payload.get("inputId") == self.input_id
        if kind == "turn.started" and same_input:
            self.turn_id = event.get("turnId")
        same_turn = self.turn_id and event.get("turnId") == self.turn_id
        if kind not in ("turn.completed", "turn.failed"):
            if same_turn and (kind == "tool.updated" or
                              kind in ("model.streaming", "part.delta") and has_text(payload.get("delta"))):
                self.on_progress()
            return
        if same_input or (payload.get("inputId") is None and same_turn):
            if kind != "turn.completed" or payload.get("resultType") != "success":
                chat.fail("ZCode reported an unsuccessful meeting turn; see the CLI logs")
            if self.terminal is not None or not isinstance(payload.get("response"), str):
                chat.fail("ZCode returned an invalid terminal response")
            self.terminal = payload["response"]

    def request(self, method, params):
        self.request_id += 1
        self.send({"id": self.request_id, "method": method, "params": params})
        while True:
            row = self.receive()
            if row.get("id") == self.request_id:
                if "error" in row or not isinstance(row.get("result"), dict):
                    chat.fail(f"ZCode {method} failed; see the CLI logs")
                return row["result"]


class ZCode:
    prompt_schema = True
    owned_process = True
    node_scripts = (".cjs", ".mjs")
    npm_entries = ()
    version = "0.17.1"

    def command(self, args, directory, run_directory, info, prefix, answer_path, schema):
        require_version(prefix, args.cwd, "ZCode", self.version)
        storage = directory / "zcode-runtime"
        storage.mkdir(exist_ok=True)
        environment = {**os.environ, "ZCODE_STORAGE_DIR": str(storage),
                       "ZCODE_SESSION_DB_PATH": str(storage / "sessions.sqlite"),
                       "ZCODE_LOG_DIR": str(storage / "logs")}
        return prefix + ["app-server", "--stdio", "--cwd", args.cwd], environment

    def exchange(self, args, process, source, output, info, on_progress):
        connection = ZCodeConnection(process, output, on_progress)
        expected = info.get("native_session_id")
        params = {"workspace": {"workspacePath": args.cwd, "workspaceKey": args.cwd},
                  "toolAllowlist": ["Read", "Glob", "Grep"]}
        model = getattr(args, "model", None)
        selection = None
        if model:
            provider, slash, picker_value = model.partition("/")
            model_id, separator, reasoning = picker_value.partition("$")
            if not slash or not provider.strip() or not model_id.strip() or (separator and not reasoning.strip()):
                chat.fail("ZCode model must use providerId/modelId with an optional $reasoningLevel")
            selection = {"providerId": provider, "modelId": model_id}
            if separator:
                selection["options"] = {"reasoningLevel": reasoning}
        if expected:
            params["sessionId"] = expected
            snapshot = connection.request("session/resume", params)
        else:
            params.update(mode="plan", persistence="immediate", titleGenerationEnabled=False)
            if selection and "options" in selection:
                params["model"] = selection
            snapshot = connection.request("session/create", params)
        session = snapshot.get("session")
        if not isinstance(session, dict):
            chat.fail("ZCode returned an invalid session snapshot")
        session_id = session_ids([session], "sessionId")
        if expected and session_id != expected:
            chat.fail("ZCode resumed a different native session")
        connection.session = session_id
        if selection and not expected:
            if "options" not in selection:
                available = snapshot.get("settings", {}).get("model", {}).get("available", [])
                candidate = next((item for item in available if item.get("ref") == selection), None)
                default = (candidate or {}).get("reasoning", {}).get("defaultLevel")
                if not isinstance(default, str) or not default:
                    chat.fail("ZCode model selection needs a supported $reasoningLevel")
                selection["options"] = {"reasoningLevel": default}
            # Creation's legacy model setter flattens options. Use the typed
            # setter so the selected reasoning level is persisted too.
            connection.request("session/setModel", {"sessionId": session_id, "model": selection,
                               "persistAsWorkspaceLastUsed": False})
        # ZCode 0.17.1 represents Plan as a separate flag. The legacy setter
        # enables it while the returned snapshot still shows the base mode.
        snapshot = connection.request("session/setMode", {"sessionId": session_id, "mode": "plan"})
        session = snapshot.get("session")
        if (not isinstance(session, dict) or session.get("sessionId") != session_id
                or session.get("mode") not in ("build", "plan")):
            chat.fail("ZCode did not establish a read-only plan session")
        subscription = connection.request("session/subscribe", {"sessionId": session_id,
                                          "deliveryKind": "web-remote-replayable"})
        if subscription.get("sessionId") != session_id:
            chat.fail("ZCode subscribed to a different native session")
        connection.input_id = str(uuid.uuid4())
        sent = connection.request("session/send", {"sessionId": session_id, "inputId": connection.input_id,
                                    "content": source.read().decode("utf-8")})
        if sent.get("accepted") is not True or sent.get("sessionId") != session_id:
            chat.fail("ZCode did not accept the input for this session")
        while connection.terminal is None:
            connection.receive()
        result = response(connection.terminal)
        connection.input_id = None
        if connection.request("session/close", {"sessionId": session_id}).get("closed") is not True:
            chat.fail("ZCode did not release its session after the turn")
        process.stdin.close()
        while chunk := process.stdout.read(65536):
            output.write(chunk)
        return result, session_id


REGISTRY = {
    "claude": Legacy("claude", ("@anthropic-ai/claude-code/cli.js",)),
    "codex": Legacy("codex", ("@openai/codex/bin/codex.js",)),
    "pi": Pi(),
    "opencode": OpenCode(),
    "dsh": DeepSeek(),
    "qwen": Qwen(),
    "zcode": ZCode(),
    "hermes": Hermes(),
    "qoder": Qoder(),
    "antigravity": Antigravity(),
}
BACKENDS = tuple(REGISTRY)


def get(backend):
    if backend not in REGISTRY:
        chat.fail("unsupported agent backend; choose " + ", ".join(BACKENDS))
    return REGISTRY[backend]


def default_cli(backend):
    return getattr(get(backend), "cli", backend)
