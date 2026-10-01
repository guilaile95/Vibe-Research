"""Isolated entrypoint tests: no real app imports, network fetches, or UI."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import sys
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("desktop_backend_entry", Path(__file__).with_name("backend_entry.py"))
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class EntryTests(unittest.TestCase):
    def test_port_zero_announces_a_live_bound_socket(self):
        observed = {}
        class Server:
            def __init__(self, config):
                observed["config"] = config
            def run(self, sockets):
                observed["port"] = sockets[0].getsockname()[1]
                with socket.socket() as other:
                    with self_test.assertRaises(OSError):
                        other.bind(("127.0.0.1", observed["port"]))
        self_test = self
        fake_uvicorn = types.SimpleNamespace(Config=lambda *a, **kw: (a, kw), Server=Server)
        output = io.StringIO()
        original_path = sys.path[:]
        try:
            with patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), patch.dict(os.environ, {"VR_DESKTOP_BACKEND_PORT": "0"}), patch.object(sys, "argv", ["vibe-backend"]), contextlib.redirect_stdout(output):
                self.assertEqual(entry.main(), 0)
        finally:
            sys.path[:] = original_path
        announcement = json.loads(output.getvalue())
        self.assertEqual(announcement, {"type": "listening", "service": "backend", "port": observed["port"]})
        self.assertGreater(observed["port"], 0)
        self.assertEqual(observed["config"][1]["host"], "127.0.0.1")

    def test_job_holder_rejects_invalid_arguments(self):
        with self.assertRaises(ValueError):
            entry.supervise([])

    @unittest.skipUnless(sys.platform == "linux", "Linux subreaper integration")
    def test_subreaper_reaps_detached_orphan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "child.py"
            pidfile = root / "detached.pid"
            code = f"import os,pathlib,time; p=pathlib.Path({str(pidfile)!r}); t=p.with_suffix('.tmp'); t.write_text(str(os.getpid())); t.replace(p); time.sleep(60)"
            child.write_text("import subprocess,sys,time,pathlib\n" +
                f"subprocess.Popen([sys.executable, '-c', {code!r}], start_new_session=True)\n" +
                "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)\n")
            frozen = os.environ.get("VR_DESKTOP_TEST_EXECUTABLE")
            holder = [frozen] if frozen else [sys.executable, str(Path(entry.__file__))]
            result = subprocess.run(holder + ["--desktop-supervisor", sys.executable, str(child),
                str(pidfile), "unused"], timeout=10, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(pidfile.exists(), result.stderr)
            pid = int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def windows_job_scenario(self, force_holder_exit):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile, trigger = root / "owned.json", root / "exit"
            grandchild = "import time; time.sleep(60)"
            child_code = (
                "import subprocess,sys,os,pathlib,json,time; "
                f"grandchild=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
                f"p=pathlib.Path({str(pidfile)!r}); t=p.with_suffix('.tmp'); t.write_text(json.dumps([os.getpid(),grandchild.pid])); t.replace(p); "
                "time.sleep(60)"
            )
            fixture = root / "fixture.py"
            fixture.write_text("import subprocess,sys,pathlib,time\n" +
                f"subprocess.Popen([sys.executable,'-c',{child_code!r}])\n" +
                f"while not pathlib.Path({str(trigger)!r}).exists(): time.sleep(.01)\n")
            frozen = os.environ.get("VR_DESKTOP_TEST_EXECUTABLE")
            command = [frozen] if frozen else [sys.executable, str(Path(entry.__file__))]
            holder = subprocess.Popen(command + ["--desktop-supervisor", sys.executable,
                str(fixture), "resources", "data"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            handles = []
            try:
                deadline = time.monotonic() + 10
                while not pidfile.exists() and time.monotonic() < deadline:
                    if holder.poll() is not None:
                        self.fail("Holder exited before child startup: " + holder.stderr.read().decode(errors="replace"))
                    time.sleep(.02)
                self.assertTrue(pidfile.exists(), "Windows job children did not start")
                for pid in json.loads(pidfile.read_text()):
                    # Retain handles to exactly our fixture processes, avoiding PID reuse.
                    handle = kernel.OpenProcess(0x00100000 | 0x1000 | 0x0001, False, pid)
                    self.assertTrue(handle, f"Cannot inspect owned child {pid}: {ctypes.get_last_error()}")
                    handles.append(handle)
                if force_holder_exit:
                    holder.terminate()
                else:
                    trigger.write_text("exit")
                holder.wait(timeout=10)
                for handle in handles:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0,
                        "Owned child/grandchild survived job holder exit")
            finally:
                if holder.poll() is None:
                    holder.kill()
                holder.wait(timeout=10)
                for handle in handles:
                    if kernel.WaitForSingleObject(handle, 0) != 0:
                        kernel.TerminateProcess(handle, 1)
                    kernel.CloseHandle(handle)
                holder.stderr.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object integration")
    def test_windows_job_kills_descendants_after_supervisor_exit(self):
        self.windows_job_scenario(False)

    @unittest.skipUnless(sys.platform == "win32", "Windows Job Object integration")
    def test_windows_job_kills_descendants_after_holder_termination(self):
        self.windows_job_scenario(True)


if __name__ == "__main__":
    unittest.main()
