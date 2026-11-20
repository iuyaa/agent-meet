import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_group import SCRIPTS
import peer


FAKE = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

mode_file = Path('mode')
mode = mode_file.read_text() if mode_file.exists() else 'ok'
if sys.argv[1:] == ['--version']:
    print('0.17.1' if mode != 'unsupported' else '0.16.0')
    sys.exit(0)
assert sys.argv[1:4] == ['app-server', '--stdio', '--cwd']
database = Path(os.environ['ZCODE_SESSION_DB_PATH'])
session = 'sess_original'

def write(row):
    print(json.dumps(row), flush=True)

for line in sys.stdin:
    request = json.loads(line)
    action = request['method']
    params = request['params']
    with Path('wire.jsonl').open('a', encoding='utf-8') as log:
        log.write(line)
    if action in ('session/create', 'session/resume'):
        assert params['toolAllowlist'] == ['Read', 'Glob', 'Grep']
        write({'id': 'preferences', 'method': 'session/requestRuntimePreferences', 'params': {}})
        preferences = json.loads(sys.stdin.readline())
        assert preferences['id'] == 'preferences' and preferences['result']['appControlEnabled'] is False
        if action == 'session/create':
            assert params['mode'] == 'plan' and params['persistence'] == 'immediate'
            assert params['titleGenerationEnabled'] is False
            database.touch()
        elif not database.is_file() or params['sessionId'] != session:
            write({'id': request['id'], 'error': {'code': -32001, 'message': 'Session not found'}})
            continue
        result = {'session': {'mode': 'build', 'sessionId': 'sess_wrong' if mode == 'wrong-session' else session}}
    elif action == 'session/setMode':
        assert params == {'sessionId': session, 'mode': 'plan'}
        result = {'session': {'mode': 'plan', 'sessionId': session}}
    elif action == 'session/setModel':
        assert params['model']['options'] == {'reasoningLevel': 'low'}
        assert params['persistAsWorkspaceLastUsed'] is False
        result = {'session': {'mode': 'plan', 'sessionId': session}}
    elif action == 'session/subscribe':
        assert params['sessionId'] == session
        result = {'sessionId': session}
    elif action == 'session/send':
        assert params['sessionId'] == session
        if mode == 'broken-pipe':
            sys.exit(0)
        if mode == 'interactive':
            write({'id': 'approval', 'method': 'permission/request', 'params': {}})
        if mode == 'timeout':
            continue
        context = json.loads(params['content'].split('Discussion data:\n', 1)[1])
        kind = context['allowed_actions'][0]
        response = {'action': kind, 'text': '只读核对完成', 'decision': 'accept' if kind == 'review' else 'none',
                    'conclusion': {'summary': '', 'agreements': [], 'disagreements': [],
                                   'open_questions': [], 'evidence_message_ids': []}}
        event = {'method': 'session/event', 'params': {'sessionId': session, 'type': 'turn.completed',
                 'payload': {'inputId': 'previous-turn', 'resultType': 'success', 'response': 'not this turn'}}}
        write(event)
        event['params']['payload'].update(inputId=params['inputId'],
            resultType='cancelled' if mode == 'failed-turn' else 'success', response=json.dumps(response))
        write(event)
        result = {'accepted': True, 'sessionId': session}
    elif action == 'session/close':
        result = {'closed': True}
    else:
        raise AssertionError(action)
    write({'id': request['id'], 'result': result})
