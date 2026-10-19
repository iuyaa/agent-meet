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
        for name, body in [('claude', FAKE_CLAUDE), ('codex', FAKE_CODEX), ('pi', FAKE_AGENT), ('opencode', FAKE_AGENT)]:
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

    def test_one_group_can_mix_all_four_engines_under_opencode_host(self):
        roles=[{'id':name+'-role','title':name,'focus':'核实证据','backend':name,'cli':str(cli)} for name,cli in self.clis.items()]
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
        for backend in ('pi','opencode'):
            calls=self.calls(backend+'-role');self.assertEqual(len(calls),2)
            self.assertEqual(calls[1]['context']['your_role']['backend'],backend)

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
        for backend in ('pi','opencode'):
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
        for backend in ('pi','opencode'):
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
