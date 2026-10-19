import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import chat
import peer
import view


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.room = self.root / "中文 空格.sqlite"
        self.chat("create", "--topic", "讨论实时页面")
        self.chat("join", "--as", "codex")
        self.chat("join", "--as", "claude")
        self.chat("send", "--as", "codex", "--request-id", "opening", "--text", "保留原会话 <script>bad()</script>")
        self.started = self.command("start")
        self.info = view.running(self.room)
        self.assertIsNotNone(self.info)
        self.origin = self.info["origin"]

    def tearDown(self):
        self.command("close")
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            info = view.read_json(view.directory(self.room) / "status.json")
            if info.get("state") == "closed":
                break
            time.sleep(0.05)
        self.temp.cleanup()

    def chat(self, command, *args):
        result = subprocess.run([sys.executable, str(SCRIPTS / "chat.py"), command,
                                 "--room", str(self.room), *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def command(self, command, room=None, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / "view.py"), command,
                                 "--room", str(room or self.room)], capture_output=True,
                                text=True, encoding="utf-8", timeout=12)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def http(self, path, method="GET", headers=None, auth=True):
        base = {"Authorization": "Bearer " + self.info["token"]} if auth else {}
        req = urllib.request.Request(self.origin + path, method=method, headers={**base, **(headers or {})})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_start_reuses_server_and_state_tracks_actual_events(self):
        duplicate = self.command("start")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["pid"], self.started["pid"])
        self.assertEqual(self.command("status")["url"], self.started["url"])
        before = json.loads(self.http("/api/state")[2])
        self.assertEqual(len(before["events"]), 1)
        self.chat("send", "--as", "claude", "--request-id", "reply", "--text", "可以查看真实发言。")
        after = json.loads(self.http("/api/state")[2])
        self.assertEqual([e["sender"] for e in after["events"]], ["codex", "claude"])
        self.assertIn("<script>", after["events"][0]["body"])
        self.assertNotIn("native_session_id", json.dumps(after))
        self.assertEqual(self.info["origin"].split(":")[1], "//127.0.0.1")
        if os.name != "nt":
            self.assertEqual((view.directory(self.room) / "status.json").stat().st_mode & 0o777, 0o600)

    def test_api_requires_token_and_valid_host_origin(self):
        self.assertEqual(self.http("/api/state", auth=False)[0], 401)
        self.assertEqual(self.http("/api/stop", "POST", auth=False)[0], 401)
        self.assertEqual(self.http("/api/state", headers={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.http("/api/state", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.http("/api/stop", "POST", headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertNotEqual(json.loads(self.http("/api/state")[2])["status"]["phase"], "closed")
        self.assertEqual(self.http("/api/state", headers={"Origin": self.origin})[0], 200)

    def test_static_assets_are_whitelisted_and_do_not_embed_room_data(self):
        for path in ("/", "/app.js", "/style.css"):
            code, headers, body = self.http(path, auth=False)
            self.assertEqual(code, 200)
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertNotIn(self.info["token"].encode(), body)
        self.assertNotIn("保留原会话".encode(), self.http("/", auth=False)[2])
        for path in ("/../scripts/view.py", "/scripts/view.py", "/%2e%2e/config.json", "/api/state?room=other"):
            self.assertEqual(self.http(path)[0], 404)

    def test_stop_closes_room_without_fabricating_agreement_and_export_downloads(self):
        code, _, body = self.http("/api/stop", "POST")
        self.assertEqual(code, 200)
        status = json.loads(body)["status"]
        self.assertEqual(status["phase"], "closed")
        self.assertEqual(status["conclusion_status"], "none")
        self.assertIn("用户从讨论页面停止", status["close_reason"])
        code, headers, body = self.http("/api/export")
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        report = body.decode("utf-8")
        self.assertIn("尚无结论", report)
        self.assertIn("保留原会话 <script>bad()</script>", report)
        self.assertEqual(len(json.loads(self.http("/api/state")[2])["events"]), 1)

    def test_missing_room_does_not_create_server_or_database(self):
        missing = self.root / "missing.sqlite"
        failed = self.command("start", room=missing, ok=False)
        self.assertIn("not found", failed["error"])
        self.assertFalse(missing.exists())
        self.assertFalse(view.directory(missing).exists())

    def test_snapshot_exposes_briefing_and_failures_but_no_cli_configuration(self):
        root = view.consult.directory(self.room)
        root.mkdir()
        briefing = {"goal": "保留长期背景", "constraints": ["只读项目"]}
        peer.write_json(root / "config.json", {"main": "codex", "reviewer": "claude", "briefing": briefing,
                                               "cli": ["sensitive-cli-argument"]})
        peer.write_json(root / "status.json", {"state": "failed", "detail": "CLI exited with code 3",
                                               "native_session_id": "private-session"})
        data = json.loads(self.http("/api/state")[2])
        self.assertEqual(data["briefing"], briefing)
        self.assertEqual(data["model"], {"state": "failed", "detail": "CLI exited with code 3"})
        self.assertNotIn("private-session", json.dumps(data))
        self.assertNotIn("sensitive-cli-argument", json.dumps(data))

    def test_closing_viewer_preserves_live_discussion_and_can_reopen(self):
        self.command("close")
        deadline = time.monotonic() + 4
        while view.running(self.room) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.command("status")["running"])
        with chat.database(self.room) as conn:
            self.assertEqual(chat.state(conn)["phase"], "discussing")
        restarted = self.command("start")
        self.assertFalse(restarted["duplicate"])
        self.info = view.running(self.room)

    @unittest.skipIf(os.name == "nt", "CLI fixture uses a Unix executable shebang")
    def test_page_stop_cancels_an_active_foreground_cli(self):
        from test_peer import FAKE_CLAUDE
        room = self.root / "active.sqlite"
        cli = self.root / "fake-claude"
        cli.write_text(FAKE_CLAUDE, encoding="utf-8")
        cli.chmod(0o755)
        (self.root / "fake-mode.txt").write_text("delay")
        brief = self.root / "briefing.json"
        brief.write_text(json.dumps({"question": "检查页面停止", "goal": "取消调用", "current_view": "等待回复",
                                     "constraints": [], "decisions": [], "rejected_options": [],
                                     "code_references": [], "unknowns": []}), encoding="utf-8")
        initialized = subprocess.run([sys.executable, str(SCRIPTS / "consult.py"), "init", "--room", str(room),
                                      "--cwd", str(self.root), "--briefing-file", str(brief), "--cli", str(cli)],
                                     capture_output=True, text=True, timeout=10)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.command("start", room=room)
        process = subprocess.Popen([sys.executable, str(SCRIPTS / "consult.py"), "reply", "--room", str(room),
                                    "--request-id", "cancel-test"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if view.snapshot(room)["worker"].get("state") == "thinking":
                    break
                time.sleep(0.05)
            else:
                self.fail("CLI did not start")
            self.assertEqual(view.snapshot(room)["model"]["state"], "calling")
            result = view.request(view.running(room), "/api/stop", "POST")
            self.assertEqual(result["status"]["phase"], "closed")
            _, stderr = process.communicate(timeout=6)
            self.assertEqual(process.returncode, 1, stderr)
            self.assertEqual(len(view.snapshot(room)["events"]), 1)
            self.assertEqual(view.snapshot(room)["status"]["conclusion_status"], "none")
        finally:
            if process.poll() is None:
                chat.stop(argparse.Namespace(room=room, reason="test cleanup"))
                process.communicate(timeout=6)
            self.command("close", room=room)


if __name__ == "__main__":
    unittest.main()
