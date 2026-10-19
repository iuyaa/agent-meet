import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import chat
import group
import peer

FAKE_ROLE = r'''#!/usr/bin/env python3
import json,sys,time,uuid
from pathlib import Path
c=json.loads(sys.stdin.read().split("Discussion data:\n",1)[1])
name=c["your_identity"]
mode_file=Path("mode-"+name+".txt")
mode=mode_file.read_text() if mode_file.exists() else "ok"
with Path("calls-"+name+".jsonl").open("a",encoding="utf-8") as f:
    f.write(json.dumps({"context":c,"argv":sys.argv[1:],"started":time.time()},ensure_ascii=False)+"\n")
if mode=="delay": time.sleep(30)
if mode=="slow": time.sleep(1)
if mode=="barrier":
    Path("barrier-"+name).touch()
    deadline=time.monotonic()+4
    while len(list(Path('.').glob('barrier-*'))) < len(c["roles"])-1:
        if time.monotonic()>deadline: sys.exit(8)
        time.sleep(0.02)
if mode=="fail": sys.exit(7)
action=c["allowed_actions"][0]
result={"action":action,"text":name+"：从"+c["your_role"]["title"]+"角度提出依据与疑问。", "decision":"none",
        "conclusion":{"summary":"","agreements":[],"disagreements":[],"open_questions":[],"evidence_message_ids":[]}}
if action=="review": result["decision"]="reject" if mode=="reject" else "accept"
sid=str(uuid.uuid5(uuid.NAMESPACE_URL,name if mode!="collide" else "shared"))
if mode=="wrong-session": sid=str(uuid.uuid4())
if "--output-last-message" in sys.argv:
    Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text(json.dumps(result),encoding="utf-8")
    print(json.dumps({"type":"thread.started","thread_id":sid}))
    print(json.dumps({"type":"turn.completed"}))
else:
    print(json.dumps({"session_id":sid,"structured_output":result,"is_error":False}))
'''


