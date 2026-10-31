import hashlib
import json
import re
from pathlib import Path
import signal
import subprocess
import tempfile
import tarfile
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

    def test_built_archive_preserves_adopted_license_and_notice_bytes(self):
        notices = ("docs/third-party/vibe-astock-LICENSE", "docs/third-party/vibe-astock-NOTICE")
        originals = {name: (linux.ROOT / name).read_bytes() for name in notices}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            names = ["backend/app.py", "frontend/package.json", "frontend/package-lock.json",
                     "frontend/vite.config.ts", "frontend/buildIdentity.mjs", "frontend/src/data/sectors.json",
                     "agent-runtime/package.json", "agent-runtime/package-lock.json", "LICENSE",
                     "tools/linux/vibe_linux.py", "docs/LINUX_INSTALL.md", *notices]
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(originals.get(name, b"synthetic package input\n"))
            (root / "frontend/package.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
            (root / "frontend/node_modules").mkdir()
            def git_output(args, **kwargs):
                return "a" * 12 if "rev-parse" in args else "\0".join(names).encode()
            def frontend_build(args, *, cwd, **kwargs):
                self.assertEqual(args, ["npm", "run", "build"])
                (cwd / "dist").mkdir()
                (cwd / "dist/index.html").write_text("synthetic build", encoding="utf-8")
            output = Path(temp) / "artifacts"
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), \
                    patch.object(linux.subprocess, "check_output", side_effect=git_output), \
                    patch.object(linux, "checked", side_effect=frontend_build):
                linux.build(output)
            archive, = output.glob("*.tar.gz")
            with tarfile.open(archive, "r:gz") as package:
                prefix = package.getnames()[0].split("/", 1)[0]
                manifest = json.load(package.extractfile(prefix + "/manifest.json"))
                for name, expected in originals.items():
                    self.assertEqual(package.extractfile(prefix + "/" + name).read(), expected)
                    self.assertEqual(manifest["files"][name], hashlib.sha256(expected).hexdigest())

    def test_real_packaged_frontend_config_includes_local_imports(self):
        # Use the actual tracked source/config and real archive/manifest selection.
        # Only compilation is synthetic: no npm install, provider or server runs.
        def frontend_build(args, *, cwd, **kwargs):
            self.assertEqual(args, ["npm", "run", "build"])
            (cwd / "dist").mkdir()
            (cwd / "dist/index.html").write_text("synthetic build", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "artifacts"
            with patch.object(linux, "prerequisites"), \
                    patch.object(linux, "checked", side_effect=frontend_build):
                linux.build(output)
            archive, = output.glob("*.tar.gz")
            with tarfile.open(archive, "r:gz") as package:
                prefix = package.getnames()[0].split("/", 1)[0]
                manifest = json.load(package.extractfile(prefix + "/manifest.json"))
                pending = ["frontend/vite.config.ts"]
                inspected = set()
                while pending:
                    name = pending.pop()
                    if name in inspected:
                        continue
                    inspected.add(name)
                    self.assertIn(name, manifest["files"], f"missing config dependency: {name}")
                    content = package.extractfile(prefix + "/" + name).read()
                    self.assertEqual(content, (linux.ROOT / name).read_bytes())
                    self.assertEqual(manifest["files"][name], hashlib.sha256(content).hexdigest())
                    for relative in re.findall(r"from\s+[\"'](\.[^\"']+)[\"']", content.decode()):
                        pending.append(str(Path(name).parent / relative))
                self.assertIn("frontend/buildIdentity.mjs", inspected)

    def test_integrity_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = self.package(root)
            self.assertEqual(linux.verify(root), expected)
            (root / "backend/app.py").write_text("changed")
            with self.assertRaises(RuntimeError):
                linux.verify(root)

    def test_integrity_rejects_unmanifested_package_source_and_assets(self):
        for name in ("backend/stale.py", "backend/stale/__init__.py",
                     "backend/stale.pyc", "backend/__pycache__/stale.py",
                     "backend/__pycache__/stale.cpython-311.pyc", "backend/stale.abi3.so",
                     "backend/stale.pyd", "agent-runtime/src/stale.mjs",
                     "agent-runtime/src/stale.node", "agent-runtime/src/stale.json", "agent-runtime/src/stale.ts",
                     "frontend/dist/stale.js"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.package(root)
                extra = root / name
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text("synthetic stale input")
                with self.assertRaisesRegex(RuntimeError, "Unmanifested package file"):
                    linux.verify(root)

    def test_integrity_allows_generated_cache_and_separate_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = self.package(root)
            for name in ("backend/__pycache__/app.cpython-311.pyc",
                         "agent-runtime/node_modules/fixture/index.js", ".installed",
                         "backend/logs/operation.log", "backend/data/local.sqlite3",
                         ".venv/lib/fixture.py"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"synthetic generated input")
            self.assertEqual(linux.verify(root), expected)

    def test_integrity_rejects_unmanifested_source_directory_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "package"
            root.mkdir()
            self.package(root)
            external = Path(temp) / "outside"
            external.mkdir()
            (root / "backend/extra").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "Refusing symlink"):
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
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), patch.object(linux.os, "geteuid", return_value=root.stat().st_uid), patch.object(linux, "checked") as commands:
                linux.install(prefix)
                target = prefix / "releases/test-1"
                self.assertTrue((target / ".installed").exists())
                self.assertFalse((target / "private.env").exists())
                self.assertEqual(commands.call_count, 4)
                with self.assertRaises(FileExistsError):
                    linux.install(prefix)

    def test_install_rejects_prefix_owned_by_another_user(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "package"
            root.mkdir()
            self.package(root)
            prefix = Path(temp) / "install"
            prefix.mkdir()
            other_uid = prefix.stat().st_uid + 1
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), \
                    patch.object(linux.os, "geteuid", return_value=other_uid), \
                    patch.object(linux, "checked") as commands:
                with self.assertRaisesRegex(RuntimeError, "Install prefix must belong to the current user"):
                    linux.install(prefix)
                commands.assert_not_called()
                self.assertFalse((prefix / "releases").exists())

    def test_failed_install_is_not_runnable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "package"
            root.mkdir()
            self.package(root)
            prefix = Path(temp) / "install"
            with patch.object(linux, "ROOT", root), patch.object(linux, "prerequisites"), patch.object(linux.os, "geteuid", return_value=root.stat().st_uid), patch.object(linux, "checked", side_effect=subprocess.CalledProcessError(1, "mock")):
                with self.assertRaises(subprocess.CalledProcessError):
                    linux.install(prefix)
                self.assertFalse((prefix / "releases/test-1/.installed").exists())

    def test_runtime_override_is_explicit_and_consistent(self):
        self.assertEqual(linux.runtime_endpoint({}), ("http://127.0.0.1:8911", 8911))
        for env in ({"VR_AGENT_RUNTIME_URL": "http://127.0.0.1:18302"},
                    {"VR_AGENT_RUNTIME_PORT": "18302"},
                    {"VR_AGENT_RUNTIME_URL": "http://localhost:18302", "VR_AGENT_RUNTIME_PORT": "18302"}):
            self.assertEqual(linux.runtime_endpoint(env), ("http://127.0.0.1:18302", 18302))
        for env in ({"VR_AGENT_RUNTIME_URL": "http://127.0.0.1:18302", "VR_AGENT_RUNTIME_PORT": "8911"},
                    {"VR_AGENT_RUNTIME_PORT": "65536"}, {"VR_AGENT_RUNTIME_PORT": "5899"},
                    {"VR_AGENT_RUNTIME_PORT": "abc"}, {"VR_AGENT_RUNTIME_PORT": "1"}):
            with self.assertRaises(ValueError): linux.runtime_endpoint(env)
        for url in ("https://127.0.0.1:8911", "http://external.test:8911", "http://u:p@127.0.0.1:8911", "http://127.0.0.1:8911?x=1", "http://127.0.0.1:8911/path"):
            with self.assertRaises(ValueError): linux.runtime_endpoint({"VR_AGENT_RUNTIME_URL": url})

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
