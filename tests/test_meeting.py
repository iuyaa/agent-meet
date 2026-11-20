import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_group import FAKE_ROLE, SCRIPTS
from test_task import FAKE
import view


@unittest.skipIf(os.name == "nt", "fake CLI uses a Unix executable shebang")
class MeetingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.room = self.root / "original.sqlite"
        self.cli = self.root / "fake role"
        self.cli.write_text(FAKE_ROLE.replace('c["your_role"]["title"]', 'c.get("your_role", {}).get("title", name)'),
                            encoding="utf-8")
        self.cli.chmod(0o755)
        self.brief = self.write("brief.json", {
            "question": "设计评审", "goal": "形成方案", "current_view": "先检查已知约束",
            "constraints": [], "decisions": [], "rejected_options": [], "code_references": [], "unknowns": [],
        })
        self.context = self.write("context.md", "核对已发言角色提供的接口约束。")
        self.spec = self.write("task.json", {
            "title": "核对接口", "instructions": "按验收标准执行", "context": "来自当前会议",
            "constraints": ["保留已有改动"], "acceptance_criteria": ["提供证据"],
        })

    def write(self, name, value):
        path = self.root / name
        path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def command(self, script, action, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), action, "--room", str(self.room), *map(str, args)],
                                capture_output=True, encoding="utf-8", timeout=20)
        self.assertNotIn("Traceback", result.stderr)
        value = json.loads(result.stdout or result.stderr)
        self.assertEqual(result.returncode, 0 if ok else 1, value)
        return value

    def role(self, name, **values):
        return {"id": name, "title": name, "focus": "检查事实", "cli": str(self.cli), **values}

    def group(self, *roles, cwd=None):
        return self.command("group.py", "init", "--cwd", cwd or self.root, "--briefing-file", self.brief,
                            "--roles-file", self.write("roles.json", list(roles)), "--rounds", 2)

    def round(self, request, *args):
        return self.command("group.py", "round", "--request-id", request, *args)

    def host(self, action, *args, **kwargs):
        return self.command("meeting.py", action, "--as", "codex", *args, **kwargs)

    def invite(self, *args, **kwargs):
        return self.host("invite", "--role-file", self.write("guest.json", self.role("guest")),
                         "--context-file", self.context, "--request-id", "invite-guest", *args, **kwargs)

    def calls(self, role):
        return [json.loads(line) for line in (self.root / f"calls-{role}.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_invite_keeps_frozen_inputs_and_adds_guest_evidence(self):
        self.group(self.role("alpha"), self.role("beta"))
        first = self.round("first", "--only", "alpha")["results"]["alpha"]["event"]
        invite = self.invite("--evidence-event", first["id"])
        self.assertEqual(invite["status"]["pending_speakers"], ["beta", "guest"])
        self.assertTrue(self.invite("--evidence-event", first["id"])["duplicate"])
        self.invite(ok=False)
        self.round("rest")
        beta = self.calls("beta")[0]["context"]
        self.assertEqual([role["id"] for role in beta["roles"]], ["codex", "alpha", "beta"])
        self.assertNotIn(first["id"], [event["id"] for event in beta["new_events"]])
        guest = self.calls("guest")[0]["context"]
        self.assertEqual(guest["invitation_evidence"], [first])
        self.assertEqual(guest["invitation"]["body"]["context"], self.context.read_text(encoding="utf-8"))
        self.assertEqual(view.snapshot(self.room)["status"]["completed_rounds"], 1)

    def test_promoted_pair_keeps_room_and_resumes_original_peer(self):
        self.command("consult.py", "init", "--cwd", self.root, "--briefing-file", self.brief, "--cli", self.cli)
        self.command("consult.py", "reply", "--request-id", "original-reply")
        old = view.snapshot(self.room)["events"]
        self.invite()
        self.assertEqual([e["id"] for e in view.snapshot(self.room)["events"][:len(old)]], [e["id"] for e in old])
        self.command("consult.py", "reply", "--request-id", "moved", ok=False)
        self.round("guest-first")
        self.command("chat.py", "send", "--as", "codex", "--request-id", "host-2", "--text", "按新证据复核。")
        self.round("second")
        self.assertIn("--resume", self.calls("claude")[1]["argv"])
        self.assertEqual(len(self.calls("claude")), 2)
        self.assertEqual(len(self.calls("guest")), 2)

    def test_invited_role_can_take_its_first_task_then_join_discussion(self):
        self.group(self.role("alpha"))
        evidence_id = self.round("first")["results"]["alpha"]["event"]["id"]
        self.invite("--evidence-event", evidence_id)
        assignment = ["--task-id", "verify", "--to", "guest", "--type", "readonly",
                      "--file", self.spec, "--request-id", "assign"]
        refused = self.command("meeting.py", "assign", "--as", "alpha", *assignment, ok=False)
        self.assertIn("original host", refused["error"])
        self.host("assign", *assignment)
        self.host("run", "--task-id", "verify", "--request-id", "run")
        self.round("guest-speaking")
        task_call, speaking_call = self.calls("guest")
        self.assertEqual(task_call["context"]["invitation_context"], self.context.read_text(encoding="utf-8"))
        self.assertIn(f"#{evidence_id} alpha:", task_call["context"]["invitation_evidence"])
        self.assertIn("--resume", speaking_call["argv"])

    def test_readonly_review_and_rework_reference_exact_result_and_resume(self):
        self.group(self.role("checker"))
        first = self.round("first")["results"]["checker"]["event"]["id"]
        assigned = self.host("assign", "--task-id", "verify", "--to", "checker", "--type", "readonly",
                             "--file", self.spec, "--evidence-event", first, "--request-id", "assign")
        self.assertEqual(assigned["status"]["work_items"][0]["state"], "assigned")
        self.assertFalse(self.host("assign", "--task-id", "extra", "--to", "nobody", "--type", "readonly",
                                   "--file", self.spec, "--request-id", "missing", ok=False)["ok"])
        result = self.host("run", "--task-id", "verify", "--request-id", "run-1")["event"]
        self.assertTrue(self.host("run", "--task-id", "verify", "--request-id", "run-1")["duplicate"])
        events = view.snapshot(self.room)["events"]
        ids = [e["id"] for e in events if e["kind"] in ("message", "meeting_result")]
        assessment = self.write("assessment.json", {
            "decision": "conclude", "reason": "证据齐全", "blocking_questions": [],
            "accepted_uncertainties": [], "next_steps": [], "evidence_message_ids": ids,
        })
        failed = self.command("chat.py", "assess", "--as", "codex", "--request-id", "assess", "--file", assessment, ok=False)
        self.assertIn("open meeting tasks", failed["error"])
        self.host("review", "--task-id", "verify", "--result", result["id"], "--request-id", "revise",
                  "--decision", "revise", "--text-file", self.context)
        fresh = self.host("run", "--task-id", "verify", "--request-id", "run-2")["event"]
        calls = self.calls("checker")
        self.assertEqual(len(calls), 3)
        for call in calls[1:]:
            self.assertIn("--resume", call["argv"])
            self.assertIn("dontAsk", call["argv"])
        self.assertEqual(calls[1]["argv"][calls[1]["argv"].index("--resume") + 1],
                         calls[2]["argv"][calls[2]["argv"].index("--resume") + 1])
        self.assertEqual(calls[2]["context"]["host_feedback"], self.context.read_text(encoding="utf-8"))
        for evidence, ok in ((result["id"], False), (fresh["id"], True)):
            self.host("review", "--task-id", "verify", "--result", evidence, "--request-id", "accept",
                      "--decision", "accept", "--text-file", self.context, ok=ok)
        accepted = view.snapshot(self.room)["status"]["work_items"][0]
        self.assertEqual((accepted["state"], accepted["result_id"]), ("accepted", fresh["id"]))
        self.command("chat.py", "assess", "--as", "codex", "--request-id", "assess", "--file", assessment)
        exported = self.root / "record.md"
        self.command("chat.py", "export", "--output", exported)
        self.assertIn("核对接口 · checker · 已验收", exported.read_text(encoding="utf-8"))

    def implementation(self):
        project = self.root / "project"
        project.mkdir()
        (project / "app.py").write_text("def answer():\n    return 0\n", encoding="utf-8")
        git = ["git", "-C", str(project)]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "app.py"], check=True)
        subprocess.run(git + ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"], check=True)
        self.cli.write_text(FAKE, encoding="utf-8")
        self.write("control.json", {})
        self.group(self.role("developer", model="test-model"), cwd=project)
        self.host("assign", "--task-id", "patch", "--to", "developer", "--type", "implementation",
                  "--file", self.spec, "--request-id", "assign")
        return project

    def work(self, operation, *args, **kwargs):
        return self.host("work", "--task-id", "patch", operation, *args, **kwargs)

    def test_implementation_reuses_worker_session_and_requires_apply(self):
        project = self.implementation()
        first = self.host("run", "--task-id", "patch", "--request-id", "start")
        snapshot = first["evidence"]["snapshot"]
        self.work("review", "--request-id", "revise", "--decision", "revise",
                  "--snapshot", snapshot, "--text-file", self.context)
        result = self.host("run", "--task-id", "patch", "--request-id", "again")
        self.assertIn("return 0", (project / "app.py").read_text(encoding="utf-8"))
        check_file = self.write("check.json", [sys.executable, "-B", "-m", "unittest"])
        checked = self.work("check", "--request-id", "check", "--command-file", check_file)
        self.assertTrue(checked["passed"], checked)
        self.work("review", "--request-id", "accept", "--decision", "accept", "--check-id", "check",
                  "--snapshot", result["evidence"]["snapshot"], "--text-file", self.context)
        self.assertIn("return 0", (project / "app.py").read_text(encoding="utf-8"))
        self.work("apply", "--request-id", "apply")
        self.assertIn("return 42", (project / "app.py").read_text(encoding="utf-8"))
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls[0]["session"], calls[1]["session"])
        self.assertIn("test-model", calls[0]["args"])
        self.assertIn("--resume", calls[1]["args"])
        data = view.snapshot(self.room)
        self.assertTrue(data["status"]["work_items"][0]["applied"])
        self.assertEqual({e["sender"] for e in data["events"] if e["kind"] == "meeting_result"}, {"developer"})

    def test_stopping_meeting_interrupts_running_implementation(self):
        project = self.implementation()
        self.write("control.json", {"sleep": True})
        worker = subprocess.Popen([sys.executable, str(SCRIPTS / "meeting.py"), "run", "--room", str(self.room),
                                   "--as", "codex", "--task-id", "patch", "--request-id", "start"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not (self.root / "calls.jsonl").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.root / "calls.jsonl").exists())
            self.assertEqual(view.snapshot(self.room)["status"]["work_items"][0]["state"], "running")
            self.command("chat.py", "stop", "--reason", "test stop")
            _, stderr = worker.communicate(timeout=10)
            self.assertEqual(worker.returncode, 1, stderr)
            self.assertIn("parent meeting closed", json.loads(stderr)["error"])
            self.assertIn("return 0", (project / "app.py").read_text(encoding="utf-8"))
            self.assertEqual(view.snapshot(self.room)["status"]["work_items"][0]["state"], "failed")
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
