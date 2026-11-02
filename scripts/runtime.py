"""Cross-process installation leases, stored outside the skill being updated."""

import atexit
import hashlib
import os
import sys
from pathlib import Path


class Busy(Exception):
    pass


def control(root):
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Caches'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    key = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()[:20]
    directory = base / 'agent-meet' / key
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


class Lease:
    def __init__(self, root, exclusive=False):
        path = control(root) / 'runtime.lock'
        self.handle = None
        self.close_handle = None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes as w
            if not path.exists():
                try:
                    with path.open('xb'):
                        pass
                except FileExistsError:
                    pass
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                       w.DWORD, w.DWORD, w.HANDLE]
            api.CreateFileW.restype = w.HANDLE
            api.CloseHandle.argtypes = [w.HANDLE]
            # Readers coexist; an updater needs sole ownership of this handle.
            handle = api.CreateFileW(str(path), 0xC0000000 if exclusive else 0x80000000,
                                     0 if exclusive else 1, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                error = ctypes.get_last_error()
                if error in (32, 33):
                    raise Busy('Agent-Meet tools or its viewer are still running')
                raise ctypes.WinError(error)
            self.close_handle = lambda: api.CloseHandle(handle)
        else:
            import fcntl
            handle = path.open('a+b')
            try:
                fcntl.flock(handle.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                raise Busy('Agent-Meet tools or its viewer are still running') from None
            self.handle = handle

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None
        if self.close_handle:
            self.close_handle()
            self.close_handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def reader(root):
    try:
        lease = Lease(root)
    except OSError:
        # A read-only cache must not disable discussions. Updating cannot acquire
        # its exclusive lease either, so that operation also defers on this host.
        return None
    atexit.register(lease.close)
    return lease
