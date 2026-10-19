"""Stdlib runner contracts, including real descendant teardown (no provider calls)."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import offline_acceptance as runner


class OfflineAcceptanceTests(unittest.TestCase):
    def test_environment_is_allowlisted_and_private(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "SECRET_TOKEN": "CANARY", "HTTPS_PROXY": "CANARY", "PYTHONPATH": "CANARY",
                "VR_DATA_DIR": "CANARY", "HOME": "CANARY"}):
            env = runner.isolated_env(Path(directory))
            self.assertNotIn("CANARY", json.dumps(env))
            for name in ("SECRET_TOKEN", "HTTPS_PROXY", "PYTHONPATH"):
                self.assertNotIn(name, env)
            for name in ("HOME", "TMPDIR", "VR_DATA_DIR", "VR_REPORTS_DIR"):
                self.assertTrue(Path(env[name]).is_relative_to(directory))
                self.assertEqual(Path(env[name]).stat().st_mode & 0o777, 0o700)

    def test_unknown_identity_is_not_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            result = runner.acceptance(Path(directory))
        self.assertEqual(result["release_acceptance"], "blocked")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(all(gate["status"] == "blocked" for gate in result["gates"].values()))

    def test_dirty_identity_fails_closed(self):
        with patch.object(runner, "identity", return_value={"status": "fail", "dirty": True}), \
                patch.object(runner, "run_owned") as execute:
            result = runner.acceptance()
        self.assertEqual(result["release_acceptance"], "blocked")
        execute.assert_not_called()
        self.assertEqual(result["status"], "fail")

    def test_identity_change_invalidates_results(self):
        before = {"status": "pass", "commit": "a" * 40, "tree": "b" * 40, "dirty": False}
        after = {**before, "commit": "c" * 40}
        with patch.object(runner, "identity", side_effect=[before, after]), \
                patch.object(runner, "run_owned", return_value={"status": "pass"}):
            result = runner.acceptance()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["identity_consistency"], "CHANGED_DURING_RUN")
        self.assertEqual(result["release_acceptance"], "blocked")

    def test_child_output_never_exported_and_large_output_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            result = runner.run_owned([sys.executable, "-c",
                "import os; [os.write(1,b'CANARY_PRIVATE'*8192) for _ in range(256)]"],
                cwd=directory, env=runner.isolated_env(Path(directory)), timeout=10)
        self.assertEqual(result["status"], "pass")
        self.assertNotIn("CANARY", json.dumps(result))
        self.assertLess(len(json.dumps(result)), 250)

    def test_namespace_unavailable_blocks_without_fallback(self):
        clean = {"status": "pass", "commit": "a" * 40, "tree": "b" * 40, "dirty": False}
        with patch.object(runner, "identity", return_value=clean), \
                patch.object(runner, "run_owned", return_value={"status": "fail"}) as execute:
            result = runner.acceptance()
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result["release_acceptance"], "blocked")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["isolation"], "UNAVAILABLE")

    def test_nonfinite_deadline_rejected(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                runner.run_owned([], cwd=".", env={}, timeout=value)

    @unittest.skipUnless(sys.platform == "linux", "Linux namespace contract")
    def test_namespace_external_network_denied_and_loopback_works(self):
        with tempfile.TemporaryDirectory() as directory:
            env = runner.isolated_env(Path(directory))
            probe = runner.run_owned(runner.namespace_command([sys.executable, "-c", "pass"], True),
                                     cwd=directory, env=env, timeout=5)
            if probe["status"] != "pass":
                self.skipTest("Linux user/network/PID namespaces unavailable")
            code = '''import socket
s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen()
c=socket.create_connection(s.getsockname(),timeout=1)
a,_=s.accept(); c.close(); a.close(); s.close()
x=socket.socket(); x.settimeout(.2)
try: x.connect(('192.0.2.1',443))
except OSError: pass
else: raise AssertionError('external network unexpectedly available')
'''
            result = runner.run_owned(runner.namespace_command([sys.executable, "-c", code], True),
                                      cwd=directory, env=env, timeout=5)
        self.assertEqual(result["status"], "pass")

    @unittest.skipUnless(sys.platform == "linux", "Linux namespace contract")
    def test_deadline_reaps_listening_grandchild_with_inherited_pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            env = runner.isolated_env(Path(directory))
            probe = runner.run_owned(runner.namespace_command([sys.executable, "-c", "pass"], True),
                                     cwd=directory, env=env, timeout=5)
            if probe["status"] != "pass":
                self.skipTest("Linux user/network/PID namespaces unavailable")
            marker = Path(directory) / "child.json"
            grandchild = '''import json,os,pathlib,signal,socket,time,sys
os.setsid()
signal.signal(signal.SIGTERM,signal.SIG_IGN)
s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen()
host_pid=int(next(line for line in pathlib.Path('/proc/self/status').read_text().splitlines() if line.startswith('NSpid:')).split()[1])
pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':host_pid,'port':s.getsockname()[1]}))
while True: time.sleep(1)
'''
            middle = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(100)"
            leader = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]); time.sleep(100)"
            start = time.monotonic()
            result = runner.run_owned(runner.namespace_command([
                sys.executable, "-c", leader, middle, grandchild, str(marker)], True),
                cwd=directory, env=env, timeout=1)
            self.assertLess(time.monotonic() - start, 4)
            self.assertEqual(result["reason"], "DEADLINE_EXCEEDED")
            child = json.loads(marker.read_text())
            self.assertGreater(child["port"], 0)  # Written only after actual listen().
            deadline = time.monotonic() + 2
            while Path(f'/proc/{child["pid"]}').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertFalse(Path(f'/proc/{child["pid"]}').exists(), "owned descendant was not reaped")

    def test_pipe_inheritance_does_not_extend_deadline(self):
        # Direct group regression: parent exits, child holds stdout open.
        with tempfile.TemporaryDirectory() as directory:
            code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(100)'])"
            start = time.monotonic()
            result = runner.run_owned([sys.executable, "-c", code], cwd=directory,
                                      env=runner.isolated_env(Path(directory)), timeout=.3)
        self.assertEqual(result["reason"], "DEADLINE_EXCEEDED")
        self.assertLess(time.monotonic() - start, 3)


if __name__ == "__main__":
    unittest.main()
