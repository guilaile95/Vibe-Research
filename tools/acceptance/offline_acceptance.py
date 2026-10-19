#!/usr/bin/env python3
"""Selected offline evidence only; run with the project's dependency-equipped Python.

JSON is the only public output. No child logs, environment values or data paths are
exported. Linux user/network/PID namespaces are required, never silently replaced
by a Python-only socket guard. This is not a hostile-code filesystem sandbox.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
GATES = {
    "metadata_diagnostics": ("tests/test_myreports_metadata.py", "tests/test_runtime_diagnostics.py"),
    "runtime_contracts": ("tests/test_runtime_info_api.py",),
    "data_health": ("tests/test_data_health_gate_encoding.py",),
    "synthetic_ai": ("tests/test_ai_answer_quality.py", "tests/test_ai_arithmetic_grammar.py"),
    "linux_package": (),
    "saved_research_journey": ("tests/test_saved_research_restart_journey.py",),
}
BLOCKED = ("real_provider", "real_model", "natural_next_day", "deployment")


def isolated_env(root: Path, node=None) -> dict[str, str]:
    """Do not read/copy ambient credentials, proxies, hooks or provider settings."""
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH": "1",
           "VIBE_NATIVE_INTEL_DISABLE_SCHEDULER": "1"}
    for name, directory in {"HOME": "home", "TMPDIR": "tmp", "XDG_CONFIG_HOME": "config",
                            "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "xdg-data",
                            "VR_DATA_DIR": "data", "VR_REPORTS_DIR": "reports"}.items():
        path = root / directory
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[name] = str(path)
    # Resolve executable directories explicitly, not the caller's arbitrary PATH.
    env["PATH"] = os.pathsep.join(dict.fromkeys([str(Path(sys.executable).parent), os.defpath]))
    if node is not None:
        executable = Path(node)
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("node must be an absolute executable path")
        env["PATH"] = str(executable.parent) + os.pathsep + env["PATH"]
    return env


def run_owned(command, *, cwd, env, timeout):
    """Bound execution AND pipe drains; discard output rather than retain secrets.

    Every process starts in an owned session. Namespace init termination also
    kills descendants that escaped the session. Pipe EOF is not trusted as a
    completion boundary: grandchildren may inherit it after the leader exits.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    start = time.monotonic()
    try:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True)
    except OSError:
        return {"status": "blocked", "reason": "PROCESS_START_UNAVAILABLE"}
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    os.set_blocking(child.stdout.fileno(), False)
    timed_out = False
    try:
        while True:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                timed_out = True
                break
            if child.poll() is not None and not selector.get_map():
                break
            for key, _ in selector.select(min(remaining, 0.05)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
    finally:
        # Always clean the whole group, even after a successful leader exit.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
        selector.close()
        child.stdout.close()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return {"status": "fail", "reason": "PROCESS_REAP_FAILED"}
    return {"status": "fail" if timed_out or child.returncode else "pass",
            "reason": "DEADLINE_EXCEEDED" if timed_out else "EXIT_STATUS",
            "exit_code": child.returncode, "elapsed_seconds": round(time.monotonic() - start, 3)}


def identity(root: Path):
    """No paths or Git diagnostics escape; an unavailable identity never passes."""
    env = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args], env=env,
                                       stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    try:
        commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
        dirty = bool(git("status", "--porcelain", "--untracked-files=all"))
        if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (commit, tree)):
            raise ValueError("invalid identity")
        return {"status": "fail" if dirty else "pass", "commit": commit, "tree": tree,
                "dirty": dirty}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "blocked", "reason": "IDENTITY_UNAVAILABLE"}


def namespace_command(command, loopback=False):
    return ["unshare", "--user", "--map-current-user", "--keep-caps", "--net", "--pid", "--fork",
            "--kill-child", sys.executable, str(Path(__file__).resolve()),
            "_sandbox", "loopback" if loopback else "none", *command]


def sandbox_main(mode, command):
    # Only the newly-created network namespace is modified. No host interfaces,
    # routes, DNS, credentials or services are touched.
    if mode == "loopback":
        import fcntl
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            request = struct.pack("16sH", b"lo", 0)
            current = fcntl.ioctl(sock.fileno(), 0x8913, request)  # SIOCGIFFLAGS
            flags = struct.unpack("16sH", current[:18])[1]
            fcntl.ioctl(sock.fileno(), 0x8914, struct.pack("16sH", b"lo", flags | 1))
    os.execvpe(command[0], command, os.environ)


