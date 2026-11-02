"""Shared launch policy for noninteractive agent and service processes."""

import os
import subprocess
import contextlib
import signal
import time


WINDOWS = os.name == "nt"


def launch_options(*, background=False):
    """Do not allocate a Windows console; detach background services on POSIX."""
    if WINDOWS:
        # DETACHED_PROCESS must not be combined with CREATE_NO_WINDOW: Windows
        # ignores CREATE_NO_WINDOW in that combination. All callers redirect
        # stdin/stdout/stderr, so neither workers nor CLIs need a console.
        flags = subprocess.CREATE_NO_WINDOW
        if background:
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags}
    return {"start_new_session": True} if background else {}


def windows_job(process):
    """Own descendants through a kill-on-close job (no console allocation)."""
    import ctypes
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", w.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", w.DWORD), ("scheduling", w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ro", "wo", "oo", "rb", "wb", "ob")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                    ("peak_job", ctypes.c_size_t)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    api.CreateJobObjectW.restype = w.HANDLE
    api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    api.CloseHandle.argtypes = [w.HANDLE]
    handle = api.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not api.AssignProcessToJobObject(handle, int(process._handle)):
        error = ctypes.get_last_error()
        api.CloseHandle(handle)
        raise ctypes.WinError(error)
    return lambda: api.CloseHandle(handle)


def resume_windows(process):
    """Resume the suspended primary thread only after job ownership is installed."""
    import ctypes
    from ctypes import wintypes as w
    class Thread(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("id", w.DWORD),
                    ("owner", w.DWORD), ("base", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    api.CreateToolhelp32Snapshot.restype = w.HANDLE
    api.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(Thread)]
    api.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(Thread)]
    api.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenThread.restype = w.HANDLE
    api.ResumeThread.argtypes = [w.HANDLE]
    api.ResumeThread.restype = w.DWORD
    api.CloseHandle.argtypes = [w.HANDLE]
    snapshot = api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Thread()
        entry.size = ctypes.sizeof(entry)
        more = api.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.owner == process.pid:
                handle = api.OpenThread(2, False, entry.id)  # THREAD_SUSPEND_RESUME
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if api.ResumeThread(handle) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    api.CloseHandle(handle)
                return
            more = api.Thread32Next(snapshot, ctypes.byref(entry))
        raise OSError("cannot find the suspended task process thread")
    finally:
        api.CloseHandle(snapshot)


@contextlib.contextmanager
def owned(command, **kwargs):
    """Task commands cannot leave their ordinary process descendants running."""
    options = launch_options(background=True)
    if WINDOWS:
        options["creationflags"] |= 0x00000004  # CREATE_SUSPENDED: attach before any child can run.
    process = subprocess.Popen(command, **kwargs, **options)
    close_job = None
    try:
        if WINDOWS:
            close_job = windows_job(process)
            resume_windows(process)
        yield process
    finally:
        if close_job:
            close_job()
        elif not WINDOWS:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                time.sleep(0.15)
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait()
