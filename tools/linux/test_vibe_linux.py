import hashlib
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import vibe_linux as linux


class LinuxPackageTests(unittest.TestCase):
    def package(self, root):
        (root / "backend").mkdir()
        file = root / "backend/app.py"
        file.write_text("# fixture\n")
        manifest = {"release": "test-1", "files": {"backend/app.py": linux.digest(file)}}
        (root / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def test_integrity_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = self.package(root)
            self.assertEqual(linux.verify(root), expected)
            (root / "backend/app.py").write_text("changed")
            with self.assertRaises(RuntimeError):
                linux.verify(root)

    def test_integrity_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text(json.dumps({"release": "test-1", "files": {"../outside": "bad"}}))
            with self.assertRaises(RuntimeError):
                linux.verify(root)

    def test_release_rejects_escape_and_absolute_paths(self):
        for release in ("../escape", "/absolute", "a/b", "..", ""):
            with self.subTest(release=release), self.assertRaises(RuntimeError):
                linux.validate_release(release)

    def test_source_ancestor_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaises(RuntimeError):
                linux.safe_path(root, "link/file.py")

    def test_sensitive_names_are_excluded(self):
        for name in ("frontend/dist/.env", "backend/private/x.py", "frontend/dist/portfolio.json",
                     "frontend/dist/user-data/a.json", "backend/token.key", "backend/db.sqlite"):
            self.assertFalse(linux.allowed_name(name), name)

    def test_install_is_manifest_only_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "package"
            root.mkdir()
            self.package(root)
            (root / "private.env").write_text("never copy")
            prefix = Path(temp) / "install"
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), patch.object(linux.os, "geteuid", return_value=1000), patch.object(linux, "checked") as commands:
                linux.install(prefix)
                target = prefix / "releases/test-1"
                self.assertTrue((target / ".installed").exists())
                self.assertFalse((target / "private.env").exists())
                self.assertEqual(commands.call_count, 4)
                with self.assertRaises(FileExistsError):
                    linux.install(prefix)

    def test_failed_install_is_not_runnable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "package"
            root.mkdir()
            self.package(root)
            prefix = Path(temp) / "install"
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), patch.object(linux.os, "geteuid", return_value=1000), patch.object(linux, "checked", side_effect=subprocess.CalledProcessError(1, "mock")):
                with self.assertRaises(subprocess.CalledProcessError):
                    linux.install(prefix)
                self.assertFalse((prefix / "releases/test-1/.installed").exists())

    def test_commands_use_existing_fixed_loopback_ports(self):
        commands = linux.commands(Path("/fixture"))
        self.assertEqual(len(commands), 3)
        self.assertIn("8900", commands[0][0])
        self.assertEqual(commands[1][0], ["node", "src/server.mjs"])
        self.assertIn("preview", commands[2][0])
        self.assertIn("--strictPort", commands[2][0])
        self.assertIn("127.0.0.1", commands[2][0])

    def test_cleanup_targets_only_owned_process_groups(self):
        children = [Mock(pid=101), Mock(pid=102)]
        children[1].wait.side_effect = [subprocess.TimeoutExpired("mock", 0), 0]
        with patch.object(linux.os, "killpg") as kill:
            linux.stop_children(children)
        self.assertEqual(kill.call_args_list, [
            unittest.mock.call(101, signal.SIGTERM), unittest.mock.call(102, signal.SIGTERM),
            unittest.mock.call(101, signal.SIGKILL), unittest.mock.call(102, signal.SIGKILL)])

    def test_start_failure_cleans_partial_children_without_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.package(root)
            (root / ".installed").touch()
            child = Mock(pid=101)
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), patch.dict(linux.os.environ, {"VR_DATA_DIR": str(root / "data")}), patch.object(linux.socket, "socket"), patch.object(linux.subprocess, "Popen", side_effect=[child, OSError("mock startup failure")]) as popen, patch.object(linux, "stop_children") as stop:
                with self.assertRaises(OSError):
                    linux.run()
                stop.assert_called_once_with([child])
                self.assertEqual(popen.call_count, 2)
                self.assertTrue(popen.call_args_list[0].kwargs["start_new_session"])
                self.assertEqual(popen.call_args_list[0].kwargs["env"]["VR_AGENT_RUNTIME_PORT"], "8911")

    def test_health_timeout_and_early_exit_cleanup(self):
        for exits in (False, True):
            with self.subTest(exits=exits), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.package(root)
                (root / ".installed").touch()
                children = [Mock(pid=101 + i) for i in range(3)]
                for child in children:
                    child.poll.return_value = 1 if exits else None
                opener = Mock()
                opener.open.side_effect = OSError("mock unavailable")
                with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), patch.dict(linux.os.environ, {"VR_DATA_DIR": str(root / "data")}), patch.object(linux.socket, "socket"), patch.object(linux.subprocess, "Popen", side_effect=children) as popen, patch.object(linux, "stop_children") as stop, patch.object(linux.urllib.request, "build_opener", return_value=opener), patch.object(linux.time, "monotonic", side_effect=[0, 100]):
                    with self.assertRaises(RuntimeError):
                        linux.run()
                    stop.assert_called_once_with(children)
                    self.assertEqual(popen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
