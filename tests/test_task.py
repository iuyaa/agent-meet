import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import task
import view

SCRIPTS = Path(task.__file__).parent
FAKE = '''#!/usr/bin/env python3
import json, pathlib, subprocess, sys, time
root = pathlib.Path(__file__).parent
config = json.loads((root / 'control.json').read_text())
args = sys.argv[1:]
session = args[args.index('--resume') + 1] if '--resume' in args else args[args.index('--session-id') + 1]
prompt = sys.stdin.read()
with (root / 'calls.jsonl').open('a') as f:
    f.write(json.dumps({'args': args, 'prompt': prompt, 'session': session, 'cwd': str(pathlib.Path.cwd())}) + '\\n')
if config.get('edit', True):
    pathlib.Path('app.py').write_text('def answer():\\n    return ' + str(config.get('answer', 42)) + '\\n')
    pathlib.Path('test_app.py').write_text('import unittest\\nfrom app import answer\\nclass Answer(unittest.TestCase):\\n    def test_answer(self):\\n        self.assertEqual(answer(), 42)\\n')
if config.get('child'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    (root / 'child.pid').write_text(str(child.pid))
if config.get('sleep'):
    time.sleep(60)
if config.get('fail'):
    print(json.dumps({'subtype': 'success', 'is_error': True, 'session_id': session,
                      'result': 'Prompt is too long · automatic compaction failed'}))
else:
    print(json.dumps({'session_id': 'wrong-session' if config.get('wrong_session') else session,
       'structured_output': {'status': config.get('status', 'ready_for_review'),
       'summary': '完成 **实现**，请主持人检查实际 diff。', 'tests': ['worker claims only'],
       'remaining_issues': []}}))
'''