@unittest.skipIf(os.name == "nt", "fake CLI uses a Unix executable shebang")
class GroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.room = self.root / "五角色 空格.sqlite"
        self.cli = self.root / "fake model"
        self.cli.write_text(FAKE_ROLE, encoding="utf-8")
        self.cli.chmod(0o755)
        titles = ["产品经理", "架构师", "开发", "用户", "业务负责人"]
        self.roles = [{"id": f"role{i}", "title": title, "focus": f"从{title}的视角判断，不编造事实", "cli": str(self.cli)} for i, title in enumerate(titles)]
        self.roles_file = self.root / "roles.json"
        self.brief = {"question": "多角色评审", "goal": "保留原主持人上下文", "current_view": "先核对已知约束",
                      "constraints": ["只讨论，不改代码"], "decisions": ["保留当前长会话"],
                      "rejected_options": ["不替换原主持人"], "code_references": [], "unknowns": ["实际用户反馈未知"]}
        self.brief_file = self.root / "brief.json"
        self.brief_file.write_text(json.dumps(self.brief), encoding="utf-8")

    def tearDown(self):
        if self.room.exists():
            self.command("chat.py", "stop", "--reason", "test cleanup")
        self.temp.cleanup()

    def command(self, script, action, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), action, "--room", str(self.room), *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8", timeout=14)
        self.assertNotIn("Traceback", result.stderr)
        value = json.loads(result.stdout or result.stderr)
        self.assertEqual(result.returncode, 0 if ok else 1, value)
        return value

    def initialize(self, rounds=2, **kwargs):
        self.roles_file.write_text(json.dumps(self.roles, ensure_ascii=False), encoding="utf-8")
        return self.command("group.py", "init", "--cwd", self.root, "--briefing-file", self.brief_file,
                            "--roles-file", self.roles_file, "--rounds", rounds, **kwargs)

    def run_round(self, request="round-1", **kwargs):
        return self.command("group.py", "round", "--request-id", request, **kwargs)

    def send(self, name="codex", request="host-2", text="结合上一轮各角色意见，检查取舍和未知信息。", **kwargs):
        return self.command("chat.py", "send", "--as", name, "--request-id", request, "--text", text, **kwargs)

    def calls(self, name):
        path = self.root / ("calls-" + name + ".jsonl")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def propose(self, request="proposal-1", ids=None, **kwargs):
        with chat.database(self.room) as conn:
            events = list(conn.execute("SELECT id FROM events WHERE kind='message'"))
        body = {"summary": "准确记录各角色共识、分歧及待验证问题", "agreements": ["保留原主持人上下文"],
                "disagreements": ["可保留不同判断"], "open_questions": ["真实用户反馈"],
                "evidence_message_ids": ids if ids is not None else [r[0] for r in events]}
        assessment = {"decision": "conclude", "reason": "已记录各方意见，未知信息明确保留，可提交记录审核",
                      "blocking_questions": [], "accepted_uncertainties": ["真实用户反馈未知"],
                      "next_steps": [], "evidence_message_ids": [r[0] for r in events]}
        assessment_path = self.root / (request + "-assessment.json")
        assessment_path.write_text(json.dumps(assessment), encoding="utf-8")
        self.command("chat.py", "assess", "--as", "codex", "--request-id", request + "-assessment", "--file", assessment_path)
        path = self.root / (request + ".json")
        path.write_text(json.dumps(body), encoding="utf-8")
        return self.command("chat.py", "propose", "--as", "codex", "--request-id", request, "--file", path, **kwargs)

    def test_five_roles_keep_distinct_native_sessions_and_see_previous_round(self):
        initialized = self.initialize()
        self.assertEqual(initialized["status"]["participants"], ["codex"] + [r["id"] for r in self.roles])
        self.assertEqual(initialized["status"]["completed_rounds"], 0)
        self.assertTrue(all(not self.calls(r["id"]) for r in self.roles))
        self.run_round()
        self.send()
        second = self.run_round("round-2")
        self.assertEqual(second["status"]["phase"], "summarizing")
        self.assertEqual(second["status"]["completed_rounds"], 2)
        sessions = []
        for role in self.roles:
            calls = self.calls(role["id"])
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["context"]["your_role"]["title"], role["title"])
            self.assertEqual(calls[1]["context"]["briefing"], self.brief)
            others = {e["sender"] for e in calls[1]["context"]["new_events"] if e["kind"] == "message"}
            self.assertTrue({r["id"] for r in self.roles} <= others)
            self.assertIn("codex", others)
            self.assertIn("--resume", calls[1]["argv"])
            sessions.append(calls[1]["argv"][calls[1]["argv"].index("--resume") + 1])
        self.assertEqual(len(set(sessions)), 5)
        self.send(request="over-budget", ok=False)

    def test_calls_are_parallel_and_share_same_input_snapshot(self):
        self.initialize()
        for role in self.roles:
            (self.root / ("mode-" + role["id"] + ".txt")).write_text("barrier")
        self.run_round()
        calls = [self.calls(role["id"])[0] for role in self.roles]
        # Each CLI waits for all five to start; a sequential runner cannot pass.
        self.assertEqual(len(list(self.root.glob("barrier-*"))), 5)
        self.assertEqual(len({json.dumps(c["context"]["new_events"], sort_keys=True) for c in calls}), 1)

    def test_all_roles_must_review_and_host_cannot_self_confirm(self):
        self.initialize(rounds=1)
        self.run_round()
        self.propose(ids=[1, 2], ok=False)
        proposal = self.propose()["event"]["id"]
        self.command("chat.py", "review", "--as", "codex", "--request-id", "self", "--proposal", proposal,
                     "--decision", "accept", "--text", "不能自审", ok=False)
        for i, role in enumerate(self.roles):
            reviewed = self.command("chat.py", "review", "--as", role["id"], "--request-id", "review",
                                    "--proposal", proposal, "--decision", "accept", "--text", "准确记录了本角色观点")
            self.assertEqual(reviewed["status"]["phase"] == "closed", i == 4)
            self.assertEqual(reviewed["status"]["conclusion_status"] == "confirmed", i == 4)

    def test_rejection_is_not_overridden_by_majority_and_revision_can_be_reviewed(self):
        self.initialize()
        self.run_round()
        self.propose()
        mode = self.root / "mode-role3.txt"
        mode.write_text("reject")
        disputed = self.run_round("review-1")
        self.assertEqual(disputed["status"]["conclusion_status"], "disputed")
        self.assertNotEqual(disputed["status"]["phase"], "closed")
        self.propose(request="proposal-2")
        mode.unlink()
        accepted = self.run_round("review-2")
        self.assertEqual(accepted["status"]["conclusion_status"], "confirmed")
        self.assertEqual(accepted["status"]["completed_rounds"], 1)
        output = self.root / "report.md"
        self.command("chat.py", "export", "--output", output)
        text = output.read_text(encoding="utf-8")
        self.assertIn("全部角色已确认记录", text)
        self.assertIn("用户", text)
        self.assertIn("第 1 轮", text)
        self.assertNotIn("native_session_id", text)

    def test_failed_role_keeps_other_replies_and_new_request_only_retries_missing_role(self):
        self.initialize()
        mode = self.root / "mode-role2.txt"
        mode.write_text("fail")
        failed = self.run_round(ok=False)
        self.assertEqual(set(failed["errors"]), {"role2"})
        self.assertEqual(len(failed["results"]), 4)
        self.run_round(ok=False)
        self.assertTrue(all(len(self.calls(r["id"])) == 1 for r in self.roles))
        self.send(ok=False)
        mode.unlink()
        retried = self.run_round("retry-role2")
        self.assertEqual(set(retried["results"]), {"role2"})
        self.assertEqual(retried["status"]["completed_rounds"], 1)
        self.assertEqual(len(self.calls("role2")), 2)
        self.assertEqual(self.calls("role2")[0]["context"]["new_events"],
                         self.calls("role2")[1]["context"]["new_events"])

    def test_successful_and_old_batch_retries_do_not_call_or_roll_context_back(self):
        self.initialize()
        self.run_round()
        duplicate = self.run_round()
        self.assertTrue(all(v["duplicate"] for v in duplicate["results"].values()))
        self.send()
        self.run_round("round-2")
        cursors = {r["id"]: peer.read_status(peer.paths(self.room, r["id"]))["read_cursor"] for r in self.roles}
        self.run_round()
        self.assertEqual(cursors, {r["id"]: peer.read_status(peer.paths(self.room, r["id"]))["read_cursor"] for r in self.roles})
        self.assertTrue(all(len(self.calls(r["id"])) == 2 for r in self.roles))

    def test_saved_response_can_be_committed_after_db_failure_without_another_model_call(self):
        self.initialize()
        original = group.commit_response
        def interrupted(room, role, cached, request_id):
            if role["id"] == "role2":
                raise sqlite3.OperationalError("simulated interrupted database commit")
            return original(room, role, cached, request_id)
        with mock.patch.object(group, "commit_response", side_effect=interrupted):
            failed = group.run_round(type("Args", (), {"room": str(self.room), "request_id": "recover-ready",
                                                       "turn_timeout": 10, "only": None})())
        self.assertFalse(failed["ok"])
        self.assertEqual(set(failed["errors"]), {"role2"})
        recovered = self.run_round("recover-ready")
        self.assertEqual(recovered["status"]["completed_rounds"], 1)
        self.assertTrue(all(len(self.calls(r["id"])) == 1 for r in self.roles))

    def test_role_backend_model_and_main_role_can_be_configured(self):
        self.roles[1].update(backend="codex", model="example-codex-model")
        initialized = self.initialize()
        self.assertEqual(initialized["roles"][2]["backend"], "codex")
        self.run_round()
        self.assertIn("--model", self.calls("role1")[0]["argv"])
        self.assertIn("example-codex-model", self.calls("role1")[0]["argv"])
        self.send()
        self.run_round("round-2")
        self.assertIn("resume", self.calls("role1")[1]["argv"])

    def test_host_can_fill_one_of_the_roles_and_two_person_rounds_use_same_protocol(self):
        self.roles = self.roles[:1]
        self.roles_file.write_text(json.dumps(self.roles), encoding="utf-8")
        initialized = self.command("group.py", "init", "--cwd", self.root, "--briefing-file", self.brief_file,
                                   "--roles-file", self.roles_file, "--rounds", 1,
                                   "--main-title", "架构师", "--main-focus", "基于长期背景审视架构取舍")
        self.assertEqual(initialized["roles"][0]["title"], "架构师")
        self.run_round()
        self.propose()
        accepted = self.run_round("review")
        self.assertEqual(accepted["status"]["conclusion_status"], "confirmed")

    def test_timeout_does_not_turn_partial_reviews_into_agreement(self):
        self.initialize(rounds=1)
        self.run_round()
        self.propose()
        first = self.command("group.py", "round", "--request-id", "one-review", "--only", "role0")
        self.assertEqual(first["status"]["conclusion_status"], "unconfirmed")
        with sqlite3.connect(self.room) as conn:
            conn.execute("UPDATE room SET expires=?", (time.time() - 1,))
        expired = self.command("group.py", "status")["status"]
        self.assertEqual(expired["close_reason"], "expired")
        self.assertEqual(expired["conclusion_status"], "unconfirmed")
        self.assertEqual(len(expired["pending_reviewers"]), 4)

    def test_partial_review_calls_use_the_same_original_proposal_snapshot(self):
        self.initialize(rounds=1)
        self.run_round()
        self.propose()
        self.command("group.py", "round", "--request-id", "review-one", "--only", "role0")
        self.run_round("review-remaining")
        first = self.calls("role0")[-1]["context"]
        last = self.calls("role4")[-1]["context"]
        self.assertEqual(first["new_events"], last["new_events"])
        self.assertEqual(first["status"], last["status"])

    def test_same_native_session_is_not_shared_between_different_roles(self):
        self.initialize()
        for role in self.roles[:2]:
            (self.root / ("mode-" + role["id"] + ".txt")).write_text("collide")
        result = self.run_round(ok=False)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("same native session", next(iter(result["errors"].values())))
        self.assertEqual(result["status"]["completed_rounds"], 0)
        retried = self.run_round("collision-retry", ok=False)
        self.assertIn("another role", next(iter(retried["errors"].values())))
        self.assertTrue(all(len(self.calls(role["id"])) == 1 for role in self.roles))

    def test_round_settings_and_role_validation_happen_before_room_creation(self):
        self.initialize(rounds=0, ok=False)
        self.assertFalse(self.room.exists())
        self.roles[1]["id"] = self.roles[0]["id"]
        self.initialize(ok=False)
        self.assertFalse(self.room.exists())
        self.roles[1]["id"] = "role1"
        self.roles[1]["cli"] = "definitely-missing-agent-cli"
        self.initialize(ok=False)
        self.assertFalse(self.room.exists())

    def test_initialization_is_idempotent_and_different_configuration_needs_new_room(self):
        self.initialize()
        self.assertTrue(self.initialize()["already_initialized"])
        self.initialize(rounds=3, ok=False)
        self.roles[0]["focus"] = "不同职责"
        self.initialize(ok=False)

    def test_stopping_cancels_all_parallel_roles_without_fabricating_messages(self):
        self.initialize()
        for role in self.roles:
            (self.root / ("mode-" + role["id"] + ".txt")).write_text("delay")
        process = subprocess.Popen([sys.executable, str(SCRIPTS / "group.py"), "round", "--room", str(self.room),
                                    "--request-id", "stopped-batch"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if all(group.status(self.room)["workers"][r["id"]]["state"] == "thinking" for r in self.roles):
                    break
                time.sleep(0.05)
            else:
                self.fail("not all parallel CLI calls started")
            self.command("chat.py", "stop", "--reason", "用户停止")
            stdout, stderr = process.communicate(timeout=7)
            self.assertEqual(process.returncode, 1, stderr)
            result = json.loads(stdout)
            self.assertEqual(len(result["errors"]), 5)
            self.assertEqual(result["status"]["message_count"], 1)
            self.assertEqual(result["status"]["conclusion_status"], "none")
        finally:
            if process.poll() is None:
                self.command("chat.py", "stop")
                process.communicate(timeout=7)


if __name__ == "__main__":
    unittest.main()
