"""Subprocess integration for agent-independent hosts and native conversation reuse."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_peer import SCRIPTS, FAKE_CLAUDE
from test_discuss import FAKE_CODEX
import adapters
import codex_desktop
import peer

FAKE_AGENT = r'''#!/usr/bin/env python3
import json,sys,os,uuid,time
from pathlib import Path
if '--help' in sys.argv:
    print('--no-mcp --tools --session');sys.exit(0)
if '--version' in sys.argv:
    print(Path('oc-version').read_text() if Path('oc-version').exists() else '1.2.27');sys.exit(0)
c=json.loads(sys.stdin.read().split('Discussion data:\n',1)[1]);name=c['your_identity']
mode=Path('mode').read_text() if Path('mode').exists() else 'ok'
with Path('calls-'+name+'.jsonl').open('a') as f:
    f.write(json.dumps({'argv':sys.argv[1:],'context':c,'config':os.environ.get('OPENCODE_CONFIG_CONTENT'),'permission':os.environ.get('OPENCODE_PERMISSION')})+'\n')
if mode=='delay':time.sleep(30)
if mode=='bad-shape':
    print(json.dumps({'type':'text','sessionID':['invalid'],'part':'invalid'}));sys.exit(0)
sid=str(uuid.uuid5(uuid.NAMESPACE_DNS,name))
if mode=='switch':sid=str(uuid.uuid4())
action='review' if 'review' in c['allowed_actions'] else 'send'
r={'action':action,'text':'保留既有上下文，逐轮验证依据。','decision':'accept' if action=='review' else 'none','conclusion':{'summary':'','agreements':[],'disagreements':[],'open_questions':[],'evidence_message_ids':[]}}
text='not JSON' if mode=='malformed' else json.dumps(r)
if '--print' in sys.argv:
    p=Path(sys.argv[sys.argv.index('--session')+1])
    if p.exists() and mode!='switch':sid=json.loads(p.read_text().splitlines()[0])['id']
    header={'type':'session','id':sid}
    if not p.exists():p.write_text(json.dumps(header)+'\n')
    if mode!='no-session':print(json.dumps(header))
    print(json.dumps({'type':'message_end','message':{'role':'assistant','stopReason':'length' if mode=='length' else 'stop','content':[{'type':'text','text':text}]}}))
    print(json.dumps({'type':'agent_end','messages':[]}))
else:
    if mode=='error':print(json.dumps({'type':'error','sessionID':sid,'error':{'message':'test failure'}}));sys.exit(0)
    # Tool-era prose must not be parsed as the final JSON response.
    print(json.dumps({'type':'text','sessionID':sid,'part':{'messageID':'earlier','text':'Inspecting project.'}}))
    print(json.dumps({'type':'text',**({} if mode=='no-session' else {'sessionID':sid}),'part':{'messageID':'final','text':text}}))
    print(json.dumps({'type':'step_finish','sessionID':sid,'part':{'reason':'length' if mode=='length' else 'stop'}}))
'''

FAKE_HEADLESS = r'''#!/usr/bin/env python3
import json, os, sys, uuid
from pathlib import Path

backend = Path(sys.argv[0]).name.split()[-1]
mode_path = Path('mode')
mode = mode_path.read_text() if mode_path.exists() else 'ok'
args = sys.argv[1:]
if args == ['--version']:
    print('0.0.0' if mode == 'unsupported' else {
        'dsh': '0.2.2-rc.5', 'qwen': '0.28.0', 'qoder': '1.1.93',
        'hermes': 'Hermes Agent v0.21.5 (2026.9.24)'
    }[backend])
    sys.exit(0)
if mode == 'delay':
    import time
    time.sleep(30)

prompt = sys.stdin.read()
context = json.loads(prompt.split('Discussion data:\n', 1)[1])
name = context['your_identity']
sid = str(uuid.uuid5(uuid.NAMESPACE_DNS, name))
overlay = None
resume_flag = '--session-id' if backend == 'dsh' else '--resume'
if backend == 'dsh':
    overlay = json.loads(Path(args[args.index('--patch') + 1]).read_text(encoding='utf-8'))
    home = Path(os.environ['DSH_HOME'])
    home.mkdir(parents=True, exist_ok=True)
    saved = home / sid
else:
    saved = Path('session-' + sid)
if resume_flag in args:
    assert args[args.index(resume_flag) + 1] == sid and saved.is_file(), 'original session lost'
saved.touch()
with Path('calls-' + name + '.jsonl').open('a', encoding='utf-8') as handle:
    handle.write(json.dumps({'argv': args, 'context': context, 'session': sid, 'overlay': overlay,
                             'web_prompt': 'Cite source titles and URLs' in prompt,
                             'home': os.environ.get('DSH_HOME')}) + '\n')

action = 'review' if 'review' in context['allowed_actions'] else 'send'
reply = {'action': action, 'text': '可核对的记录 [文档](https://example.org/docs)。',
         'decision': 'accept' if action == 'review' else 'none',
         'conclusion': {'summary': '', 'agreements': [], 'disagreements': [], 'open_questions': [], 'evidence_message_ids': []}}
answer = 'not JSON' if mode == 'malformed' else json.dumps(reply)
actual = str(uuid.uuid4()) if mode == 'switch' else sid
if backend == 'dsh':
    print(json.dumps({'type': 'session', 'sessionId': actual}))
    print(json.dumps({'type': 'text', 'text': 'Earlier tool step'}))
    if mode == 'error':
        print(json.dumps({'type': 'error', 'message': 'fake error'}))
    if mode != 'truncated':
        print(json.dumps({'type': 'final', 'sessionId': 'different-id' if mode == 'mismatched-final' else actual,
                          'reason': {'kind': 'error' if mode == 'terminal-failure' else 'completed'}, 'text': answer}))
elif backend == 'qwen':
    print(json.dumps({'type': 'system', 'subtype': 'session_start', 'session_id': actual}))
    if mode == 'error':
        print(json.dumps({'type': 'system', 'subtype': 'session_recording_degraded'}))
    if mode != 'truncated':
        print(json.dumps({'type': 'result', 'subtype': 'success', 'session_id': actual, 'result': answer,
                          'is_error': mode == 'terminal-failure'}))
else:
    init = {'type': 'system', 'subtype': 'init', 'session_id': actual}
    final = {'type': 'result', 'session_id': 'different-id' if mode == 'mismatched-final' else actual}
    if backend == 'qoder':
        names = args[args.index('--tools') + 1:args.index('--permission-mode')]
        assert names == ['Read', 'Glob', 'Grep', 'WebSearch', 'WebFetch']
        assert args[args.index('--permission-mode') + 1] == 'dont_ask'
        assert '--strict-mcp-config' in args
        assert json.loads(args[args.index('--mcp-config') + 1]) == {'mcpServers': {}}
        assert json.loads(args[args.index('--settings') + 1])['disableAllHooks']
        if mode == 'unexpected-tool':
            names.append('Bash')
        init.update(permissionMode='dontAsk', mcp_servers=[], tools=names)
        final.update(subtype='success', result=answer, is_error=mode == 'terminal-failure',
                     terminal_reason='blocking_limit' if mode == 'error' else 'completed')
    else:
        assert args[:8] == ['chat', '--query-file', '-', '--format', 'stream-json',
                            '--toolsets', 'web', '--ignore-rules']
        print('Hermes startup warning')
        final.update(text=answer, exit_code=1 if mode == 'terminal-failure' else 0)
    print(json.dumps(init))
    if backend == 'hermes' and mode == 'unexpected-tool':
        print(json.dumps({'type': 'tool_use', 'name': 'write_file'}))
    if backend == 'hermes' and mode == 'error':
        print(json.dumps({'type': 'error', 'message': 'denied'}))
    if mode != 'truncated':
        print(json.dumps(final))
'''


FAKE_ANTIGRAVITY = r'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if sys.argv[1:] == ['--version']:
    print('1.5.18')
    sys.exit(0)

args = sys.argv[1:]
project = Path(args[args.index('--add-dir') + 1])
agent = args[args.index('--agent') + 1]
definition = (Path.cwd() / '.agents' / 'agents' / (agent + '.md')).read_text()
assert 'commandExecutionPolicy: off' in definition
assert 'view_file' in definition and 'run_command' not in definition and 'write_to_file' not in definition
assert '--disable-slash-commands' in args
assert args[args.index('--input-format') + 1] == 'stream-json'
assert args[args.index('--output-format') + 1] == 'stream-json'
frame = json.loads(sys.stdin.read())
assert frame['event'] == 'user'
prompt = frame['message']['content']
assert 'Return ONLY one JSON object' in prompt
context = json.loads(prompt.split('Discussion data:\n', 1)[1])
mode_path = project / 'mode'
mode = mode_path.read_text() if mode_path.exists() else 'ok'
session = 'agy-original-conversation'
log = project / ('calls-' + context['your_identity'] + '.jsonl')
if '--conversation' in args:
    assert args[args.index('--conversation') + 1] == session
    assert log.exists()
with log.open('a', encoding='utf-8') as out:
    out.write(json.dumps({'argv': args, 'context': context, 'session': session}) + '\n')
if mode == 'switch':
    session = 'unexpected-conversation'
print(json.dumps({'event': 'init', 'conversation_id': session,
                  'init': {'agent': 'other-agent' if mode == 'wrong-agent' else agent}}))
reply = {'action': 'send', 'text': '可复用原会话。', 'decision': 'none', 'conclusion': {
    'summary': '', 'agreements': [], 'disagreements': [], 'open_questions': [], 'evidence_message_ids': []}}
if mode != 'truncated':
    print(json.dumps({'event': 'result', 'result': {
        'status': 'WAITING' if mode == 'waiting' else 'SUCCESS',
        'conversation_id': session, 'response': json.dumps(reply)}}))
'''


class CodexDesktopTests(unittest.TestCase):
    def test_cli_precedence_and_portable_desktop_selection(self):
        existing = Path('/existing/codex.exe')
        bundled = Path('/bundled/codex.exe')
        with mock.patch.object(peer.processes, 'WINDOWS', True), \
                mock.patch.object(peer.shutil, 'which', side_effect=[str(existing), str(existing), None, None]), \
                mock.patch.object(codex_desktop, 'find_cli', return_value=bundled) as find:
            self.assertEqual(peer.cli_prefix('codex', 'codex'), [str(existing.resolve())])
            self.assertEqual(peer.configured_cli(str(existing), 'codex'), str(existing.resolve()))
            find.assert_not_called()
            self.assertEqual(peer.configured_cli('codex', 'codex'), 'codex')
            self.assertEqual(peer.cli_prefix('codex', 'codex'), [str(bundled)])
        with mock.patch.object(peer.processes, 'WINDOWS', True), \
                mock.patch.object(peer.shutil, 'which', return_value=None), \
                mock.patch.object(codex_desktop, 'find_cli') as find:
            with self.assertRaises(peer.chat.ChatError):
                peer.cli_path('/missing/codex.exe', 'codex')
            find.assert_not_called()

    def test_unlaunchable_msix_candidate_falls_back_to_relocated_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundled = root / 'app/resources/codex.exe'
            bundled.parent.mkdir(parents=True)
            bundled.touch()
            relocated = root / 'relocated/codex.exe'
            relocated.parent.mkdir()
            relocated.touch()
            help_text = subprocess.CompletedProcess([], 0, '--json --output-schema resume', '')
            with mock.patch.object(codex_desktop, 'installed_package_roots', return_value=[root]), \
                    mock.patch.object(codex_desktop, 'relocated_candidates', return_value=[relocated]), \
                    mock.patch.object(codex_desktop.subprocess, 'run', side_effect=[PermissionError(), help_text]) as run:
                self.assertEqual(codex_desktop.find_cli(), relocated)
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             [[str(bundled), 'exec', '--help'], [str(relocated), 'exec', '--help']])


@unittest.skipIf(os.name == 'nt', 'subprocess fixtures use Unix shebangs')
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.room = self.root / 'room.sqlite'
        self.brief = self.root / 'brief.json'
        self.brief.write_text(json.dumps({'question':'跨 agent 讨论','goal':'保留当前主持人','current_view':'显式恢复会话',
            'constraints':[],'decisions':[],'rejected_options':[],'code_references':[],'unknowns':[]}))
        self.clis = {}
        for name, body in [('claude', FAKE_CLAUDE), ('codex', FAKE_CODEX), ('pi', FAKE_AGENT), ('opencode', FAKE_AGENT),
                           ('dsh', FAKE_HEADLESS), ('qwen', FAKE_HEADLESS),
                           ('hermes', FAKE_HEADLESS), ('qoder', FAKE_HEADLESS),
                           ('antigravity', FAKE_ANTIGRAVITY)]:
            path=self.root / ('fake '+name);path.write_text(body);path.chmod(0o755);self.clis[name]=path

    def tearDown(self):
        self.temp.cleanup()

    def command(self, script, action, *args, ok=True):
        run=subprocess.run([sys.executable,str(SCRIPTS/script),action,'--room',str(self.room),*map(str,args)],
                           capture_output=True,text=True,encoding='utf-8',timeout=12)
        self.assertNotIn('Traceback',run.stderr)
        result=json.loads(run.stdout or run.stderr)
        self.assertEqual(run.returncode,0 if ok else 1,result)
        return result

    def initialize(self, backend, host='claude', *extra):
        return self.command('consult.py','init','--cwd',self.root,'--briefing-file',self.brief,
                            '--main',host,'--backend',backend,'--cli',self.clis[backend],*extra)

    def reply(self, request='reply', **kwargs):
        return self.command('consult.py','reply','--request-id',request,**kwargs)

    def send(self, host='claude', request='followup'):
        return self.command('chat.py','send','--as',host,'--request-id',request,'--text','请核实先前的依据。')

    def calls(self, reviewer):
        return [json.loads(line) for line in (self.root/('calls-'+reviewer+'.jsonl')).read_text().splitlines()]

    def test_claude_hosts_codex_and_resumes_without_starting_another_host(self):
        initialized=self.initialize('codex')
        self.assertEqual(initialized['status']['participants'],['claude','codex'])
        first=self.reply();self.send();second=self.reply('reply2')
        calls=[json.loads(line) for line in (self.root/'fake-codex-calls.jsonl').read_text().splitlines()]
        self.assertEqual(first['model']['native_session_id'],second['model']['native_session_id'])
        self.assertIn('resume',calls[1]['argv'])
        self.assertFalse((self.root/'fake-cli-calls.jsonl').exists())
        self.assertFalse(peer.paths(self.room,'claude').exists())

    def test_pi_and_opencode_resume_after_user_extension_and_review_final_draft(self):
        for backend,host,version in [('pi','opencode',None),('opencode','pi','1.2.27'),('opencode','claude','2.0.32')]:
            with self.subTest(backend=backend,version=version):
                self.room=self.root/('room-'+backend+host+'.sqlite')
                (self.root/('calls-'+backend+'.jsonl')).unlink(missing_ok=True)
                if version:(self.root/'oc-version').write_text(version)
                self.initialize(backend,host,'--max-messages','2','--model','provider/example')
                first=self.reply()
                self.command('chat.py','extend','--as',host,'--request-id','more','--rounds','1','--reason','用户要求验证依据')
                self.send(host);second=self.reply('reply2')
                self.assertEqual(first['model']['native_session_id'],second['model']['native_session_id'])
                calls=self.calls(backend)
                self.assertEqual(calls[0]['context']['main_identity'],host)
                self.assertEqual(calls[1]['argv'][calls[1]['argv'].index('--model')+1],'provider/example')
                if backend=='pi':
                    self.assertEqual(calls[0]['argv'],calls[1]['argv'])
                    self.assertIn('read,grep,find,ls',calls[1]['argv']);self.assertIn('--no-mcp',calls[1]['argv'])
                else:
                    self.assertIn('--session',calls[-1]['argv'])
                    self.assertEqual('--standalone' in calls[-1]['argv'],version.startswith('2.'))
                    self.assertEqual(json.loads(calls[-1]['config'])['agent']['agent-chat']['permission']['*'],'deny')
                evidence=[1,2,4,5]
                assessment=self.root/'assessment.json';assessment.write_text(json.dumps({'decision':'conclude','reason':'双方依据已记录',
                    'blocking_questions':[],'accepted_uncertainties':[],'next_steps':[],'evidence_message_ids':evidence}))
                self.command('chat.py','assess','--as',host,'--request-id','ready','--file',assessment)
                draft=self.root/'conclusion.json';draft.write_text(json.dumps({'summary':'保留主会话，显式续聊','agreements':[],
                    'disagreements':[],'open_questions':[],'evidence_message_ids':evidence}))
                self.command('chat.py','propose','--as',host,'--request-id','draft','--file',draft)
                reviewed=self.reply('review')
                self.assertEqual(reviewed['status']['conclusion_status'],'confirmed')
                self.assertEqual(reviewed['model']['native_session_id'],first['model']['native_session_id'])

    def test_one_group_can_mix_eight_engines_under_opencode_host(self):
        backends = ('claude', 'codex', 'pi', 'opencode', 'dsh', 'qwen', 'qoder', 'antigravity')
        roles=[{'id':name+'-role','title':name,'focus':'核实证据','backend':name,'cli':str(self.clis[name])}
               for name in backends]
        path=self.root/'roles.json';path.write_text(json.dumps(roles))
        self.command('group.py','init','--cwd',self.root,'--briefing-file',self.brief,'--roles-file',path,
                     '--main','opencode','--rounds','1')
        first=self.command('group.py','round','--request-id','first')
        self.assertEqual(first['status']['completed_rounds'],1)
        self.command('chat.py','extend','--as','opencode','--request-id','more','--rounds','1','--reason','用户要求继续')
        self.send('opencode')
        second=self.command('group.py','round','--request-id','second')
        self.assertEqual(second['status']['completed_rounds'],2)
        for role in roles:
            info=peer.read_status(peer.paths(self.room,role['id']))
            self.assertTrue(info['native_session_id'])
        for backend in ('pi','opencode','dsh','qwen','antigravity'):
            calls=self.calls(backend+'-role');self.assertEqual(len(calls),2)
            self.assertEqual(calls[1]['context']['your_role']['backend'],backend)

    def test_dsh_web_scope_and_qwen_read_only_task_resume_in_original_room(self):
        spec=self.root/'spec.json';spec.write_text(json.dumps({'title':'核对依据','instructions':'提交出处和结论',
            'context':'核对版本变更','constraints':[],'acceptance_criteria':['列出可核对出处']}))
        feedback=self.root/'feedback.txt';feedback.write_text('补充证据', encoding='utf-8')
        for backend in ('dsh','qwen'):
            with self.subTest(backend=backend):
                self.room=self.root/f'{backend}.sqlite'
                self.initialize(backend,'claude','--model','custom-test-model')
                native=self.reply()['model']['native_session_id']
                assignment=['--as','claude','--task-id','verify','--request-id','assign',
                            '--to',backend,'--type','readonly','--file',spec]
                if backend=='qwen':
                    self.command('meeting.py','assign',*assignment,'--web-search',ok=False)
                extra=['--web-search'] if backend=='dsh' else []
                event=self.command('meeting.py','assign',*assignment,*extra)['event']
                self.assertEqual(event['body'].get('web_search',False),backend=='dsh')
                result=self.command('meeting.py','run','--as','claude','--task-id','verify','--request-id','run')['event']
                self.assertIn('https://example.org/docs',result['body']['summary'])
                self.command('meeting.py','review','--as','claude','--task-id','verify','--request-id','review',
                             '--result',result['id'],'--decision','revise','--text-file',feedback)
                self.command('meeting.py','run','--as','claude','--task-id','verify','--request-id','rework')
                self.send('claude')
                self.command('group.py','round','--request-id','followup-round')
                calls=self.calls(backend)
                self.assertEqual([call['session'] for call in calls],[native]*4)
                resume='--session-id' if backend=='dsh' else '--resume'
                self.assertNotIn(resume,calls[0]['argv'])
                for call in calls[1:]:
                    self.assertEqual(call['argv'][call['argv'].index(resume)+1],native)
                if backend=='dsh':
                    self.assertEqual(len({call['home'] for call in calls}),1)
                    for call,enabled in zip(calls,(False,True,True,False)):
                        patch={row['id']:row for row in call['overlay']}
                        self.assertEqual(patch['tool-web']['disabled'],not enabled)
                        self.assertEqual(call['web_prompt'],enabled)
                        self.assertTrue(patch['tool-bash']['disabled'])
                        self.assertFalse(patch['tool-fs']['config']['write'])
                        self.assertEqual(patch['agent-default-model']['config']['model'],'custom-test-model')
                        self.assertIn('read-only',call['argv'])
                else:
                    for call in calls:
                        argv=call['argv'];excluded=set(argv[argv.index('--exclude-tools')+1].split(','))
                        self.assertIn('--safe-mode',argv)
                        self.assertIn('custom-test-model',argv)
                        self.assertTrue({'run_shell_command','agent','web_search','write_file'} <= excluded)
                        self.assertFalse({'read_file','grep_search','glob','list_directory'} & excluded)

    def test_dsh_and_qwen_fail_closed_on_incomplete_and_incompatible_output(self):
        for backend in ('dsh','qwen'):
            modes = ('truncated','malformed','error','terminal-failure','unsupported')
            for mode in (*modes,'mismatched-final') if backend=='dsh' else modes:
                with self.subTest(backend=backend,mode=mode):
                    self.room=self.root/f'{backend}-{mode}.sqlite'
                    self.initialize(backend)
                    (self.root/'mode').write_text(mode)
                    self.reply(ok=False)
                    self.assertEqual(self.command('consult.py','status')['status']['message_count'],1)

    def test_hermes_and_qoder_reuse_native_sessions_for_meeting_assignments(self):
        for backend, host in (('hermes', 'qoder'), ('qoder', 'hermes')):
            with self.subTest(backend=backend):
                self.room = self.root / f'{backend}.sqlite'
                self.initialize(backend, host, '--model', 'custom-test-model')
                native = self.reply()['model']['native_session_id']
                self.send(host)
                self.assertEqual(self.reply('second')['model']['native_session_id'], native)
                spec = self.root / 'native-web-task.json'
                spec.write_text(json.dumps({'title': 'Check source', 'instructions': 'Verify provided evidence',
                    'context': 'Use public sources if available', 'constraints': [],
                    'acceptance_criteria': ['Use a citation']}))
                self.command('meeting.py', 'assign', '--as', host, '--to', backend, '--type', 'readonly',
                             '--task-id', 'verify', '--request-id', 'assign', '--file', spec)
                self.command('meeting.py', 'run', '--as', host, '--task-id', 'verify', '--request-id', 'run')
                calls = self.calls(backend)
                self.assertEqual([call['session'] for call in calls], [native] * 3)
                self.assertNotIn('--resume', calls[0]['argv'])
                for call in calls[1:]:
                    argv = call['argv']
                    self.assertEqual(argv[argv.index('--resume') + 1], native)
                    self.assertEqual(argv[argv.index('--model') + 1], 'custom-test-model')
                self.assertFalse(peer.paths(self.room, host).exists())
                self.assertEqual(calls[-1]['context']['task']['title'], 'Check source')

    def test_hermes_and_qoder_reject_errors_or_unexpected_tools(self):
        for backend in ('hermes', 'qoder'):
            for mode in ('truncated', 'malformed', 'error', 'terminal-failure', 'unsupported',
                         'mismatched-final', 'unexpected-tool'):
                with self.subTest(backend=backend, mode=mode):
                    self.room = self.root / f'{backend}-{mode}.sqlite'
                    self.initialize(backend)
                    (self.root / 'mode').write_text(mode)
                    self.reply(ok=False)
                    self.assertEqual(self.command('consult.py', 'status')['status']['message_count'], 1)

    def test_antigravity_resumes_through_promotion_and_readonly_assignment(self):
        self.initialize('antigravity', 'codex', '--model', 'fixture-model')
        native = self.reply()['model']['native_session_id']
        self.send('codex')
        self.assertEqual(self.reply('followup')['model']['native_session_id'], native)
        spec = self.root / 'agy-task.json'
        spec.write_text(json.dumps({'title': 'Inspect evidence', 'instructions': 'Review project facts',
                                    'context': 'Evidence review', 'constraints': [],
                                    'acceptance_criteria': ['Name the original evidence']}))
        self.command('meeting.py', 'assign', '--as', 'codex', '--to', 'antigravity', '--type', 'readonly',
                     '--task-id', 'inspect', '--request-id', 'assign', '--file', spec)
        self.command('meeting.py', 'run', '--as', 'codex', '--task-id', 'inspect', '--request-id', 'run')
        calls = self.calls('antigravity')
        self.assertEqual(len(calls), 3)
        self.assertNotIn('--conversation', calls[0]['argv'])
        for call in calls[1:]:
            argv = call['argv']
            self.assertEqual(argv[argv.index('--conversation') + 1], native)
            self.assertEqual(argv[argv.index('--model') + 1], 'fixture-model')
        self.assertEqual(calls[-1]['context']['task']['title'], 'Inspect evidence')
        self.assertEqual(adapters.default_cli('antigravity'), 'agy')

    def test_antigravity_rejects_incomplete_turns_and_different_conversations(self):
        for mode in ('truncated', 'waiting', 'wrong-agent', 'switch'):
            with self.subTest(mode=mode):
                self.room = self.root / f'agy-{mode}.sqlite'
                mode_path = self.root / 'mode'
                mode_path.unlink(missing_ok=True)
                self.initialize('antigravity')
                native = self.reply()['model']['native_session_id']
                self.send()
                mode_path.write_text(mode)
                self.reply('followup', ok=False)
                state = self.command('consult.py', 'status')
                self.assertEqual(state['status']['message_count'], 3)
                self.assertEqual(state['model']['native_session_id'], native)

    def test_invalid_new_engine_outputs_never_become_discussion_messages(self):
        for backend in ('pi','opencode'):
            for mode in ('malformed','length','error','bad-shape'):
                if backend=='pi' and mode=='error':mode='no-session'
                with self.subTest(backend=backend,mode=mode):
                    self.room=self.root/(backend+mode+'.sqlite')
                    self.initialize(backend)
                    (self.root/'mode').write_text(mode)
                    self.reply(ok=False)
                    state=self.command('consult.py','status')
                    self.assertEqual(state['status']['message_count'],1)

    def test_different_session_is_refused_on_resume_for_new_engines(self):
        for backend in ('pi','opencode','dsh','qwen','hermes','qoder'):
            with self.subTest(backend=backend):
                self.room=self.root/(backend+'.sqlite');self.initialize(backend);first=self.reply();self.send()
                (self.root/'mode').write_text('switch')
                self.reply('switch',ok=False)
                current=self.command('consult.py','status')
                self.assertEqual(current['model']['native_session_id'],first['model']['native_session_id'])
                self.assertEqual(current['status']['message_count'],3)
                (self.root/'mode').unlink()

    def test_missing_pi_session_file_refuses_replacement(self):
        self.initialize('pi');self.reply();self.send()
        adapters.Pi.session_file(peer.paths(self.room,'pi')).unlink()
        failure=self.reply('missing',ok=False)
        self.assertIn('original session file is missing',failure['error'])
        self.assertEqual(len(self.calls('pi')),1)

    def test_same_engine_host_gets_distinct_reviewer_identity(self):
        result=self.initialize('claude')
        self.assertEqual(result['status']['participants'],['claude','claude-peer'])

    def test_legacy_consult_configuration_defaults_to_claude(self):
        self.initialize('claude','codex')
        path=Path(str(self.room)+'.consult')/'config.json'
        config=json.loads(path.read_text());config.pop('backend');config.pop('model');path.write_text(json.dumps(config))
        self.assertEqual(self.reply()['event']['sender'],'claude')

    def test_new_adapters_use_shared_timeout_and_record_no_reply(self):
        for backend in ('pi','opencode','hermes','qoder'):
            with self.subTest(backend=backend):
                self.room=self.root/(backend+'-timeout.sqlite');self.initialize(backend)
                (self.root/'mode').write_text('delay')
                self.command('consult.py','reply','--request-id','timeout','--turn-timeout','1',ok=False)
                current=self.command('consult.py','status')
                self.assertEqual(current['status']['message_count'],1)
                self.assertEqual(current['model']['state'],'failed')
        with mock.patch.object(adapters.subprocess, 'run', side_effect=subprocess.TimeoutExpired('cli',10)):
            with self.assertRaises(peer.chat.ChatError):adapters.probe(['cli'],'--help',str(self.root))

    def test_opencode_does_not_replace_an_existing_inline_configuration(self):
        self.initialize('opencode')
        with mock.patch.dict(os.environ, {'OPENCODE_CONFIG_CONTENT':'{"model":"user/model"}'}):
            failure=self.reply(ok=False)
        self.assertIn('already set',failure['error'])
        self.assertFalse((self.root/'calls-opencode.jsonl').exists())

    def test_unsupported_engine_is_rejected_before_creating_room(self):
        with self.assertRaises(Exception):peer.cli_prefix(str(self.clis['pi']),'unknown')
        self.assertFalse(self.room.exists())

    def test_windows_pi_npm_wrapper_resolves_without_shell(self):
        for entry in adapters.REGISTRY['pi'].npm_entries:
            with self.subTest(entry=entry):
                wrapper=self.root/'pi.cmd';wrapper.write_text('do not execute')
                script=self.root/'node_modules'/entry;script.parent.mkdir(parents=True,exist_ok=True);script.write_text('')
                with mock.patch.object(peer.shutil,'which',side_effect=[str(wrapper),'/path/node.exe']):
                    self.assertEqual(peer.cli_prefix('pi','pi'),['/path/node.exe',str(script)])
                script.unlink()

    def test_windows_qoder_npm_wrapper_resolves_without_shell(self):
        wrapper = self.root / 'qoder.cmd'
        wrapper.write_text('do not execute')
        script = self.root / 'node_modules' / adapters.Qoder.npm_entries[0]
        script.parent.mkdir(parents=True)
        script.write_text('')
        with mock.patch.object(peer.shutil, 'which', side_effect=[str(wrapper), '/path/node.exe']):
            self.assertEqual(peer.cli_prefix('qoder', 'qoder'), ['/path/node.exe', str(script)])