@unittest.skipIf(os.name == 'nt', 'fixture uses executable Unix shebang; native Windows validation remains separate')
class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / '项目 空格'
        self.project.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Task Test')
        self.git('config', 'user.email', 'task@test.invalid')
        (self.project / 'app.py').write_text('def answer():\n    return 0\n')
        (self.project / '.gitignore').write_text('__pycache__/\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        self.room = self.project / '.agent-meet' / 'task-one' / 'discussion.sqlite'
        self.cli = self.root / 'fake claude'
        self.cli.write_text(FAKE, encoding='utf-8')
        self.cli.chmod(0o755)
        self.control()
        self.spec = {'title': '修复答案', 'instructions': 'Return 42; add a meaningful regression test.',
                     'context': '当前主持人保留原讨论上下文。', 'constraints': ['Preserve user changes'],
                     'acceptance_criteria': ['answer() returns 42', 'regression test passes']}
        self.spec_file = self.root / 'spec.json'
        self.spec_file.write_text(json.dumps(self.spec), encoding='utf-8')
        self.feedback = self.root / 'feedback.txt'
        self.feedback.write_text('检查真实差异和失败路径；修复后继续原会话。', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], stderr=subprocess.PIPE)

    def control(self, **value):
        (self.root / 'control.json').write_text(json.dumps(value))

    def command(self, script, action, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), action, '--room', str(self.room), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        output = result.stdout if result.returncode == 0 else result.stderr
        if result.returncode:
            self.assertNotIn('Traceback', output)
        data = json.loads(output)
        self.assertEqual(result.returncode, 0 if ok else 1, data)
        return data

    def call(self, action, *args, **kwargs):
        return self.command('task.py', action, *args, **kwargs)

    def init(self, *args, **kwargs):
        result = self.call('init', '--cwd', self.project, '--main', 'pi', '--task-file', self.spec_file,
                           '--cli', self.cli, *args, **kwargs)
        if result.get('ok'):
            self.worktree = Path(result['worktree'])
        return result

    def run_worker(self, request='run-1', **kwargs):
        return self.call('run', '--request-id', request, **kwargs)

    def calls(self):
        path = self.root / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def check(self, request='check-1', argv=None):
        path = self.root / (request + '.json')
        path.write_text(json.dumps(argv or [sys.executable, '-m', 'unittest', '-v']), encoding='utf-8')
        return self.call('check', '--as', 'pi', '--request-id', request, '--command-file', path)

    def review(self, snapshot, decision='accept', request='review-1', *extra, **kwargs):
        return self.call('review', '--as', 'pi', '--request-id', request, '--snapshot', snapshot,
                         '--decision', decision, '--text-file', self.feedback, *extra, **kwargs)

    def accept(self):
        result = self.run_worker()
        self.check()
        self.review(result['evidence']['snapshot'], 'accept', 'accept-1', '--check-id', 'check-1')
        return result

    def test_init_copies_dirty_source_and_preserves_head_and_index(self):
        (self.project / 'staged.txt').write_text('staged version')
        self.git('add', 'staged.txt')
        (self.project / 'staged.txt').write_text('unstaged version')
        (self.project / 'notes.txt').write_text('untracked user notes')
        before = (self.git('rev-parse', 'HEAD'), self.git('diff', '--cached'), self.git('status', '--porcelain'))
        result = self.init()
        self.assertEqual(result['status']['task_state'], 'ready')
        self.assertEqual((self.worktree / 'staged.txt').read_text(), 'unstaged version')
        self.assertEqual((self.worktree / 'notes.txt').read_text(), 'untracked user notes')
        self.assertEqual(before, (self.git('rev-parse', 'HEAD'), self.git('diff', '--cached'), self.git('status', '--porcelain')))
        self.assertFalse(self.calls())
        self.assertTrue(self.init()['already_initialized'])
        self.init('--attempts', '2', ok=False)

    def test_worker_diff_review_rework_resumes_exact_session_and_deduplicates(self):
        self.init()
        original = (self.project / 'app.py').read_text()
        first = self.run_worker()
        self.assertEqual((self.project / 'app.py').read_text(), original)
        self.assertEqual(set(first['evidence']['changed_files']), {'app.py', 'test_app.py'})
        self.assertIn('+    return 42', Path(first['evidence']['diff_file']).read_text())
        self.assertTrue(self.run_worker()['duplicate'])
        self.assertEqual(len(self.calls()), 1)
        self.run_worker('unreviewed', ok=False)
        self.review(first['evidence']['snapshot'], 'revise', 'revise-1')
        second = self.run_worker('run-2')
        calls = self.calls()
        self.assertIn('--session-id', calls[0]['args'])
        self.assertIn('--resume', calls[1]['args'])
        self.assertEqual(calls[0]['session'], calls[1]['session'])
        self.assertIn('修复后继续原会话', calls[1]['prompt'])
        self.assertIn('Edit', calls[0]['args'][calls[0]['args'].index('--allowedTools') + 1])
        self.assertNotIn('--dangerously-skip-permissions', calls[0]['args'])
        self.assertEqual(second['status']['task_state'], 'ready_for_review')

    def test_real_checks_accept_and_apply_preserve_user_index_and_unrelated_edits(self):
        (self.project / 'notes.txt').write_text('before')
        self.git('add', 'notes.txt')
        before_index = self.git('diff', '--cached')
        before_head = self.git('rev-parse', 'HEAD')
        self.init()
        result = self.accept()
        self.assertEqual((self.project / 'app.py').read_text(), 'def answer():\n    return 0\n')
        (self.project / 'unrelated.txt').write_text('late unrelated edit')
        applied = self.call('apply', '--as', 'pi', '--request-id', 'apply-1')
        self.assertTrue(applied['applied'])
        self.assertTrue(self.call('apply', '--as', 'pi', '--request-id', 'apply-1')['duplicate'])
        self.assertEqual((self.project / 'app.py').read_text(), 'def answer():\n    return 42\n')
        self.assertEqual((self.project / 'unrelated.txt').read_text(), 'late unrelated edit')
        self.assertEqual(self.git('diff', '--cached'), before_index)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before_head)
        self.assertEqual(self.call('status')['status']['accepted_snapshot'], result['evidence']['snapshot'])

    def test_failed_checks_block_acceptance_and_rework_gets_actual_output(self):
        self.init()
        self.control(answer=7)
        result = self.run_worker()
        check = self.check()
        self.assertFalse(check['passed'])
        self.assertIn('AssertionError', check['stderr'])
        self.assertTrue(self.check()['duplicate'])
        self.review(result['evidence']['snapshot'], 'accept', 'bad-accept', '--check-id', 'check-1', ok=False)
        self.review(result['evidence']['snapshot'], 'accept', 'bad-hidden', '--no-check-reason', 'skip', ok=False)
        self.review(result['evidence']['snapshot'], 'revise', 'revise', '--check-id', 'check-1')
        self.control()
        result = self.run_worker('run-2')
        self.assertIn('AssertionError', self.calls()[-1]['prompt'])
        check = self.check('check-2')
        self.assertTrue(check['passed'])
        self.review(result['evidence']['snapshot'], 'accept', 'good', '--check-id', 'check-2')

    def test_stale_snapshot_and_changed_during_check_are_rejected(self):
        self.init()
        result = self.run_worker()
        self.check(argv=[sys.executable, '-c', "from pathlib import Path; Path('extra.txt').write_text('changed')"])
        evidence = self.call('inspect')['evidence']
        self.review(result['evidence']['snapshot'], 'accept', 'stale', '--no-check-reason', 'skip', ok=False)
        self.review(evidence['snapshot'], 'accept', 'stale-check', '--check-id', 'check-1', ok=False)
        self.check('fresh')
        self.review(evidence['snapshot'], 'accept', 'good', '--check-id', 'fresh')

    def test_apply_refuses_source_conflicts_and_duplicate_does_not_overwrite_later_edits(self):
        self.init()
        self.accept()
        source = self.project / 'app.py'
        source.write_text('late edit\n')
        self.call('apply', '--as', 'pi', '--request-id', 'apply-1', ok=False)
        self.assertEqual(source.read_text(), 'late edit\n')
        source.write_text('def answer():\n    return 0\n')
        self.call('apply', '--as', 'pi', '--request-id', 'apply-1')
        source.write_text('later edit after apply\n')
        self.call('apply', '--as', 'pi', '--request-id', 'apply-1', ok=False)
        self.assertEqual(source.read_text(), 'later edit after apply\n')

    def test_apply_changes_staged_and_unstaged_task_path_without_rewriting_source_index(self):
        source = self.project / 'app.py'
        source.write_text('def answer():\n    return 1\n')
        self.git('add', 'app.py')
        source.write_text('def answer():\n    return 2\n')
        index_before = self.git('diff', '--cached')
        self.init()
        self.accept()
        self.call('apply', '--as', 'pi', '--request-id', 'apply')
        self.assertIn('return 42', source.read_text())
        self.assertEqual(index_before, self.git('diff', '--cached'))

    def test_binary_addition_deletion_and_executable_mode_survive_delivery(self):
        (self.project / 'remove.txt').write_text('remove this file')
        self.git('add', '.')
        self.git('commit', '-qm', 'more baseline')
        self.init()
        self.run_worker()
        binary = b'\0\xff\x80\n' * 100
        (self.worktree / 'asset.bin').write_bytes(binary)
        (self.worktree / 'remove.txt').unlink()
        (self.worktree / 'app.py').chmod(0o755)
        evidence = self.call('inspect')['evidence']
        self.check()
        self.review(evidence['snapshot'], 'accept', 'accept', '--check-id', 'check-1')
        self.call('apply', '--as', 'pi', '--request-id', 'apply')
        self.assertEqual((self.project / 'asset.bin').read_bytes(), binary)
        self.assertFalse((self.project / 'remove.txt').exists())
        self.assertTrue((self.project / 'app.py').stat().st_mode & 0o100)

    def test_source_conflict_detection_uses_literal_filenames(self):
        special = 'file[1].txt'
        (self.project / special).write_text('baseline\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'special filename')
        self.init()
        self.run_worker()
        (self.worktree / special).write_text('worker\n')
        evidence = self.call('inspect')['evidence']
        self.check()
        self.review(evidence['snapshot'], 'accept', 'accept', '--check-id', 'check-1')
        (self.project / special).write_text('late user edit\n')
        self.call('apply', '--as', 'pi', '--request-id', 'apply', ok=False)
        self.assertEqual((self.project / special).read_text(), 'late user edit\n')

    def test_newer_failed_check_is_not_hidden_by_older_success(self):
        self.init()
        result = self.run_worker()
        argv = [sys.executable, '-c', "import pathlib, sys; sys.exit(1 if pathlib.Path('.agent-meet/fail').exists() else 0)"]
        self.check('pass', argv)
        ignored = self.worktree / '.agent-meet'
        ignored.mkdir()
        (ignored / 'fail').write_text('fail now')
        self.assertFalse(self.check('fail', argv)['passed'])
        self.review(result['evidence']['snapshot'], 'accept', 'bad', '--check-id', 'pass', ok=False)
        (ignored / 'fail').unlink()
        self.assertTrue(self.check('pass-later', argv)['passed'])
        self.review(result['evidence']['snapshot'], 'accept', 'good', '--check-id', 'pass-later')

    def test_running_worker_can_be_stopped_without_database_lock_or_orphan(self):
        self.init()
        self.control(child=True, sleep=True)
        process = subprocess.Popen([sys.executable, str(SCRIPTS / 'task.py'), 'run', '--room', str(self.room), '--request-id', 'stop-running'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic() + 5
            while not (self.root / 'child.pid').exists() and time.monotonic() < until:
                time.sleep(0.05)
            self.assertTrue((self.root / 'child.pid').exists())
            self.command('chat.py', 'stop', '--reason', 'user clicked stop')
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1, stderr)
            self.assertEqual(self.call('status')['status']['close_reason'], 'stopped: user clicked stop')
            proc = Path('/proc') / (self.root / 'child.pid').read_text() / 'stat'
            if proc.exists():
                self.assertEqual(proc.read_text().split()[2], 'Z')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_compaction_failure_keeps_edits_and_original_session_for_explicit_retry(self):
        self.init()
        self.control(fail=True)
        failure = self.run_worker(ok=False)
        self.assertIn('preserved', failure['error'])
        self.assertIn('42', (self.worktree / 'app.py').read_text())
        self.assertEqual(self.call('status')['status']['task_state'], 'failed')
        self.run_worker(ok=False)  # Failed request ID must never silently rerun edits.
        self.assertEqual(len(self.calls()), 1)
        self.control()
        self.run_worker('explicit-retry')
        self.assertEqual(self.calls()[0]['session'], self.calls()[1]['session'])
        self.assertIn('--resume', self.calls()[1]['args'])

    def test_different_native_session_is_not_accepted(self):
        self.init()
        self.control(wrong_session=True)
        self.run_worker(ok=False)
        self.assertEqual(self.call('status')['status']['task_state'], 'failed')

    def test_budget_extension_keeps_worktree_and_session(self):
        self.init('--attempts', '1')
        result = self.run_worker()
        self.review(result['evidence']['snapshot'], 'revise', 'revise-1')
        self.run_worker('over-budget', ok=False)
        self.call('extend', '--as', 'pi', '--request-id', 'extend-1', '--attempts', '1', '--reason', '用户要求继续修复')
        self.run_worker('run-2')
        self.assertEqual(self.calls()[0]['session'], self.calls()[1]['session'])
        self.assertEqual(self.calls()[0]['cwd'], self.calls()[1]['cwd'])

    def test_no_check_reason_allowed_and_host_cannot_be_impersonated_by_worker(self):
        self.init()
        result = self.run_worker()
        self.review(result['evidence']['snapshot'], ok=False)
        self.call('review', '--as', 'claude-worker', '--request-id', 'self-accept', '--snapshot', result['evidence']['snapshot'],
                  '--decision', 'accept', '--text-file', self.feedback, '--no-check-reason', 'skip', ok=False)
        self.review(result['evidence']['snapshot'], 'accept', 'review-1', '--no-check-reason', '人工检查此次小改动，原因记录在此')

    def test_discussion_mutations_rejected_task_view_and_export_do_not_claim_discussion_consensus(self):
        self.init()
        result = self.run_worker()
        self.command('chat.py', 'send', '--as', 'pi', '--request-id', 'bypass', '--text', 'bypass', ok=False)
        self.command('chat.py', 'join', '--as', 'pi', ok=False)
        self.command('chat.py', 'extend', '--as', 'pi', '--request-id', 'bypass', '--minutes', '5', '--reason', 'bypass', ok=False)
        self.check()
        snapshot = view.snapshot(self.room)
        self.assertEqual(snapshot['status']['mode'], 'task')
        encoded = json.dumps(snapshot)
        for secret in ('native_session_id', 'stdout_file', 'stderr_file', str(self.cli)):
            self.assertNotIn(secret, encoded)
        self.assertIn('worker claims only', encoded)
        output = self.root / 'report.md'
        self.command('chat.py', 'export', '--output', output)
        self.assertIn('任务记录', output.read_text())
        self.assertNotIn('双方已确认', output.read_text())
        self.command('chat.py', 'export', '--output', output, ok=False)

    def test_worker_cannot_change_task_git_branch(self):
        self.init()
        subprocess.check_call(['git', '-C', str(self.worktree), 'checkout', '-qb', 'wrong'])
        self.run_worker(ok=False)
        self.assertFalse(self.calls())

    def test_invalid_init_does_not_modify_source(self):
        self.init('--minutes', 'nan', ok=False)
        self.assertFalse(self.room.exists())
        self.init('--cli', 'missing-agent-meet-cli', ok=False)
        self.assertFalse(self.room.exists())
        self.assertFalse(self.calls())

    def test_stop_retains_files_and_explicit_extension_resumes(self):
        self.init()
        self.command('chat.py', 'stop', '--reason', 'user stop')
        self.run_worker(ok=False)
        self.assertFalse(self.calls())
        self.call('extend', '--as', 'pi', '--request-id', 'extend-1', '--minutes', '2', '--reason', '用户明确继续')
        self.run_worker()

    def test_timeout_kills_worker_and_ordinary_descendants(self):
        self.init()
        self.control(child=True, sleep=True)
        self.call('run', '--request-id', 'timeout', '--turn-timeout', '1', ok=False)
        pid = int((self.root / 'child.pid').read_text())
        proc = Path('/proc') / str(pid) / 'stat'
        if proc.exists():
            self.assertEqual(proc.read_text().split()[2], 'Z')  # reaped by init eventually
        self.assertEqual(self.call('status')['status']['task_state'], 'failed')
        self.assertIn('42', (self.worktree / 'app.py').read_text())

    def test_normal_completion_does_not_leave_worker_descendants(self):
        self.init()
        self.control(child=True)
        self.run_worker()
        proc = Path('/proc') / (self.root / 'child.pid').read_text() / 'stat'
        if proc.exists():
            self.assertEqual(proc.read_text().split()[2], 'Z')


if __name__ == '__main__':
    unittest.main()