def diagnostics(root, destination, observed):
    sys.path.insert(0, str(root / "backend"))
    from runtime_diagnostics import build_report
    from version import read_version
    report = build_report({"service": "vibe-research-api", "version": read_version(),
                           "git_sha": observed["commit"], "source_state": "clean"})
    Path(destination).write_text(json.dumps(report), encoding="utf-8")


def acceptance(root=ROOT, timeout=120, node=None):
    before = identity(root)
    report = {"schema": "offline_acceptance.v1", "scope": "SELECTED_OFFLINE_SYNTHETIC_ONLY",
              "release_acceptance": "blocked", "identity": before, "isolation": "LINUX_USER_NETWORK_PID_NAMESPACES",
              "gates": {name: {"status": "blocked", "reason": "NOT_RUN"} for name in GATES}}
    report["gates"].update({name: {"status": "blocked", "reason": "REQUIRES_SEPARATE_REAL_EVIDENCE"}
                            for name in BLOCKED})
    if before["status"] != "pass":
        report["status"] = before["status"]
        return report
    with tempfile.TemporaryDirectory(prefix="vibe-offline-") as directory:
        env = isolated_env(Path(directory) / "diagnostics", node)
        probe = run_owned(namespace_command([sys.executable, "-c", "pass"], True),
                          cwd=root, env=env, timeout=min(timeout, 10))
        if probe["status"] != "pass":
            report["status"] = "blocked"
            report["isolation"] = "UNAVAILABLE"
            return report
        destination = Path(directory) / "diagnostics.json"
        command = [sys.executable, str(Path(__file__).resolve()), "_diagnostics", str(root),
                   str(destination), json.dumps(before)]
        outcome = run_owned(namespace_command(command), cwd=root, env=env, timeout=timeout)
        if outcome["status"] == "pass":
            try:
                report["diagnostics"] = json.loads(destination.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                outcome = {"status": "fail", "reason": "DIAGNOSTICS_UNAVAILABLE"}
        for name, targets in GATES.items():
            if name == "metadata_diagnostics" and outcome["status"] != "pass":
                report["gates"][name] = outcome
                continue
            if name == "linux_package":
                cwd = root
                command = [sys.executable, "tools/linux/test_vibe_linux.py"]
            else:
                cwd = root / "backend"
                if not all((cwd / target).is_file() for target in targets):
                    report["gates"][name] = {"status": "blocked", "reason": "TEST_TARGET_UNAVAILABLE"}
                    continue
                command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]
            env = isolated_env(Path(directory) / name, node)
            report["gates"][name] = run_owned(namespace_command(command, name == "saved_research_journey"),
                                              cwd=cwd, env=env, timeout=timeout)
    after = identity(root)
    report["identity_after"] = after
    statuses = [report["gates"][name]["status"] for name in GATES]
    report["status"] = "fail" if "fail" in statuses else "blocked" if "blocked" in statuses else "pass"
    if before != after:
        report["status"] = "fail"
        report["identity_consistency"] = "CHANGED_DURING_RUN"
    # Overall pass is only selected offline gates; broader acceptance remains blocked.
    return report


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_sandbox":
        sandbox_main(sys.argv[2], sys.argv[3:])
    elif len(sys.argv) > 1 and sys.argv[1] == "_diagnostics":
        diagnostics(Path(sys.argv[2]), sys.argv[3], json.loads(sys.argv[4]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--timeout", type=float, default=120, help="hard deadline per gate, seconds")
        parser.add_argument("--node", type=Path, help="explicit absolute Node executable for saved journey")
        args = parser.parse_args()
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            parser.error("timeout must be positive and finite")
        if args.node is not None and (not args.node.is_absolute() or not args.node.is_file() or not os.access(args.node, os.X_OK)):
            parser.error("node must be an absolute executable path")
        report = acceptance(timeout=args.timeout, node=args.node)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "pass" else 1 if report["status"] == "fail" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
