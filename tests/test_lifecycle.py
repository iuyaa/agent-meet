import json
import os
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest import mock

import test_group
import test_peer
import group
import peer
import chat


@unittest.skipIf(os.name == "nt", "fake CLIs use Unix executable shebangs")
class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.g = test_group.GroupTests()
        self.g.setUp()
        self.g.roles = self.g.roles[:2]

    def tearDown(self):
        self.g.tearDown()

    def command(self, script, action, *args, **kwargs):
        return self.g.command(script, action, *args, **kwargs)

    def evidence(self):
        with chat.database(self.g.room) as conn:
            return [row[0] for row in conn.execute("SELECT id FROM events WHERE kind='message'")]

    def assess(self, decision="continue", request="assessment", blocking=None, ok=True):
        path = self.g.root / (request + ".json")
        value = {"decision": decision, "reason": "仍需核对边界条件" if decision == "continue" else "各方观点与不确定性已明确，可总结",
                 "blocking_questions": blocking if blocking is not None else ["边界条件未核实"] if decision == "continue" else [],
                 "accepted_uncertainties": ["真实用户反馈待验证"], "next_steps": ["核对证据后交叉评审"] if decision == "continue" else [],
                 "evidence_message_ids": self.evidence()}
        path.write_text(json.dumps(value), encoding="utf-8")
        return self.command("chat.py", "assess", "--as", "codex", "--request-id", request, "--file", path, ok=ok)

    def extend(self, request="extension", *args, ok=True):
        return self.command("chat.py", "extend", "--as", "codex", "--request-id", request,
                            "--reason", "用户确认追加讨论，继续核对边界条件", *args, ok=ok)

    def proposal(self, request="draft", ok=True):
        path = self.g.root / (request + ".json")
        path.write_text(json.dumps({"summary": "记录已有判断与适用条件", "agreements": ["保留原会话"],
                                    "disagreements": [], "open_questions": ["真实用户反馈"],
                                    "evidence_message_ids": self.evidence()}), encoding="utf-8")
        return self.command("chat.py", "propose", "--as", "codex", "--request-id", request, "--file", path, ok=ok)

    def initialize_pair(self, messages=2):
        self.g.cli.write_text(test_peer.FAKE_CLAUDE, encoding="utf-8")
        return self.command("consult.py", "init", "--cwd", self.g.root, "--briefing-file", self.g.brief_file,
                            "--cli", self.g.cli, "--max-messages", messages)

    def pair_calls(self):
        return [json.loads(line) for line in (self.g.root / "fake-cli-calls.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_host_must_assess_before_draft_and_continue_is_not_a_conclusion(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        self.proposal(ok=False)
        continued = self.assess()
        self.assertTrue(continued["status"]["continuation_needs_approval"])
        self.assertEqual(continued["status"]["latest_proposal"], None)
        self.proposal(ok=False)
        self.assess("conclude", request="invalid-ready", blocking=["未解决的关键问题"], ok=False)
        self.assess("conclude", request="ready")
        self.proposal()

    def test_new_messages_make_previous_readiness_assessment_stale(self):
        self.g.initialize(rounds=2)
        self.g.run_round()
        self.assess("conclude")
        self.g.send()
        self.g.run_round("second")
        self.proposal(ok=False)
        self.assess("conclude", request="ready-second")
        self.proposal()

    def test_default_does_not_auto_extend_and_explicit_extension_is_idempotent(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        self.assess()
        self.extend("automatic", "--rounds", "1", "--automatic", ok=False)
        extended = self.extend("approved", "--rounds", "1")
        self.assertEqual(extended["status"]["max_rounds"], 2)
        self.assertEqual(extended["status"]["epoch"], 1)
        duplicate = self.extend("approved", "--rounds", "1")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["status"]["max_rounds"], 2)
        self.extend("approved", "--rounds", "2", ok=False)

    def test_declining_continuation_stops_waiting_even_after_expiry(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        self.assess()
        with sqlite3.connect(self.g.room) as conn:
            conn.execute("UPDATE room SET expires=?", (time.time() - 1,))
        stopped = self.command("chat.py", "stop", "--reason", "用户决定不再追加，保留未解决问题")
        self.assertEqual(stopped["status"]["phase"], "closed")
        self.assertFalse(stopped["status"]["continuation_needs_approval"])
        self.assertEqual(stopped["status"]["assessment_status"], "continue")
        self.assertEqual(stopped["status"]["conclusion_status"], "none")

    def test_group_extension_restores_original_native_sessions_and_history(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        original = {role["id"]: peer.read_status(peer.paths(self.g.room, role["id"]))["native_session_id"] for role in self.g.roles}
        self.assess()
        self.extend("more", "--rounds", "1")
        self.g.send()
        resumed = self.g.run_round("continued-round")
        self.assertEqual(resumed["status"]["completed_rounds"], 2)
        for role in self.g.roles:
            calls = self.g.calls(role["id"])
            self.assertEqual(len(calls), 2)
            argv = calls[-1]["argv"]
            self.assertEqual(argv[argv.index("--resume") + 1], original[role["id"]])
            self.assertTrue(any(e["kind"] == "extension" for e in calls[-1]["context"]["new_events"]))
            self.assertTrue(set(self.evidence()[:3]) <= {e["id"] for e in calls[-1]["context"]["new_events"]})
        self.proposal(ok=False)
        self.assess("conclude", request="ready-after-continuation")
        self.proposal()

    def test_confirmed_history_is_preserved_but_not_presented_as_current_conclusion(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        self.assess("conclude")
        proposal = self.proposal()["event"]["id"]
        self.g.run_round("original-review")
        extended = self.extend("continue-after-confirmation", "--rounds", "1")
        self.assertIsNone(extended["status"]["latest_proposal"])
        self.assertEqual(extended["status"]["conclusion_status"], "none")
        self.assertEqual(extended["event"]["body"]["previous_proposal_id"], proposal)
        old = self.g.run_round("original-review")
        self.assertTrue(all(result["duplicate"] for result in old["results"].values()))
        self.assertEqual(old["status"]["conclusion_status"], "none")
        with chat.database(self.g.room) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='review'").fetchone()[0], 2)
        output = self.g.root / "continued.md"
        self.command("chat.py", "export", "--output", output)
        self.assertIn("旧结论和审核保留", output.read_text(encoding="utf-8"))

    def test_expiry_mid_round_and_later_round_keep_all_prior_role_messages_visible(self):
        self.g.initialize(rounds=1)
        self.command("group.py", "round", "--request-id", "first-only", "--only", "role0")
        original = peer.read_status(peer.paths(self.g.room, "role0"))["native_session_id"]
        with sqlite3.connect(self.g.room) as conn:
            conn.execute("UPDATE room SET discuss_until=?,expires=?", (time.time() - 20, time.time() - 10))
        self.assess()
        self.extend("renew-time", "--minutes", "5")
        self.g.run_round("complete-missing-role")
        self.extend("new-round", "--rounds", "1")
        self.g.send()
        self.g.run_round("next-round")
        argv = self.g.calls("role0")[-1]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], original)
        self.assertIn("role0", {e["sender"] for e in self.g.calls("role1")[-1]["context"]["new_events"] if e["kind"] == "message"})

    def test_old_uncommitted_reply_cannot_be_inserted_after_extension(self):
        self.g.initialize(rounds=1)
        original_commit = group.commit_response
        def fail_one(room, role, cached, request_id):
            if role["id"] == "role1":
                raise sqlite3.OperationalError("simulated lost commit")
            return original_commit(room, role, cached, request_id)
        args = type("Args", (), {"room": str(self.g.room), "request_id": "old-batch", "turn_timeout": 10, "only": None})()
        with mock.patch.object(group, "commit_response", side_effect=fail_one):
            self.assertFalse(group.run_round(args)["ok"])
        self.extend("new-epoch", "--rounds", "1")
        replayed = self.g.run_round("old-batch", ok=False)
        self.assertIn("predates continuation", replayed["errors"]["role1"])
        self.assertEqual(len(self.g.calls("role1")), 1)
        self.g.run_round("fresh-continuation")
        self.assertIn("--resume", self.g.calls("role1")[-1]["argv"])

    def test_group_native_id_is_recovered_from_database_if_status_metadata_is_missing(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        root = peer.paths(self.g.room, "role0")
        info = peer.read_status(root)
        original = info["native_session_id"]
        info["native_session_id"] = None
        peer.write_json(root / "status.json", info)
        self.extend("resume", "--rounds", "1")
        self.g.send()
        self.g.run_round("continued")
        argv = self.g.calls("role0")[-1]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], original)

    def test_missing_original_pair_session_refuses_replacement(self):
        self.initialize_pair()
        self.command("consult.py", "reply", "--request-id", "first")
        self.extend("pair-resume", "--rounds", "1")
        self.g.send()
        root = self.g.room.parent / (self.g.room.name + ".consult")
        info = peer.read_status(root)
        info["native_session_id"] = None
        peer.write_json(root / "status.json", info)
        failed = self.command("consult.py", "reply", "--request-id", "must-resume", ok=False)
        self.assertIn("refusing to start a replacement", failed["error"])
        self.assertEqual(len(self.pair_calls()), 1)

    def test_missing_original_group_session_refuses_replacement(self):
        self.g.initialize(rounds=1)
        self.g.run_round()
        root = peer.paths(self.g.room, "role0")
        info = peer.read_status(root)
        info["native_session_id"] = None
        peer.write_json(root / "status.json", info)
        with sqlite3.connect(self.g.room) as conn:
            conn.execute("DELETE FROM group_sessions WHERE agent='role0'")
        self.extend("group-more", "--rounds", "1")
        self.g.send()
        failed = self.command("group.py", "round", "--request-id", "must-restore", "--only", "role0", ok=False)
        self.assertIn("refusing to start a replacement", failed["errors"]["role0"])
        self.assertEqual(len(self.g.calls("role0")), 1)

    def test_rooms_from_before_lifecycle_support_can_continue_in_place(self):
        for mode in ("group", "pair"):
            self.g.room = self.g.root / ("old-" + mode + ".sqlite")
            if mode == "group":
                self.g.initialize(rounds=1)
                self.g.run_round()
                original = peer.read_status(peer.paths(self.g.room, "role0"))["native_session_id"]
            else:
                self.initialize_pair()
                original = self.command("consult.py", "reply", "--request-id", "old-first")["model"]["native_session_id"]
            with sqlite3.connect(self.g.room) as conn:
                conn.execute("DROP TABLE discussion_lifecycle")
            self.extend("upgrade-in-place", "--rounds", "1")
            self.g.send()
            if mode == "group":
                self.g.run_round("old-room-continued")
                argv = self.g.calls("role0")[-1]["argv"]
            else:
                self.command("consult.py", "reply", "--request-id", "old-room-continued")
                argv = self.pair_calls()[-1]["argv"]
            self.assertEqual(argv[argv.index("--resume") + 1], original)
            self.command("chat.py", "stop", "--reason", "test cleanup")

    def test_pair_budget_extension_and_time_only_extension_reuse_same_claude_session(self):
        self.initialize_pair()
        first = self.command("consult.py", "reply", "--request-id", "first")
        original = first["model"]["native_session_id"]
        self.assess()
        extended = self.extend("pair-more", "--rounds", "1")
        self.assertEqual(extended["status"]["max_messages"], 4)
        self.g.send()
        self.command("consult.py", "reply", "--request-id", "second")
        argv = self.pair_calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], original)
        self.assess("conclude", request="pair-ready")
        self.proposal()
        self.command("consult.py", "reply", "--request-id", "review")
        reopened = self.extend("time-only", "--minutes", "10")
        self.assertEqual(reopened["event"]["body"]["added_rounds"], 1)
        self.assertEqual(reopened["status"]["conclusion_status"], "none")

    def test_extension_is_rejected_while_roles_are_running(self):
        self.g.initialize(rounds=1)
        for role in self.g.roles:
            (self.g.root / ("mode-" + role["id"] + ".txt")).write_text("delay")
        process = subprocess.Popen([sys.executable, str(test_group.SCRIPTS / "group.py"), "round", "--room", str(self.g.room), "--request-id", "active"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if any(group.status(self.g.room)["workers"][r["id"]]["state"] == "thinking" for r in self.g.roles):
                    break
                time.sleep(0.05)
            failed = self.extend("busy", "--rounds", "1", ok=False)
            self.assertIn("call is active", failed["error"])
            self.assertEqual(group.status(self.g.room)["status"]["epoch"], 0)
        finally:
            self.command("chat.py", "stop", "--reason", "test cleanup")
            process.communicate(timeout=7)


if __name__ == "__main__":
    unittest.main()