'''


@unittest.skipIf(os.name == "nt", "fake CLI uses a Unix executable shebang")
class ZCodeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.room = self.root / "room.sqlite"
        self.cli = self.root / "fake zcode"
        self.cli.write_text(FAKE, encoding="utf-8")
        self.cli.chmod(0o755)
        self.brief = self.root / "brief.json"
        self.brief.write_text(json.dumps({
            "question": "核对接口", "goal": "核对长简报", "current_view": "历史依赖" * 4100,
            "constraints": [], "decisions": [], "rejected_options": [], "code_references": [], "unknowns": [],
        }, ensure_ascii=False), encoding="utf-8")

    def call(self, script, command, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), command, "--room", str(self.room), *map(str, args)],
            cwd=self.root, capture_output=True, encoding="utf-8", timeout=20,
        )
        self.assertNotIn("Traceback", result.stderr)
        record = json.loads(result.stdout or result.stderr)
        self.assertEqual(result.returncode, 0 if ok else 1, record)
        return record

    def init(self):
        self.call("consult.py", "init", "--cwd", self.root, "--briefing-file", self.brief,
                  "--main", "codex", "--backend", "zcode", "--cli", self.cli, "--model", "local/glm/model$low")

    def requests(self):
        return [json.loads(line) for line in (self.root / "wire.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_long_prompt_resumes_and_runs_assignment_in_original_session(self):
        self.init()
        first = self.call("consult.py", "reply", "--request-id", "first")
        with (self.root / "spec.json").open("w", encoding="utf-8") as handle:
            json.dump({"title": "只读检查", "instructions": "核对源文件", "context": "刚才会议",
                       "constraints": [], "acceptance_criteria": ["报告证据"]}, handle)
        self.call("meeting.py", "assign", "--as", "codex", "--task-id", "check", "--request-id", "assign",
                  "--to", "zcode", "--type", "readonly", "--file", self.root / "spec.json")
        result = self.call("meeting.py", "run", "--as", "codex", "--task-id", "check", "--request-id", "run")
        self.assertEqual(result["event"]["body"]["summary"], "只读核对完成")
        wire = self.requests()
        create = next(row["params"] for row in wire if row["method"] == "session/create")
        self.assertEqual(create["model"], {"providerId": "local", "modelId": "glm/model", "options": {"reasoningLevel": "low"}})
        resume = next(row["params"] for row in wire if row["method"] == "session/resume")
        self.assertEqual(resume["sessionId"], first["model"]["native_session_id"])
        content = next(row["params"]["content"] for row in wire if row["method"] == "session/send")
        self.assertGreater(len(content), 32767)
        self.assertIn("历史依赖", content)
        self.assertEqual(sum(row["method"] == "session/close" for row in wire), 2)

    def test_failed_or_interactive_turns_commit_no_response(self):
        for mode in ("failed-turn", "broken-pipe", "interactive", "timeout", "unsupported"):
            with self.subTest(mode=mode):
                self.room = self.root / (mode + ".sqlite")
                (self.root / "mode").write_text(mode, encoding="utf-8")
                self.init()
                self.call("consult.py", "reply", "--request-id", "failed",
                          "--turn-timeout", "1", ok=False)
                status = self.call("consult.py", "status")
                self.assertEqual(status["status"]["message_count"], 1)

    def test_wrong_or_missing_session_refuses_to_send_followup(self):
        self.init()
        self.call("consult.py", "reply", "--request-id", "first")
        self.call("chat.py", "send", "--as", "codex", "--request-id", "host", "--text", "请复核。")
        (self.root / "mode").write_text("wrong-session", encoding="utf-8")
        self.call("consult.py", "reply", "--request-id", "wrong", ok=False)
        (self.root / "mode").unlink()
        directory = peer.paths(self.room, "zcode")
        (directory / "zcode-runtime" / "sessions.sqlite").unlink()
        self.call("consult.py", "reply", "--request-id", "missing", ok=False)
        self.assertEqual(sum(row["method"] == "session/send" for row in self.requests()), 1)

    def test_explicit_node_bundle_needs_no_shell_wrapper(self):
        bundle = self.root / "official cli.cjs"
        bundle.touch()
        with mock.patch.object(peer.shutil, "which", return_value="node-executable"):
            self.assertEqual(peer.cli_prefix(str(bundle), "zcode"), ["node-executable", str(bundle)])
