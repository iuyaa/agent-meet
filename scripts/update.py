#!/usr/bin/env python3
"""Check/install published Agent-Meet packages without replacing busy or edited skills."""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import runtime

REPOSITORY = 'https://raw.githubusercontent.com/iuyaa/agent-meet'
MANIFEST = 'INSTALL-MANIFEST.json'
MAX_PACKAGE = 16 * 1024 * 1024
MAX_CONTENT = 128 * 1024 * 1024


class UpdateError(Exception):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise UpdateError('invalid stable version')
    return tuple(map(int, value.split('.')))


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'Agent-Meet-Updater', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=5) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('download exceeds size limit')
    return data


def checksum(data, expected_name):
    match = re.fullmatch(r'([a-f0-9]{64})  ' + re.escape(expected_name) + r'\s*', data.decode('ascii'))
    if not match:
        raise UpdateError('invalid published package checksum')
    return match[1]


def safe_path(name):
    parts = PurePosixPath(name).parts
    if (not name or '\\' in name or ':' in name or name.startswith('/') or
            any(p in ('', '.', '..') or p.endswith((' ', '.')) or any(ord(c) < 32 for c in p)
                or p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}
                for p in name.split('/')) or not parts):
        raise UpdateError('unsafe package path: ' + name)
    return parts


def manifest(value, expected_version):
    if not isinstance(value, dict) or set(value) != {'format', 'version', 'files'} or value['format'] != 1:
        raise UpdateError('unsupported installation manifest')
    if value['version'] != expected_version or not isinstance(value['files'], dict) or not value['files']:
        raise UpdateError('manifest version/files do not match installation')
    for name, digest in value['files'].items():
        safe_path(name)
        if name == MANIFEST or name.startswith('releases/') or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise UpdateError('invalid manifest entry')
    if not {'SKILL.md', 'VERSION', 'scripts/update.py', 'scripts/runtime.py'} <= set(value['files']):
        raise UpdateError('incomplete Agent-Meet package')
    return value


def package(data, digest, target):
    if hashlib.sha256(data).hexdigest() != digest:
        raise UpdateError('package SHA-256 mismatch; installation unchanged')
    content, modes, folded = {}, {}, set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(row.file_size for row in archive.infolist()) > MAX_CONTENT:
            raise UpdateError('expanded package exceeds size limit')
        for row in archive.infolist():
            if not row.filename.startswith('agent-meet/'):
                raise UpdateError('unexpected package root')
            name = row.filename[len('agent-meet/'):]
            safe_path(name)
            mode = row.external_attr >> 16
            if (row.is_dir() or mode not in (0o100644, 0o100755) or name.casefold() in folded or
                    row.flag_bits & 1 or row.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise UpdateError('package contains a symlink, duplicate or unsupported entry')
            folded.add(name.casefold())
            content[name], modes[name] = archive.read(row), mode & 0o777
    value = manifest(json.loads(content.get(MANIFEST, b'null')), target)
    if set(content) != set(value['files']) | {MANIFEST} or content['VERSION'].decode().strip() != target:
        raise UpdateError('package inventory/version mismatch')
    for name, expected in value['files'].items():
        if hashlib.sha256(content[name]).hexdigest() != expected:
            raise UpdateError('package manifest mismatch: ' + name)
    return content, modes


def regular(root, name):
    path = root
    for part in safe_path(name):
        path = path / part
        if path.is_symlink():
            raise UpdateError('managed path is a symlink: ' + name)
    return path


def local_manifest(root, current):
    value = manifest(json.loads(regular(root, MANIFEST).read_text(encoding='utf-8')), current)
    for name, digest in value['files'].items():
        path = regular(root, name)
        raw = path.read_bytes() if path.is_file() else b''
        text_file = path.suffix.lower() in {'.py', '.md', '.js', '.cjs', '.css', '.json', '.html', '.txt'} or path.name in {'VERSION', 'LICENSE', '.gitignore'} or path.name.endswith('-LICENSE')
        unchanged = path.is_file() and (hashlib.sha256(raw).hexdigest() == digest or
                    text_file and hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() == digest)
        if not unchanged:
            raise UpdateError('local file was changed or removed: ' + name)
    return value


def replace(root, current, target, data, digest):
    old = local_manifest(root, current)
    content, modes = package(data, digest, target)
    for name, incoming in content.items():
        path = regular(root, name)
        if path.exists() and not path.is_file():
            raise UpdateError('new package conflicts with a local directory: ' + name)
        if name not in old['files'] and name != MANIFEST and path.exists() and path.read_bytes() != incoming:
            raise UpdateError('new package conflicts with a local extra file: ' + name)
    # Stage a full copy so unknown files, old room data and installer metadata survive.
    stage = Path(tempfile.mkdtemp(prefix='.agent-meet-stage-', dir=root.parent))
    backup = root.with_name('.agent-meet-backup-' + current + '-' + uuid.uuid4().hex[:10])
    try:
        shutil.copytree(root, stage, dirs_exist_ok=True, symlinks=True)
        for name in set(old['files']) - set(content):
            (stage / name).unlink()
        for name, raw in content.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # Never write through hard links copied from an unusual installation.
            path.unlink(missing_ok=True)
            path.write_bytes(raw)
            path.chmod(modes[name])
        local_manifest(root, current)  # Catch edits made while downloading/staging.
        os.replace(root, backup)
        try:
            os.replace(stage, root)
        except BaseException:
            try:
                os.replace(backup, root)
            except OSError as exc:
                raise UpdateError('installation swap failed; full original backup is at ' + str(backup)) from exc
            raise
        # Keep backup skills outside the host's skill-discovery directory.
        try:
            destination = runtime.control(root) / 'backups' / backup.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(destination))
            return {'backup': str(destination), 'installation_kind': 'files'}
        except OSError:
            return {'backup': str(backup), 'installation_kind': 'files',
                    'backup_warning': 'update succeeded; backup could not be moved to the user cache'}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        # A successful update intentionally keeps its backup. A failed swap is restored.


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=30, **launch_options())
    if result.returncode:
        # Avoid echoing remote URLs, credentials or user-controlled hooks into JSON.
        raise UpdateError('Git update could not fast-forward; installation was not reset')
    return result.stdout.decode('utf-8', 'replace').strip()


