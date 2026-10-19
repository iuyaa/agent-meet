import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_peer import FAKE_CLAUDE, SCRIPTS
import peer

FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

context = json.loads(sys.stdin.read().split("Discussion data:\n", 1)[1])
with Path("fake-codex-calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "context": context}, ensure_ascii=False) + "\n")
mode_file = Path("codex-mode.txt")
mode = mode_file.read_text() if mode_file.exists() else "ok"
if mode == "fail":
    print("test Codex login failure", file=sys.stderr)
    sys.exit(9)
if mode == "delay":
    time.sleep(30)
empty = {"summary": "", "agreements": [], "disagreements": [], "open_questions": [], "evidence_message_ids": []}
allowed = context["allowed_actions"]
action = "send" if "send" in allowed else "propose" if "propose" in allowed else "review"
result = {"action": action, "text": "本地先用 SQLite；并发写入使用短事务。", "decision": "none", "conclusion": empty}
if action == "propose":
    result["text"] = ""
    result["conclusion"] = {"summary": "第一版用 SQLite，并以短事务处理并发。",
                            "agreements": ["本地使用 SQLite", "使用短事务"], "disagreements": [],
                            "open_questions": [], "evidence_message_ids": [e["id"] for e in context["new_events"] if e["kind"] == "message"]}
if action == "review":
    result["decision"] = "accept"
answer = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
answer.write_text("not JSON" if mode == "malformed" else json.dumps(result, ensure_ascii=False), encoding="utf-8")
if mode != "no-thread":
    print(json.dumps({"type": "thread.started", "thread_id": "22222222-2222-4222-8222-222222222222"}))
print(json.dumps({"type": "turn.failed" if mode == "turn-failed" else "turn.completed"}))
'''


@unittest.skipIf(os.name == "nt", "end-to-end fixtures use Unix executable shebangs")
class ManagedDiscussionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "项目 有空格"
        self.project.mkdir()
        self.room = self.root / "完整讨论.sqlite"
        self.codex = self.root / "fake codex"
        self.claude = self.root / "fake claude"
        for path, text in ((self.codex, FAKE_CODEX), (self.claude, FAKE_CLAUDE)):
            path.write_text(text, encoding="utf-8")
            path.chmod(0o755)

    def tearDown(self):
        if self.room.exists():
            self.call("stop")
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                current = self.call("status")
                if current["finished"] and all(p["state"] not in ("waiting", "running", "thinking") for p in current["peers"].values()):
                    break
                time.sleep(0.05)
        self.temp.cleanup()

    def call(self, command, *args, ok=True):
        run = subprocess.run([sys.executable, str(SCRIPTS / "discuss.py"), command,
                              "--room", str(self.room), *map(str, args)],
                             capture_output=True, text=True, encoding="utf-8", timeout=12)
        output = run.stdout.strip() if run.stdout.strip() else run.stderr.strip()
        if output.startswith('{"event": "started"'):
            output = output.split("\n", 1)[1]
        result = json.loads(output)
        self.assertEqual(run.returncode, 0 if ok else 1, result)
        self.assertNotIn("Traceback", run.stderr)
        return result

    def start(self, command="start", **kwargs):
        return self.call(command, "--cwd", self.project, "--topic", "无需复制邀请或手动继续，讨论 SQLite 并发。",
                         "--codex-cli", self.codex, "--claude-cli", self.claude,
                         "--max-messages", 4, **kwargs)

    def until_finished(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = self.call("status")
            if result["finished"]:
                return result
            time.sleep(0.05)
        self.fail("discussion did not finish: " + str(self.call("status")))

    def test_both_peers_finish_without_initiator_participation(self):
        self.start()
        result = self.until_finished()
        self.assertEqual(result["job"]["state"], "completed")
        self.assertEqual(result["status"]["conclusion_status"], "confirmed")
        self.assertEqual(result["status"]["message_count"], 4)
        report = Path(result["job"]["report_path"])
        self.assertTrue(report.exists())
        self.assertIn("双方已确认", report.read_text(encoding="utf-8"))
        calls = [json.loads(line) for line in (self.project / "fake-codex-calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 3)
        self.assertNotIn("resume", calls[0]["argv"])
        self.assertIn("resume", calls[1]["argv"])
        self.assertIn("read-only", calls[0]["argv"])
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", calls[0]["argv"])
        replay = self.start()
        self.assertTrue(replay["already_started"])
        self.assertEqual(report, Path(replay["job"]["report_path"]))
        different = self.root / "different-question.txt"
        different.write_text("这是另一个问题", encoding="utf-8")
        mismatch = self.call("start", "--cwd", self.project, "--topic-file", different, ok=False)
        self.assertIn("different topic", mismatch["error"])

    def test_foreground_run_returns_final_result_without_continue(self):
        result = self.start("run")
        self.assertTrue(result["finished"])
        self.assertEqual(result["job"]["state"], "completed")

    def test_failed_codex_stops_claude_and_exports_partial_record(self):
        (self.project / "codex-mode.txt").write_text("fail")
        # A very fast failure may be observed during start or by status after it.
        run = subprocess.run([sys.executable, str(SCRIPTS / "discuss.py"), "run", "--room", str(self.room),
                              "--cwd", str(self.project), "--topic", "failure test", "--codex-cli", str(self.codex),
                              "--claude-cli", str(self.claude)], capture_output=True, text=True, timeout=12)
        self.assertEqual(run.returncode, 1)
        result = self.until_finished()
        self.assertEqual(result["job"]["state"], "failed")
        self.assertIn("code 9", result["job"]["detail"])
        self.assertNotEqual(result["status"]["conclusion_status"], "confirmed")
        self.assertTrue(Path(result["job"]["report_path"]).exists())

    def test_missing_backend_is_detected_before_room_creation(self):
        self.claude.unlink()
        result = self.start(ok=False)
        self.assertIn("Claude CLI not found", result["error"])
        self.assertFalse(self.room.exists())

    def test_stop_cancels_running_pair_and_preserves_record(self):
        (self.project / "codex-mode.txt").write_text("delay")
        self.start()
        self.call("stop")
        result = self.until_finished()
        self.assertEqual(result["job"]["state"], "stopped")
        self.assertTrue(Path(result["job"]["report_path"]).exists())

    def test_codex_output_failures_are_not_successful_discussions(self):
        for mode in ("no-thread", "malformed", "turn-failed"):
            with self.subTest(mode=mode):
                self.room = self.root / (mode + ".sqlite")
                (self.project / "codex-mode.txt").write_text(mode)
                # Inspect status even if the failure reached startup readiness.
                subprocess.run([sys.executable, str(SCRIPTS / "discuss.py"), "start", "--room", str(self.room),
                                "--cwd", str(self.project), "--topic", "output failure", "--codex-cli", str(self.codex),
                                "--claude-cli", str(self.claude)], capture_output=True, text=True, timeout=12)
                result = self.until_finished()
                self.assertEqual(result["job"]["state"], "failed")
                self.assertEqual(result["status"]["message_count"], 0)


class CodexWrapperTests(unittest.TestCase):
    def test_windows_npm_codex_wrapper_uses_node_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wrapper = root / "codex.cmd"
            wrapper.write_text("do not execute batch")
            entry = root / "node_modules/@openai/codex/bin/codex.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("// fixture")
            with mock.patch.object(peer.shutil, "which", side_effect=[str(wrapper), "/path/node.exe"]):
                self.assertEqual(peer.cli_prefix("codex", "codex"), ["/path/node.exe", str(entry)])


if __name__ == "__main__":
    unittest.main()
