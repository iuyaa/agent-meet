"""Published-package updates, real filesystem rollback, Git fast-forwards and leases."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import runtime
import update


def files(version):
    return {'VERSION': (version+'\n').encode(), 'SKILL.md': ('# Agent-Meet '+version+'\n').encode(),
            'scripts/update.py': b'# updater fixture\n', 'scripts/runtime.py': b'# runtime fixture\n',
            'vendor/example-LICENSE': b'License text\n',
            'new.txt' if version == '1.1.0' else 'removed.txt': version.encode()}


def add_manifest(content, version):
    content = dict(content)
    content[update.MANIFEST] = json.dumps({'format':1, 'version':version,
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in content.items()}}).encode()
    return content


def archive(content, entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as handle:
        for name, raw in (entries or [('agent-meet/'+n,b) for n,b in content.items()]):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            handle.writestr(info, raw)
    return output.getvalue()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.area = Path(self.temp.name)
        self.root = self.area / 'skill 空格'
        self.root.mkdir()
        self.old = add_manifest(files('1.0.0'), '1.0.0')
        self.new = add_manifest(files('1.1.0'), '1.1.0')
        self.write(self.root, self.old)
        self.data = archive(self.new)
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.requests = []
        self.environment = mock.patch.dict(os.environ, {'XDG_CACHE_HOME':str(self.area/'cache'), 'LOCALAPPDATA':str(self.area/'cache')})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def write(self, root, content):
        for name, raw in content.items():
            path = root / name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)

    def fetch(self, url, limit):
        self.requests.append(url)
        if url.endswith('/main/VERSION'):
            return b'1.1.0\n'
        if url.endswith('.sha256'):
            return (self.digest+'  agent-meet-v1.1.0.zip\n').encode()
        if url.endswith('.zip'):
            return self.data
        self.fail('unexpected URL '+url)

    def apply(self, **kwargs):
        return update.preflight(self.root, apply=True, fetcher=self.fetch, **kwargs)

    def test_check_then_apply_uses_cached_metadata_and_preserves_extra_room_data_and_backup(self):
        room = self.root/'.agent-meet'/'room.sqlite'
        room.parent.mkdir()
        room.write_bytes(b'room-and-session-evidence')
        (self.root/'installer-metadata.json').write_text('preserve this too')
        checked = update.preflight(self.root,fetcher=self.fetch)
        self.assertEqual(checked['state'],'available')
        self.assertEqual((self.root/'VERSION').read_text().strip(),'1.0.0')
        self.assertEqual(len(self.requests),2)
        result = self.apply()
        self.assertEqual(result['state'],'updated',result)
        self.assertTrue(result['cached'])
        self.assertEqual(len(self.requests),3)
        self.assertEqual((self.root/'new.txt').read_bytes(),b'1.1.0')
        self.assertFalse((self.root/'removed.txt').exists())
        self.assertEqual(room.read_bytes(),b'room-and-session-evidence')
        self.assertEqual((self.root/'installer-metadata.json').read_text(),'preserve this too')
        backup = Path(result['backup'])
        self.assertEqual((backup/'VERSION').read_text().strip(),'1.0.0')
        self.assertEqual((backup/'.agent-meet'/'room.sqlite').read_bytes(),room.read_bytes())
        self.assertEqual(self.apply()['state'],'current')
        self.assertEqual(len(self.requests),3)

    def test_offline_failure_does_not_block_or_mutate_the_installation(self):
        result = update.preflight(self.root,apply=True,fetcher=mock.Mock(side_effect=OSError('offline')))
        self.assertEqual(result['state'],'deferred')
        self.assertTrue(result['can_continue'])
        self.assertEqual((self.root/'SKILL.md').read_bytes(),self.old['SKILL.md'])

    def test_unwritable_cache_defers_cli_update_without_blocking_current_skill(self):
        output = io.StringIO()
        with mock.patch.object(runtime, 'control', side_effect=PermissionError('cache read only')), mock.patch('sys.stdout', output):
            code = update.main(['apply'])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['state'], 'deferred')
        self.assertTrue(result['can_continue'])
        self.assertFalse(result['updated'])

    def test_unpublished_version_does_not_offer_or_install_an_update(self):
        def unpublished(url,limit):
            if url.endswith('/VERSION'):
                return b'1.1.0'
            raise OSError('404: release not published yet')
        result = update.preflight(self.root,apply=True,fetcher=unpublished)
        self.assertEqual(result['state'],'deferred')
        self.assertFalse(result['updated'])
        self.assertFalse(list(self.root.parent.glob('.agent-meet-backup-*')))

    def test_local_file_edits_or_deletions_are_preserved_and_update_defers(self):
        (self.root/'SKILL.md').write_text('local custom instructions')
        result = self.apply()
        self.assertEqual(result['state'],'deferred')
        self.assertIn('local file',result['detail'])
        self.assertEqual((self.root/'SKILL.md').read_text(),'local custom instructions')
        self.assertFalse(any(url.endswith('.zip') for url in self.requests))
        (self.root/'SKILL.md').write_bytes(self.old['SKILL.md'])
        (self.root/'removed.txt').unlink()
        self.assertEqual(self.apply()['state'],'deferred')
        self.assertFalse((self.root/'removed.txt').exists())

    def test_fresh_installer_crlf_text_files_are_not_mistaken_for_custom_edits(self):
        for name, raw in self.old.items():
            (self.root/name).write_bytes(raw.replace(b'\n', b'\r\n'))
        result = self.apply()
        self.assertEqual(result['state'], 'updated', result)
        self.assertEqual((self.root/'VERSION').read_bytes(), b'1.1.0\n')
        self.assertEqual((Path(result['backup'])/'SKILL.md').read_bytes(), self.old['SKILL.md'].replace(b'\n', b'\r\n'))

    def test_unknown_file_conflict_and_missing_manifest_never_overwrite_user_content(self):
        (self.root/'new.txt').write_text('user file')
        self.assertEqual(self.apply()['state'],'deferred')
        self.assertEqual((self.root/'new.txt').read_text(),'user file')
        (self.root/update.MANIFEST).unlink()
        result = self.apply()
        self.assertEqual(result['state'],'deferred')
        self.assertEqual((self.root/'VERSION').read_text().strip(),'1.0.0')

    def test_bad_checksum_refuses_package_before_replacing_files(self):
        self.data = self.data[:-1]+b'x'
        result = self.apply()
        self.assertEqual(result['state'],'deferred')
        self.assertIn('SHA-256',result['detail'])
        self.assertEqual((self.root/'SKILL.md').read_bytes(),self.old['SKILL.md'])

    def test_bad_inventory_is_rejected_even_when_archive_checksum_matches(self):
        damaged = dict(self.new, **{'SKILL.md':b'tampered'})
        self.data = archive(damaged)
        self.digest = hashlib.sha256(self.data).hexdigest()
        result = self.apply()
        self.assertEqual(result['state'],'deferred')
        self.assertIn('manifest mismatch',result['detail'])

    def test_zip_slip_duplicate_case_and_symlink_entries_are_rejected(self):
        for name, mode in [('agent-meet/../outside',0o100644),('agent-meet/C:/bad',0o100644),
                           ('other/SKILL.md',0o100644),('agent-meet/evil',0o120777)]:
            data = io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:
                row=zipfile.ZipInfo(name);row.external_attr=mode<<16
                z.writestr(row,b'bad')
            with self.assertRaises(update.UpdateError):
                update.package(data.getvalue(),hashlib.sha256(data.getvalue()).hexdigest(),'1.1.0')
        duplicate = archive({},[('agent-meet/FILE',b'a'),('agent-meet/file',b'b')])
        with self.assertRaises(update.UpdateError):
            update.package(duplicate,hashlib.sha256(duplicate).hexdigest(),'1.1.0')
        self.assertFalse((self.area/'outside').exists())

    @unittest.skipIf(os.name=='nt','requires symlink creation privileges')
    def test_symlink_install_root_is_kept_and_internal_managed_symlinks_are_refused(self):
        alias = self.area/'linked-skill'
        alias.symlink_to(self.root,target_is_directory=True)
        result = update.preflight(alias,apply=True,fetcher=self.fetch)
        self.assertEqual(result['state'],'updated')
        self.assertTrue(alias.is_symlink())
        self.assertEqual((alias/'VERSION').read_text().strip(),'1.1.0')
        # A separately managed path must never be written through a link.
        other = self.area/'other-skill';other.mkdir()
        self.write(other,self.old)
        outside=self.area/'outside.md';outside.write_bytes(self.old['SKILL.md'])
        (other/'SKILL.md').unlink();(other/'SKILL.md').symlink_to(outside)
        result=update.preflight(other,apply=True,fetcher=self.fetch)
        self.assertEqual(result['state'],'deferred')
        self.assertEqual(outside.read_bytes(),self.old['SKILL.md'])

    def test_failed_final_rename_restores_the_complete_old_installation(self):
        original = os.replace
        def fail_stage(source,target):
            if Path(source).name.startswith('.agent-meet-stage-'):
                raise OSError('injected final rename failure')
            return original(source,target)
        with mock.patch.object(update.os,'replace',side_effect=fail_stage):
            result = self.apply()
        self.assertEqual(result['state'],'deferred')
        self.assertTrue(result['can_continue'])
        for name,raw in self.old.items():
            self.assertEqual((self.root/name).read_bytes(),raw)

    def test_edit_during_staging_is_preserved_and_prevents_cutover(self):
        original = shutil.copytree
        def edit_after_copy(source, destination, *args, **kwargs):
            result = original(source, destination, *args, **kwargs)
            if Path(source) == self.root:
                (self.root/'SKILL.md').write_text('user edit during staging')
            return result
        with mock.patch.object(update.shutil, 'copytree', side_effect=edit_after_copy):
            result = self.apply()
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual((self.root/'SKILL.md').read_text(), 'user edit during staging')
        self.assertEqual((self.root/'VERSION').read_text().strip(), '1.0.0')

    def test_actual_chat_entry_point_defers_while_installation_is_updating(self):
        shutil.copytree(SCRIPTS, self.root/'scripts', dirs_exist_ok=True)
        with runtime.Lease(self.root, exclusive=True):
            result = subprocess.run([sys.executable, str(self.root/'scripts'/'chat.py'), 'status', '--room', str(self.area/'missing.sqlite')],
                                    capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        value = json.loads(result.stderr)
        self.assertIn('updating', value['error'])
        self.assertNotIn('Traceback', result.stderr)

    def test_shared_runtime_lease_defers_update_and_releases_after_process_exit(self):
        code = "import sys; sys.path.insert(0,sys.argv[1]); import runtime; lease=runtime.reader(sys.argv[2]); print('ready',flush=True); sys.stdin.read()"
        process = subprocess.Popen([sys.executable,'-c',code,str(SCRIPTS),str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(),'ready')
            with runtime.Lease(self.root):
                self.assertEqual(self.apply()['state'],'busy')
            self.assertFalse(any(url.endswith('.zip') for url in self.requests))
        finally:
            process.communicate('',timeout=5)
        self.assertEqual(self.apply()['state'],'updated')

    def test_exclusive_updater_lease_refuses_new_readers(self):
        with runtime.Lease(self.root,exclusive=True):
            with self.assertRaises(runtime.Busy):
                runtime.Lease(self.root)
        with runtime.Lease(self.root):
            pass

    def test_corrupt_cache_is_ignored_and_force_check_bypasses_fresh_cache(self):
        cache=runtime.control(self.root)/'update.json'
        cache.write_text('{"checked_at": "bad", "latest_version": "oops"}')
        self.assertEqual(update.preflight(self.root,fetcher=self.fetch)['state'],'available')
        self.assertEqual(len(self.requests),2)
        update.preflight(self.root,force=True,fetcher=self.fetch)
        self.assertEqual(len(self.requests),4)

    def test_newer_local_version_is_never_downgraded(self):
        (self.root/'VERSION').write_text('2.0.0\n')
        self.assertEqual(self.apply()['state'],'ahead')
        self.assertEqual((self.root/'VERSION').read_text().strip(),'2.0.0')
        self.assertFalse(any(url.endswith('.zip') for url in self.requests))

    def test_git_dirty_checkout_and_development_branch_are_not_reset(self):
        self.git(self.root,'init','-q','-b','main')
        self.git(self.root,'config','user.name','Test')
        self.git(self.root,'config','user.email','test@test.invalid')
        self.git(self.root,'add','.')
        self.git(self.root,'commit','-qm','baseline')
        (self.root/'SKILL.md').write_text('custom')
        self.assertIn('local changes',self.apply()['detail'])
        self.git(self.root,'restore','SKILL.md')
        self.git(self.root,'checkout','-qb','development')
        self.assertIn('development branch',self.apply()['detail'])
        self.assertEqual(self.git(self.root,'branch','--show-current'),'development')

    def git(self,root,*args):
        return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()

    def test_real_git_fast_forward_retains_checkout_and_records_previous_commit(self):
        upstream=self.area/'upstream'
        shutil.copytree(self.root,upstream)
        self.git(upstream,'init','-q','-b','main')
        self.git(upstream,'config','user.name','Test')
        self.git(upstream,'config','user.email','test@test.invalid')
        self.git(upstream,'add','.')
        self.git(upstream,'commit','-qm','baseline')
        shutil.rmtree(self.root)
        subprocess.check_call(['git','clone','-q',str(upstream),str(self.root)])
        before=self.git(self.root,'rev-parse','HEAD')
        self.git(self.root,'remote','set-url','origin','https://github.com/iuyaa/agent-meet.git')
        (upstream/'removed.txt').unlink()
        self.write(upstream,self.new)
        self.git(upstream,'add','-A');self.git(upstream,'commit','-qm','release')
        self.git(upstream,'tag','v1.1.0')
        def runner(root,*args):
            if args[0]=='fetch':
                return self.git(root,'fetch','--no-tags',str(upstream),'refs/tags/v1.1.0')
            return update.git(root,*args)
        actual=update.git_update
        with mock.patch.object(update,'git_update',side_effect=lambda root,target:actual(root,target,runner=runner)):
            result=self.apply()
        self.assertEqual(result['state'],'updated',result)
        self.assertEqual(result['installation_kind'],'git')
        self.assertEqual(result['previous_commit'],before)
        self.assertEqual(self.git(self.root,'branch','--show-current'),'main')
        self.assertEqual(self.git(self.root,'status','--porcelain'),'')
        self.assertEqual((self.root/'VERSION').read_text().strip(),'1.1.0')


if __name__=='__main__':
    unittest.main()
