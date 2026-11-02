"""Console-free launches without changing foreground ownership or POSIX sessions."""

import json
import os
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import processes


class ProcessLaunchTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires native Windows Job Objects and console APIs")
    def test_owned_windows_process_has_no_console_and_cleans_descendants_after_exit(self):
        import ctypes
        from ctypes import wintypes as w
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "process.json"
            code = """
import ctypes, json, pathlib, subprocess, sys
ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
pathlib.Path(sys.argv[1]).write_text(json.dumps({'console': ctypes.windll.kernel32.GetConsoleWindow(), 'child': child.pid}))
"""
            with processes.owned([sys.executable, "-c", code, str(output)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
                self.assertEqual(process.wait(timeout=10), 0)
            value = json.loads(output.read_text())
            self.assertIsNone(value["console"])
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
            api.OpenProcess.restype = w.HANDLE
            api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
            api.CloseHandle.argtypes = [w.HANDLE]
            handle = api.OpenProcess(0x00100000, False, value["child"])
            if handle:
                try:
                    self.assertEqual(api.WaitForSingleObject(handle, 3000), 0)
                finally:
                    api.CloseHandle(handle)

    def test_windows_foreground_and_background_never_allocate_a_console(self):
        # Windows constants are unavailable on POSIX. Check both modes there as
        # well; the native test below checks the actual console on Windows.
        with mock.patch.object(processes, "WINDOWS", True), \
                mock.patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                mock.patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True):
            for background in (False, True):
                with self.subTest(background=background):
                    flags = processes.launch_options(background=background)["creationflags"]
                    self.assertTrue(flags & 0x08000000)
                    self.assertFalse(flags & 0x00000008)  # DETACHED_PROCESS overrides NO_WINDOW.
                    self.assertFalse(flags & 0x00000010)  # CREATE_NEW_CONSOLE.
                    self.assertEqual(bool(flags & 0x00000200), background)

    def test_posix_only_background_services_start_a_new_session(self):
        with mock.patch.object(processes, "WINDOWS", False):
            self.assertEqual(processes.launch_options(), {})
            self.assertEqual(processes.launch_options(background=True), {"start_new_session": True})

    def test_native_python_launches_return_output_and_exit_without_new_consoles(self):
        code = """
import json, os
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    result = {'console': ctypes.windll.kernel32.GetConsoleWindow()}
else:
    result = {'pid': os.getpid(), 'sid': os.getsid(0)}
print(json.dumps(result))
"""
        for background in (False, True):
            with self.subTest(background=background):
                result = subprocess.run([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True, timeout=5,
                                        **processes.launch_options(background=background))
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                if os.name == "nt":
                    self.assertIsNone(value["console"])
                elif background:
                    self.assertEqual(value["sid"], value["pid"])
                else:
                    self.assertEqual(value["sid"], os.getsid(0))


if __name__ == "__main__":
    unittest.main()