def launch_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def git_update(root, target, runner=git):
    if runner(root, 'status', '--porcelain'):
        raise UpdateError('Git checkout has local changes; automatic update deferred')
    if runner(root, 'branch', '--show-current') != 'main':
        raise UpdateError('Git checkout is pinned or on a development branch; automatic update deferred')
    remote = runner(root, 'remote', 'get-url', 'origin')
    if remote not in ('https://github.com/iuyaa/agent-meet.git', 'https://github.com/iuyaa/agent-meet',
                       'git@github.com:iuyaa/agent-meet.git', 'ssh://git@github.com/iuyaa/agent-meet.git'):
        raise UpdateError('origin is not the official Agent-Meet repository; automatic update deferred')
    before = runner(root, 'rev-parse', 'HEAD')
    runner(root, 'fetch', '--no-tags', 'origin', 'refs/tags/v' + target)
    target_commit = runner(root, 'rev-parse', 'FETCH_HEAD^{commit}')
    if runner(root, 'show', target_commit + ':VERSION') != target:
        raise UpdateError('published Git tag has a different version')
    runner(root, 'merge-base', '--is-ancestor', before, target_commit)
    runner(root, '-c', 'core.hooksPath=', 'merge', '--ff-only', '--no-edit', target_commit)
    return {'installation_kind': 'git', 'previous_commit': before, 'commit': target_commit}


def write_cache(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def preflight(root, apply=False, force=False, fetcher=fetch):
    root = Path(root).resolve()
    current = (root / 'VERSION').read_text(encoding='utf-8').strip()
    version(current)
    result = {'current_version': current, 'skill_directory': str(root), 'updated': False, 'can_continue': True}
    cache_file = runtime.control(root) / 'update.json'
    try:
        cached = json.loads(cache_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cached = {}
    try:
        version(cached['latest_version'])
        if not re.fullmatch('[a-f0-9]{64}', cached['sha256']) or not isinstance(cached['checked_at'], (int,float)):
            raise ValueError('invalid cached metadata')
    except (KeyError, TypeError, ValueError, UpdateError):
        cached = {}
    age = time.time() - cached.get('checked_at', 0)
    try:
        if not force and 0 <= age < 3600 and isinstance(cached.get('latest_version'), str):
            latest, digest = cached['latest_version'], cached['sha256']
            version(latest)
            result['cached'] = True
        else:
            latest = fetcher(REPOSITORY + '/main/VERSION', 100).decode('ascii').strip()
            version(latest)
            filename = 'agent-meet-v' + latest + '.zip'
            digest = checksum(fetcher(REPOSITORY + '/v' + latest + '/releases/' + filename.replace('.zip', '.sha256'), 256), filename)
            write_cache(cache_file, {'checked_at': time.time(), 'latest_version': latest, 'sha256': digest})
            result['cached'] = False
        result['latest_version'] = latest
        if version(latest) <= version(current):
            return {**result, 'state': 'current' if latest == current else 'ahead'}
        if not apply:
            return {**result, 'state': 'available'}
        with runtime.Lease(root, exclusive=True):
            # Another updater may have completed while this one downloaded metadata.
            actual = (root / 'VERSION').read_text(encoding='utf-8').strip()
            if actual != current:
                return {**result, 'state': 'changed', 'current_version': actual, 'detail': 'reread SKILL.md and check again'}
            if (root / '.git').exists():
                details = git_update(root, latest)
            else:
                local_manifest(root, current)  # Refuse local edits before fetching a large archive.
                data = fetcher(REPOSITORY + '/v' + latest + '/releases/agent-meet-v' + latest + '.zip', MAX_PACKAGE)
                details = replace(root, current, latest, data, digest)
            return {**result, **details, 'state': 'updated', 'updated': True,
                    'previous_version': current, 'current_version': latest, 'reload_skill': str(root / 'SKILL.md')}
    except runtime.Busy as exc:
        return {**result, 'state': 'busy', 'detail': str(exc)}
    except (OSError, ValueError, KeyError, TypeError, UpdateError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        return {**result, 'state': 'deferred', 'detail': str(exc), 'can_continue': (root / 'SKILL.md').is_file()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'apply'))
    parser.add_argument('--force-check', action='store_true', help='bypass the one-hour metadata cache')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    try:
        result = preflight(root, args.command == 'apply', args.force_check)
        print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=2))
        return 0 if result['can_continue'] else 1
    except (OSError, ValueError, UpdateError) as exc:
        can_continue = (root / 'SKILL.md').is_file()
        print(json.dumps({'ok': False, 'state': 'deferred', 'detail': str(exc),
                          'updated': False, 'can_continue': can_continue}, ensure_ascii=False))
        return 0 if can_continue else 1


if __name__ == '__main__':
    sys.exit(main())
