import concurrent.futures
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "chat.py"


class DiscussionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.room = self.root / "路径有空格 discussion.sqlite"
        self.cli("create", "--topic", "第一版用什么数据库？", "--max-messages", "4")
        self.cli("join", "--as", "codex")
        self.cli("join", "--as", "claude")

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, command, *args, ok=True):
        run = subprocess.run([sys.executable, str(SCRIPT), command, "--room", str(self.room), *map(str, args)],
                             capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertNotIn("Traceback", run.stderr)
        value = json.loads(run.stdout if run.returncode == 0 else run.stderr)
        self.assertEqual(run.returncode, 0 if ok else 1, value)
        self.assertEqual(value["ok"], ok)
        return value

    def send(self, who, request_id, text="SQLite 适合本地场景。", **kwargs):
        return self.cli("send", "--as", who, "--request-id", request_id, "--text", text, **kwargs)

    def exchange(self):
        self.send("codex", "c1")
        self.send("claude", "a1", "同意本地使用 SQLite，跨机器场景需要另行评估。")

    def proposal(self, ids=None, who="codex", request="p1", **kwargs):
        data = {"summary": "本地第一版使用 SQLite，保留跨机器存储选型问题。",
                "agreements": ["本地第一版使用 SQLite。"],
                "disagreements": [], "open_questions": ["跨机器存储方案。"],
                "evidence_message_ids": [1, 2] if ids is None else ids}
        path = self.root / (request + ".json")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.cli("propose", "--as", who, "--request-id", request, "--file", path, **kwargs)

    def review(self, proposal, decision="accept", who="claude", request="r1", **kwargs):
        return self.cli("review", "--as", who, "--request-id", request,
                        "--proposal", proposal, "--decision", decision, "--text", "如实记录了双方意见。", **kwargs)

    def test_two_way_delivery_and_restart_replay(self):
        self.exchange()
        first = self.cli("read", "--as", "codex", "--after", 0)
        self.assertEqual([x["sender"] for x in first["events"]], ["codex", "claude"])
        self.assertEqual(first["next_after"], 2)
        self.cli("join", "--as", "codex")
        replay = self.cli("read", "--as", "codex", "--after", 0)
        self.assertEqual(first["events"], replay["events"])
        empty = self.cli("wait", "--as", "codex", "--after", 2, "--timeout", 0)
        self.assertTrue(empty["timed_out"])
        self.assertEqual(empty["next_after"], 2)

    def test_wait_wakes_on_peer_write_without_consuming_message(self):
        self.send("codex", "c1")
        process = subprocess.Popen([sys.executable, str(SCRIPT), "wait", "--room", str(self.room),
                                    "--as", "codex", "--after", "1", "--timeout", "3"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        timer = threading.Timer(0.2, lambda: self.send("claude", "a1"))
        timer.start()
        try:
            stdout, stderr = process.communicate(timeout=5)
        finally:
            timer.join()
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertEqual(process.returncode, 0, stderr)
        message = json.loads(stdout)["events"][0]
        self.assertEqual(message["sender"], "claude")
        self.assertEqual(self.cli("read", "--as", "codex", "--after", 1)["events"][0], message)

    def test_alternation_and_unknown_identity(self):
        self.send("claude", "a1", ok=False)
        self.send("codex", "c1")
        self.send("codex", "c2", ok=False)
        self.cli("join", "--as", "stranger", ok=False)
        self.send("stranger", "s1", ok=False)
        self.cli("send", "--as", "claude", "--request-id", "a1", "--reply-to", 999, "--text", "reply", ok=False)
        self.cli("send", "--as", "claude", "--request-id", "a1", "--reply-to", 1, "--text", "reply")

    def test_concurrent_identical_retries_are_one_event(self):
        def write(_):
            return self.send("codex", "same-request")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(4)))
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        self.assertEqual({r["event"]["id"] for r in results}, {1})
        self.assertEqual(self.cli("status")["status"]["message_count"], 1)
        self.send("codex", "same-request", "different body", ok=False)

    def test_concurrent_new_writes_obey_turn(self):
        def write(request):
            return subprocess.run([sys.executable, str(SCRIPT), "send", "--room", str(self.room),
                                   "--as", "codex", "--request-id", request, "--text", request],
                                  capture_output=True, text=True, timeout=5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["first", "second"]))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1])
        self.assertEqual(self.cli("status")["status"]["message_count"], 1)

    def test_budget_allows_finalization_and_retry_after_closed(self):
        self.exchange()
        self.send("codex", "c2")
        self.send("claude", "a2")
        self.assertEqual(self.cli("status")["status"]["phase"], "summarizing")
        self.send("codex", "c3", ok=False)
        proposed = self.proposal()
        self.assertEqual(proposed["status"]["conclusion_status"], "unconfirmed")
        review = self.review(proposed["event"]["id"])
        self.assertEqual(review["status"]["close_reason"], "agreement")
        self.assertEqual(review["status"]["conclusion_status"], "confirmed")
        self.assertTrue(self.review(proposed["event"]["id"])["duplicate"])
        self.assertTrue(self.proposal()["duplicate"])
        self.send("codex", "after-closed", ok=False)

    def test_self_confirmation_and_nonexistent_evidence_rejected(self):
        self.send("codex", "c1")
        self.proposal(ids=[1], ok=False)
        self.send("claude", "a1")
        self.proposal(ids=[1, 999], ok=False)
        proposal = self.proposal()
        self.review(proposal["event"]["id"], who="codex", ok=False)
        self.send("codex", "c2", ok=False)

    def test_rejection_is_visible_and_revision_can_be_confirmed(self):
        self.exchange()
        proposed = self.proposal()
        rejected = self.review(proposed["event"]["id"], decision="reject")
        self.assertEqual(rejected["status"]["conclusion_status"], "disputed")
        self.assertEqual(rejected["status"]["phase"], "discussing")
        report = self.root / "disputed.md"
        self.cli("export", "--output", report)
        self.assertIn("另一方提出异议", report.read_text(encoding="utf-8"))
        revised = self.proposal(request="p2")
        self.review(proposed["event"]["id"], request="stale-review", ok=False)
        accepted = self.review(revised["event"]["id"], request="r2")
        self.assertEqual(accepted["status"]["conclusion_status"], "confirmed")

    def test_four_proposals_limit_preserves_disagreements(self):
        self.exchange()
        for index in range(4):
            proposal = self.proposal(request=f"p{index}")
            self.review(proposal["event"]["id"], decision="reject", request=f"r{index}")
        self.proposal(request="p5", ok=False)
        stopped = self.cli("stop", "--reason", "four disputed proposals")
        self.assertEqual(stopped["status"]["conclusion_status"], "disputed")

    def test_timeout_never_implies_agreement(self):
        self.exchange()
        self.proposal()
        with sqlite3.connect(self.room) as conn:
            conn.execute("UPDATE room SET discuss_until = ?, expires = ?", (time.time() - 20, time.time() - 10))
        result = self.cli("wait", "--as", "claude", "--after", 3, "--timeout", 3)
        self.assertEqual(result["status"]["close_reason"], "expired")
        self.assertEqual(result["status"]["conclusion_status"], "unconfirmed")
        self.review(3, ok=False)

    def test_discussion_deadline_keeps_review_window(self):
        self.exchange()
        with sqlite3.connect(self.room) as conn:
            conn.execute("UPDATE room SET discuss_until = ?, expires = ?", (time.time() - 1, time.time() + 30))
        self.assertEqual(self.cli("status")["status"]["phase"], "summarizing")
        self.send("codex", "too-late", ok=False)
        self.review(self.proposal()["event"]["id"])

    def test_stop_unblocks_wait_and_prevents_writes(self):
        self.exchange()
        self.cli("stop", "--reason", "用户要求停止")
        result = self.cli("wait", "--as", "codex", "--after", 2, "--timeout", 3)
        self.assertEqual(result["next_action"], "export")
        self.assertIn("用户要求停止", result["status"]["close_reason"])
        self.send("codex", "c2", ok=False)
        self.proposal(ok=False)

    def test_no_overwrite_export_and_multiline_round_trip(self):
        text = "多行消息\n包含 `代码`、$HOME、$(不要执行) 和 '引号'。"
        path = self.root / "message.txt"
        path.write_text(text, encoding="utf-8")
        self.cli("send", "--as", "codex", "--request-id", "file", "--text-file", path)
        self.assertEqual(self.cli("read", "--as", "claude")["events"][0]["body"], text)
        self.cli("create", "--topic", "cannot overwrite", ok=False)
        self.cli("export", "--output", self.room, ok=False)
        report = self.root / "report.md"
        self.cli("export", "--output", report)
        self.cli("export", "--output", report, ok=False)
        self.assertIn(text, report.read_text(encoding="utf-8"))
        self.assertIn("尚无结论", report.read_text(encoding="utf-8"))

    def test_bad_inputs_return_errors_without_tracebacks(self):
        self.cli("wait", "--as", "codex", "--timeout", "nan", ok=False)
        self.cli("read", "--as", "codex", "--after", -1, ok=False)
        self.send("codex", "blank", " ", ok=False)
        self.exchange()
        bad = self.root / "bad.json"
        bad.write_text('{"summary": 42}', encoding="utf-8")
        self.cli("propose", "--as", "codex", "--request-id", "bad", "--file", bad, ok=False)


if __name__ == "__main__":
    unittest.main()
