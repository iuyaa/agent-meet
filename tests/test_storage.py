"""Project-local storage, explicit room compatibility and original-session reuse."""
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_peer import SCRIPTS, FAKE_CLAUDE
import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / '项目 空格'
        self.project.mkdir()
        self.brief = self.root / 'brief.json'
        self.brief.write_text(json.dumps({'question':'方案评审','goal':'确认边界','current_view':'保留上下文',
            'constraints':[],'decisions':[],'rejected_options':[],'code_references':[],'unknowns':[]}),encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, script, action, *args, ok=True):
        run = subprocess.run([sys.executable,str(SCRIPTS/script),action,*map(str,args)],
                             capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertNotIn('Traceback',run.stderr)
        value = json.loads(run.stdout or run.stderr)
        self.assertEqual(run.returncode,0 if ok else 1,value)
        return value

    def consult(self, *extra):
        return self.run_tool('consult.py','init','--cwd',self.project,'--briefing-file',self.brief,
                             '--cli',sys.executable,*extra)

    def test_prepare_keeps_topic_paths_inside_project_and_creates_no_database(self):
        result=self.run_tool('storage.py','prepare','--cwd',self.project,'--topic','../../方案: A/B? *')
        room=Path(result['room'])
        self.assertEqual(room.name,'discussion.sqlite')
        self.assertEqual(room.parent.parent,self.project/'.agent-meet')
        self.assertNotRegex(room.parent.name,r'[.:/\\?*]')
        self.assertFalse(room.exists())
        self.assertEqual(Path(result['briefing_file']).parent,room.parent)
        self.assertEqual(Path(result['roles_file']).parent,room.parent)

    def test_same_topic_concurrent_preparations_are_distinct(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rooms=list(pool.map(lambda _:storage.prepare(self.project,'同一个议题')['room'],range(8)))
        self.assertEqual(len(set(rooms)),8)
        self.assertTrue(all(Path(room).parent.is_dir() for room in rooms))

    def test_nonexistent_project_is_not_created(self):
        missing=self.root/'missing'
        self.run_tool('storage.py','prepare','--cwd',missing,'--topic','review',ok=False)
        self.assertFalse(missing.exists())

    @unittest.skipUnless(shutil.which('git'),'git is needed to verify actual ignore behavior')
    def test_managed_data_is_git_ignored_without_changing_project_configuration(self):
        subprocess.run(['git','init','--quiet',str(self.project)],check=True)
        ignore=self.project/'.gitignore';ignore.write_text('# Project rules\nnode_modules/\n')
        data=storage.prepare(self.project,'review')
        Path(data['room']).write_text('discussion data')
        sidecar=Path(data['room']+'.peers');sidecar.mkdir();(sidecar/'session.json').write_text('{}')
        status=subprocess.check_output(['git','status','--porcelain','--untracked-files=all'],cwd=self.project,text=True)
        self.assertNotIn('.agent-meet',status)
        self.assertEqual(ignore.read_text(),'# Project rules\nnode_modules/\n')
        checked=subprocess.run(['git','check-ignore',data['room'],str(sidecar/'session.json')],cwd=self.project,capture_output=True,text=True)
        self.assertEqual(checked.returncode,0)
        self.assertEqual(len(checked.stdout.splitlines()),2)

    def test_existing_local_ignore_content_is_preserved(self):
        root=self.project/'.agent-meet';root.mkdir();ignore=root/'.gitignore';ignore.write_text('# local rule')
        storage.prepare(self.project,'review');storage.prepare(self.project,'review')
        self.assertEqual(ignore.read_text(),'# local rule\n*\n')

    def test_consult_default_separates_discussions_and_returns_reusable_room_path(self):
        first=self.consult();second=self.consult()
        self.assertNotEqual(first['room'],second['room'])
        for result in (first,second):
            room=Path(result['room'])
            self.assertEqual(room.parent.parent,self.project/'.agent-meet')
            self.assertTrue(room.is_file())
            self.assertEqual(Path(result['briefing_file']).parent,Path(str(room)+'.consult'))
        replay=self.consult('--room',first['room'])
        self.assertTrue(replay['already_initialized'])
        self.assertEqual(replay['room'],first['room'])
        self.assertEqual(self.run_tool('consult.py','status','--room',first['room'])['room'],first['room'])

    def test_group_default_uses_same_project_layout(self):
        roles=self.root/'roles.json'
        roles.write_text(json.dumps([{'id':'pm','title':'产品经理','focus':'价值','cli':sys.executable}]),encoding='utf-8')
        result=self.run_tool('group.py','init','--cwd',self.project,'--briefing-file',self.brief,'--roles-file',roles)
        self.assertEqual(Path(result['room']).parent.parent,self.project/'.agent-meet')
        self.assertEqual(result['status']['participants'],['codex','pm'])
        self.assertTrue(Path(str(result['room'])+'.group').is_dir())
        self.assertEqual(self.run_tool('group.py','status','--room',result['room'])['room'],result['room'])

    def test_explicit_external_room_keeps_original_path_and_project_untouched(self):
        room=self.root/'original.sqlite'
        result=self.consult('--room',room)
        self.assertEqual(result['room'],str(room))
        self.assertFalse((self.project/'.agent-meet').exists())
        self.assertTrue(self.consult('--room',room)['already_initialized'])

    def test_prepared_directory_can_hold_inputs_and_initialize_without_another_directory(self):
        prepared=storage.prepare(self.project,'review')
        Path(prepared['briefing_file']).write_bytes(self.brief.read_bytes())
        result=self.run_tool('consult.py','init','--cwd',self.project,'--room',prepared['room'],
                             '--briefing-file',prepared['briefing_file'],'--cli',sys.executable)
        self.assertEqual(result['room'],prepared['room'])
        directories=[p for p in (self.project/'.agent-meet').iterdir() if p.is_dir()]
        self.assertEqual(directories,[Path(prepared['discussion_directory'])])

    @unittest.skipIf(os.name=='nt','symlink creation can require Windows privileges')
    def test_managed_directory_symlink_does_not_redirect_default_storage(self):
        outside=self.root/'outside';outside.mkdir()
        (self.project/'.agent-meet').symlink_to(outside,target_is_directory=True)
        self.run_tool('storage.py','prepare','--cwd',self.project,'--topic','review',ok=False)
        self.assertEqual(list(outside.iterdir()),[])

    def test_followup_commands_require_explicit_room_to_avoid_picking_another_discussion(self):
        self.consult()
        for script,command in [('consult.py','status'),('consult.py','reply'),('group.py','status'),('group.py','round')]:
            result=subprocess.run([sys.executable,str(SCRIPTS/script),command],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('--room',result.stderr)

    @unittest.skipIf(os.name=='nt','fake CLI uses a Unix shebang')
    def test_default_room_continues_original_reviewer_after_budget_extension(self):
        cli=self.root/'fake claude';cli.write_text(FAKE_CLAUDE,encoding='utf-8');cli.chmod(0o755)
        initialized=self.consult('--cli',cli,'--max-messages','2');room=initialized['room']
        first=self.run_tool('consult.py','reply','--room',room,'--request-id','reply1')
        self.run_tool('chat.py','extend','--room',room,'--as','codex','--request-id','more','--rounds','1','--reason','用户要求继续')
        self.run_tool('chat.py','send','--room',room,'--as','codex','--request-id','question2','--text','核实上一轮依据')
        second=self.run_tool('consult.py','reply','--room',room,'--request-id','reply2')
        self.assertEqual(first['model']['native_session_id'],second['model']['native_session_id'])
        self.assertEqual(second['room'],room)
        calls=[json.loads(line) for line in (self.project/'fake-cli-calls.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(calls),2);self.assertIn('--resume',calls[1]['argv'])
