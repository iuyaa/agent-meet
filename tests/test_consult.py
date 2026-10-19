import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_peer import FAKE_CLAUDE, SCRIPTS
import peer


@unittest.skipIf(os.name == "nt", "CLI fixture uses a Unix executable shebang")
class ConsultationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "项目 空格"
        self.project.mkdir()
        self.room = self.root / "主会话.sqlite"
        self.cli = self.root / "fake claude"
        self.cli.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.cli.chmod(0o755)
        self.briefing = {"question": "讨论 SQLite 写入方案，不要重新讨论已否决的方案。",
                         "goal": "结合已有决策验证方案", "current_view": "我认为短事务适合第一版。",
                         "constraints": ["不改业务代码", "保留当前 Codex 长对话"],
                         "decisions": ["第一版仅在本机运行"],
                         "rejected_options": ["否决共享 JSON 文件：并发写入可能覆盖"],
                         "code_references": ["src/storage.py:20"], "unknowns": ["峰值负载未测量"]}
        self.briefing_path = self.root / "context.json"
        self.briefing_path.write_text(json.dumps(self.briefing, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, script, command, *args, ok=True):
        run = subprocess.run([sys.executable, str(SCRIPTS / script), command, "--room", str(self.room), *map(str, args)],
                             capture_output=True, text=True, encoding="utf-8", timeout=10)
        output = run.stdout if run.returncode == 0 else run.stderr
        self.assertNotIn("Traceback", output)
        result = json.loads(output)
        self.assertEqual(run.returncode, 0 if ok else 1, result)
        return result

    def consult(self, command, *args, **kwargs):
        return self.command("consult.py", command, *args, **kwargs)

    def chat(self, command, *args, **kwargs):
        return self.command("chat.py", command, *args, **kwargs)

    def initialize(self, **kwargs):
        return self.consult("init", "--cwd", self.project, "--briefing-file", self.briefing_path,
                            "--cli", self.cli, **kwargs)

    def reply(self, request="claude-1", **kwargs):
        return self.consult("reply", "--request-id", request, **kwargs)

    def calls(self):
        path = self.project / "fake-cli-calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def main_message(self, request="main-2"):
        return self.chat("send", "--as", "codex", "--request-id", request,
                         "--text", "请结合之前否决共享 JSON 的原因，再检查事务边界。")

    def test_initialization_keeps_existing_main_and_records_complete_briefing(self):
        initialized = self.initialize()
        self.assertEqual(initialized["mode"], "existing-main")
        self.assertEqual(initialized["briefing"], self.briefing)
        self.assertEqual(initialized["status"]["message_count"], 1)
        self.assertIsNone(initialized["model"]["native_session_id"])
        self.assertEqual(self.calls(), [])
        self.assertIn("否决共享 JSON", Path(initialized["briefing_file"]).read_text(encoding="utf-8"))
        self.assertTrue(self.initialize()["already_initialized"])
        self.briefing["decisions"].append("新增约束，不应混入旧讨论")
        self.briefing_path.write_text(json.dumps(self.briefing), encoding="utf-8")
        self.initialize(ok=False)

    def test_reply_returns_once_and_followup_resumes_claude_with_context(self):
        self.initialize()
        first = self.reply()
        self.assertEqual(first["event"]["sender"], "claude")
        self.assertEqual(first["event"]["kind"], "message")
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(first["model"]["state"], "idle")
        self.assertEqual(first["status"]["next_speaker"], "codex")
        self.reply("before-main-speaks", ok=False)
        self.assertEqual(len(self.calls()), 1)
        self.main_message()
        second = self.reply("claude-2")
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--resume", calls[0]["argv"])
        self.assertIn("--resume", calls[1]["argv"])
        self.assertEqual(calls[0]["context"]["briefing"], self.briefing)
        self.assertEqual([e["id"] for e in calls[1]["context"]["new_events"]], [2, 3])
        self.assertEqual(second["model"]["native_session_id"], first["model"]["native_session_id"])
        self.assertNotIn("exec", calls[0]["argv"])
        self.assertFalse(Path(str(self.room) + ".job").exists())
        self.assertFalse(peer.paths(self.room, "codex").exists())

    def test_successful_retry_does_not_call_model_or_move_context_backwards(self):
        self.initialize()
        first = self.reply()
        replay = self.reply()
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["event"]["id"], first["event"]["id"])
        self.main_message()
        second = self.reply("claude-2")
        old_replay = self.reply()
        self.assertEqual(old_replay["model"]["read_cursor"], second["model"]["read_cursor"])
        self.assertEqual(len(self.calls()), 2)

    def test_original_main_proposes_and_claude_reviews(self):
        self.initialize()
        self.reply()
        proposal = self.root / "conclusion.json"
        proposal.write_text(json.dumps({"summary": "使用短事务并保留负载验证事项", "agreements": ["本地第一版使用 SQLite"],
                                        "disagreements": [], "open_questions": ["峰值负载"],
                                        "evidence_message_ids": [1, 2]}, ensure_ascii=False), encoding="utf-8")
        assessment = self.root / "assessment.json"
        assessment.write_text(json.dumps({"decision": "conclude", "reason": "双方意见和未验证事项已明确，可以提交记录审核",
                                          "blocking_questions": [], "accepted_uncertainties": ["负载尚未验证"],
                                          "next_steps": [], "evidence_message_ids": [1, 2]}), encoding="utf-8")
        self.chat("assess", "--as", "codex", "--request-id", "ready", "--file", assessment)
        self.chat("propose", "--as", "codex", "--request-id", "main-conclusion", "--file", proposal)
        reviewed = self.reply("claude-review")
        self.assertEqual(reviewed["event"]["kind"], "review")
        self.assertEqual(self.calls()[-1]["context"]["allowed_actions"], ["review"])
        self.assertEqual(reviewed["status"]["conclusion_status"], "confirmed")
        self.assertTrue(self.reply("claude-review")["duplicate"])
        self.reply("after-close", ok=False)
        self.chat("export", "--output", self.root / "report.md")

    def test_failed_call_preserves_main_context_and_never_creates_a_reply(self):
        self.initialize()
        (self.project / "fake-mode.txt").write_text("fail")
        self.reply(ok=False)
        state = self.consult("status")
        self.assertEqual(state["briefing"], self.briefing)
        self.assertEqual(state["model"]["state"], "failed")
        self.assertEqual(state["status"]["message_count"], 1)
        self.reply(ok=False)
        self.assertEqual(len(self.calls()), 1)
        (self.project / "fake-mode.txt").write_text("ok")
        self.reply("explicit-retry")
        self.assertEqual(len(self.calls()), 2)

    def test_resumption_does_not_silently_switch_claude_session(self):
        self.initialize()
        original = self.reply()["model"]["native_session_id"]
        self.main_message()
        self.cli.write_text(FAKE_CLAUDE.replace("11111111-1111-4111-8111-111111111111",
                                               "33333333-3333-4333-8333-333333333333"), encoding="utf-8")
        failed = self.reply("changed-session", ok=False)
        self.assertIn("different session", failed["error"])
        current = self.consult("status")
        self.assertEqual(current["model"]["native_session_id"], original)
        self.assertEqual(current["status"]["message_count"], 3)

    def test_missing_briefing_fields_and_cli_fail_before_room_creation(self):
        del self.briefing["rejected_options"]
        self.briefing_path.write_text(json.dumps(self.briefing), encoding="utf-8")
        self.initialize(ok=False)
        self.assertFalse(self.room.exists())
        self.briefing["rejected_options"] = []
        self.briefing_path.write_text(json.dumps(self.briefing), encoding="utf-8")
        self.cli.unlink()
        self.initialize(ok=False)
        self.assertFalse(self.room.exists())

    def test_background_worker_cannot_take_same_identity_during_foreground_call(self):
        self.initialize()
        (self.project / "fake-mode.txt").write_text("delay")
        process = subprocess.Popen([sys.executable, str(SCRIPTS / "consult.py"), "reply", "--room", str(self.room),
                                    "--request-id", "pending", "--turn-timeout", "1"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic() + 3
            while not self.calls() and time.monotonic() < until:
                time.sleep(0.05)
            self.assertTrue(self.calls())
            with self.assertRaises(peer.AlreadyRunning):
                with peer.participant_lock(peer.paths(self.room, "claude")):
                    pass
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_ready_response_can_commit_without_another_model_call(self):
        self.initialize()
        self.reply()
        root = Path(str(self.room) + ".consult")
        digest = hashlib.sha256("claude-1".encode()).hexdigest()
        # Simulate an interrupted write between saving a response and its DB commit.
        import sqlite3
        with sqlite3.connect(self.room) as connection:
            connection.execute("DELETE FROM events WHERE sender = 'claude'")
        cached = json.loads((root / (digest + ".json")).read_text())
        cached["phase"] = "response_ready"
        peer.write_json(root / (digest + ".json"), cached)
        state = json.loads((root / "status.json").read_text())
        state.update(read_cursor=0, completed_turn=0, native_session_id=None)
        peer.write_json(root / "status.json", state)
        restored = self.reply()
        self.assertFalse(restored["duplicate"])
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(restored["status"]["message_count"], 2)


if __name__ == "__main__":
    unittest.main()
