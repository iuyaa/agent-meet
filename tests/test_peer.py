import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import peer  # noqa: E402


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

prompt = sys.stdin.read()
context = json.loads(prompt.split("Discussion data:\n", 1)[1])
with Path("fake-cli-calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "context": context}, ensure_ascii=False) + "\n")
mode_file = Path("fake-mode.txt")
mode = mode_file.read_text() if mode_file.exists() else "ok"
if mode == "fail":
    print("Test authentication failure", file=sys.stderr)
    sys.exit(7)
if mode == "delay":
    time.sleep(30)
if mode == "malformed":
    print("not JSON")
    sys.exit(0)
if mode == "no-structured":
    print(json.dumps({"is_error": False, "result": "ordinary text"}))
    sys.exit(0)
if mode == "permission-denied":
    print(json.dumps({"permission_denials": [{"tool_name": "Read"}]}))
    sys.exit(0)
if mode == "no-session":
    print(json.dumps({"structured_output": {"action": "send", "text": "not recorded"}}))
    sys.exit(0)
allowed = context["allowed_actions"]
action = "review" if "review" in allowed else "send" if "send" in allowed else "propose"
empty = {"summary": "", "agreements": [], "disagreements": [], "open_questions": [], "evidence_message_ids": []}
result = {"action": action, "text": "需要考虑并发写入；同意采用短事务。", "decision": "none", "conclusion": empty}
if action == "review":
    result["decision"] = "accept"
if mode == "wrong-action":
    result["action"] = "review"
    result["decision"] = "accept"
print(json.dumps({"session_id": "11111111-1111-4111-8111-111111111111", "is_error": False,
                  "structured_output": result}, ensure_ascii=False))
'''


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "项目 有空格"
        self.project.mkdir()
        self.room = self.root / "讨论 有空格.sqlite"
        self.cli_path = self.root / "fake claude"
        self.cli_path.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.cli_path.chmod(0o755)
        self.chat("create", "--topic", "讨论 $(不执行) 和 '引号'，不要修改代码", "--max-messages", 4)
        self.chat("join", "--as", "codex")

    def tearDown(self):
        try:
            self.chat("stop", "--reason", "test cleanup")
            deadline = time.monotonic() + 5
            while self.status()["state"] in ("waiting", "thinking", "running") and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            self.temp.cleanup()

    def command(self, script, command, *args, ok=True):
        run = subprocess.run([sys.executable, str(SCRIPTS / script), command, "--room", str(self.room), *map(str, args)],
                             capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertNotIn("Traceback", run.stderr)
        value = json.loads(run.stdout if run.returncode == 0 else run.stderr)
        self.assertEqual(run.returncode, 0 if ok else 1, value)
        return value

    def chat(self, command, *args, **kwargs):
        return self.command("chat.py", command, *args, **kwargs)

    def managed(self, command, *args, **kwargs):
        return self.command("peer.py", command, "--as", "claude", *args, **kwargs)

    def start(self, **kwargs):
        return self.managed("start", "--cwd", self.project, "--cli", self.cli_path, **kwargs)

    def status(self):
        return self.managed("status")["peer"]

    def until(self, predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        self.fail("timed out waiting for runner state: " + str(self.status()))

    def opening(self):
        self.chat("send", "--as", "codex", "--request-id", "opening", "--text", "建议本地使用 SQLite。")

    def mode(self, value):
        (self.project / "fake-mode.txt").write_text(value)

    @unittest.skipIf(os.name == "nt", "test executable uses a Unix shebang; wrapper resolution is tested separately")
    def test_automatic_join_reply_resume_review_and_export(self):
        self.opening()
        self.start()
        self.until(lambda: self.chat("status")["status"]["message_count"] == 2)
        conclusion = self.root / "conclusion.json"
        conclusion.write_text(json.dumps({"summary": "本地使用 SQLite，使用短事务处理并发。",
                                          "agreements": ["使用 SQLite"], "disagreements": [],
                                          "open_questions": [], "evidence_message_ids": [1, 2]}, ensure_ascii=False), encoding="utf-8")
        self.chat("propose", "--as", "codex", "--request-id", "proposal", "--file", conclusion)
        self.until(lambda: self.chat("status")["status"]["conclusion_status"] == "confirmed")
        self.until(lambda: self.status()["state"] == "completed")
        calls = [json.loads(line) for line in (self.project / "fake-cli-calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--resume", calls[0]["argv"])
        self.assertIn("--resume", calls[1]["argv"])
        self.assertIn("Read,Glob,Grep", calls[0]["argv"])
        self.assertNotIn("--dangerously-skip-permissions", calls[0]["argv"])
        self.assertIn("$(不执行)", calls[0]["context"]["topic"])
        self.assertEqual(calls[1]["context"]["new_events"][0]["id"], 2)
        self.chat("export", "--output", self.root / "report.md")

    @unittest.skipIf(os.name == "nt", "test executable uses a Unix shebang")
    def test_start_is_idempotent_while_waiting(self):
        first = self.start()
        second = self.start()
        self.assertFalse(first["already_running"])
        self.assertTrue(second["already_running"])
        self.assertEqual(first["peer"]["run_id"], second["peer"]["run_id"])
        self.assertFalse((self.project / "fake-cli-calls.jsonl").exists())
        self.managed("stop")
        self.until(lambda: self.status()["state"] == "stopped")
        self.assertEqual(self.chat("status")["status"]["phase"], "discussing")

    def test_missing_cli_does_not_claim_join_or_request_invitation(self):
        response = self.managed("start", "--cwd", self.project, "--cli", "agent-chat-no-such-cli", ok=False)
        self.assertIn("Claude CLI not found", response["error"])
        self.assertNotIn("claude", self.chat("status")["status"]["joined"])

    @unittest.skipIf(os.name == "nt", "test uses Unix directory permissions")
    def test_unwritable_directory_is_not_reported_as_already_running(self):
        directory = peer.paths(self.room, "claude")
        directory.mkdir(parents=True)
        directory.chmod(0o500)
        try:
            response = self.start(ok=False)
            self.assertIn("Permission denied", response["error"])
            self.assertNotIn("claude", self.chat("status")["status"]["joined"])
        finally:
            directory.chmod(0o700)

    @unittest.skipIf(os.name == "nt", "test executable uses a Unix shebang")
    def test_backend_error_is_visible_without_inventing_a_reply(self):
        self.mode("fail")
        self.opening()
        self.start()
        self.until(lambda: self.status()["state"] == "failed")
        self.assertIn("code 7", self.status()["detail"])
        self.assertEqual(self.chat("status")["status"]["message_count"], 1)

    @unittest.skipIf(os.name == "nt", "test executable uses a Unix shebang")
    def test_malformed_response_and_permission_denial_are_errors(self):
        self.opening()
        for mode in ("malformed", "no-structured", "permission-denied", "no-session", "wrong-action"):
            with self.subTest(mode=mode):
                self.mode(mode)
                self.start()
                self.until(lambda: self.status()["state"] == "failed")
                self.assertEqual(self.chat("status")["status"]["message_count"], 1)

    @unittest.skipIf(os.name == "nt", "test executable uses a Unix shebang")
    def test_stopping_discussion_cancels_running_model(self):
        self.mode("delay")
        self.opening()
        self.start()
        self.until(lambda: self.status()["state"] == "thinking")
        self.chat("stop", "--reason", "用户停止")
        self.until(lambda: self.status()["state"] == "stopped")
        self.assertIsNone(self.status()["child_pid"])
        self.assertEqual(self.chat("status")["status"]["message_count"], 1)

    @unittest.skipIf(os.name == "nt", "test executable uses a Unix shebang")
    def test_model_turn_timeout_is_visible(self):
        self.mode("delay")
        self.opening()
        self.managed("start", "--cwd", self.project, "--cli", self.cli_path, "--turn-timeout", 1)
        self.until(lambda: self.status()["state"] == "failed")
        self.assertIn("timed out", self.status()["detail"])

    def test_windows_npm_wrapper_resolves_without_a_shell(self):
        wrapper = self.root / "claude.cmd"
        wrapper.write_text("do not execute batch")
        script = self.root / "node_modules/@anthropic-ai/claude-code/cli.js"
        script.parent.mkdir(parents=True)
        script.write_text("// test fixture")
        with mock.patch.object(peer.shutil, "which", side_effect=[str(wrapper), "/path/node.exe"]):
            self.assertEqual(peer.claude_prefix("claude"), ["/path/node.exe", str(script)])


if __name__ == "__main__":
    unittest.main()
