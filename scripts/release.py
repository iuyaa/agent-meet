#!/usr/bin/env python3
"""Developer-only inventory and reproducible ZIP builder from Git-tracked sources."""

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import update

ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def inventory(files):
    version = files['VERSION'].decode().strip()
    update.version(version)
    return {'format': 1, 'version': version,
            'files': {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())
                      if name != update.MANIFEST}}


def tracked():
    return [name.decode() for name in git('ls-files', '-z').split(b'\0')
            if name and not name.startswith(b'releases/')]


def write_manifest():
    # Hash index blobs, so Git's line-ending filters on Windows cannot produce
    # a manifest that disagrees with the committed package.
    files = {name: git('show', ':' + name) for name in tracked() if name != update.MANIFEST}
    value = inventory(files)
    (ROOT / update.MANIFEST).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'version': value['version'], 'files': len(value['files'])}


def build():
    files, modes = {}, {}
    for row in git('ls-tree', '-r', '-z', 'HEAD').split(b'\0'):
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        name = raw_name.decode()
        if name.startswith('releases/'):
            continue
        mode, kind, blob = metadata.decode().split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('unsupported tracked release file: ' + name)
        files[name], modes[name] = git('cat-file', 'blob', blob), int(mode, 8)
    expected = inventory(files)
    if json.loads(files[update.MANIFEST]) != expected:
        raise ValueError('manifest is stale; stage files, generate manifest, and commit first')
    version = expected['version']
    target = ROOT / 'releases' / ('agent-meet-v' + version + '.zip')
    target.parent.mkdir(exist_ok=True)
    when = datetime.datetime.fromtimestamp(int(git('show', '-s', '--format=%ct', 'HEAD')), datetime.timezone.utc)
    # Exclusive create keeps existing published archives intact.
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo('agent-meet/' + name, when.timetuple()[:6])
            info.create_system = 3
            info.external_attr = modes[name] << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    update.package(data, digest, version)
    target.with_suffix('.sha256').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    return {'version': version, 'package': str(target), 'sha256': digest, 'files': len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('manifest', 'package'))
    args = parser.parse_args()
    try:
        print(json.dumps(write_manifest() if args.command == 'manifest' else build(), indent=2))
        return 0
    except (OSError, ValueError, KeyError, update.UpdateError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
