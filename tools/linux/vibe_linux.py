#!/usr/bin/env python3
"""User-space Linux packaging and foreground lifecycle, using existing services."""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
PORTS = (8900, 8911, 5899)
URL = "http://127.0.0.1:5899"


def checked(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def prerequisites():
    if sys.platform != "linux" or sys.version_info[:2] != (3, 11):
        raise RuntimeError("Linux with Python 3.11 (including venv/pip) is required")
    result = subprocess.check_output(["node", "--version"], text=True).strip()
    if tuple(map(int, result.lstrip("v").split(".")[:2])) < (22, 6):
        raise RuntimeError("Node.js >=22.6 and npm are required")
    checked(["npm", "--version"], stdout=subprocess.DEVNULL)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root, name):
    parts = Path(name).parts
    if not parts or Path(name).is_absolute() or ".." in parts or "\\" in name:
        raise RuntimeError(f"Unsafe package path: {name}")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"Refusing symlink: {name}")
    return current


def allowed_name(name):
    forbidden = {"private", ".git", "node_modules", "__pycache__", ".cache", "user-data",
                 "portfolio.json", "account_profile.json", "ai_credentials.json", "my-watchlist.json"}
    return not any(part.lower() in forbidden or part.lower().startswith(".env")
                   or part.lower().endswith((".pem", ".key", ".secret", ".sqlite", ".db"))
                   for part in Path(name).parts)


def build(output):
    prerequisites()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    backend_static = {"backend/news_sources.json", "backend/top_risk_config.yaml",
                      "backend/data/cn_a_share_trade_calendar_v01.json", "backend/data/signals_gpu_seed.json",
                      "backend/requirements-linux-py311.lock.txt"}
    explicit = {"frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.ts", "frontend/src/data/sectors.json",
                "agent-runtime/package.json", "agent-runtime/package-lock.json", "LICENSE",
                "tools/linux/vibe_linux.py", "docs/LINUX_INSTALL.md"}
    names = [p for p in tracked if p and (
        (p.startswith("backend/") and p.count("/") == 1 and p.endswith(".py") and p != "backend/conftest.py")
        or p in backend_static or p.startswith("agent-runtime/src/") or p in explicit)]
    names += list(explicit)
    sources = {name: safe_path(ROOT, name) for name in sorted(set(names))}
    for name in sources:
        if not allowed_name(name):
            raise RuntimeError(f"Sensitive package name rejected: {name}")
    # Fresh staging includes only tracked frontend inputs: untracked public content
    # and stale dist assets can never enter the build. Dependencies remain local.
    with tempfile.TemporaryDirectory(prefix="vibe-linux-build-") as temporary:
        stage = Path(temporary) / "frontend"
        stage.mkdir()
        for name in tracked:
            if not name.startswith("frontend/") or name.startswith("frontend/dist/"):
                continue
            if not allowed_name(name):
                raise RuntimeError(f"Sensitive frontend input rejected: {name}")
            source = safe_path(ROOT, name)
            target = Path(temporary) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (stage / "node_modules").symlink_to(ROOT / "frontend/node_modules", target_is_directory=True)
        checked(["npm", "run", "build"], cwd=stage,
                env={key: value for key, value in os.environ.items() if not key.startswith("VITE_")})
        for path in (stage / "dist").rglob("*"):
            if path.is_file():
                name = "frontend/" + str(path.relative_to(stage))
                safe_path(stage, str(path.relative_to(stage)))
                if not allowed_name(name):
                    raise RuntimeError(f"Sensitive build output rejected: {name}")
                sources[name] = path
        version = json.loads((ROOT / "frontend/package.json").read_text())["version"]
        revision = subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = {"version": version, "revision": revision,
                    "files": {name: digest(path) for name, path in sorted(sources.items())}}
        fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12]
        release = f"{version}-{revision}-{fingerprint}"
        validate_release(release)
        manifest["release"] = release
        output.mkdir(parents=True, exist_ok=True)
        archive = output / f"vibe-research-{release}-linux.tar.gz"
        with archive.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for name in sorted(sources) + ["manifest.json"]:
                    data = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode() if name == "manifest.json" else sources[name].read_bytes()
                    info = tarfile.TarInfo(f"vibe-research-{release}/{name}")
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    tar.addfile(info, io.BytesIO(data))
        archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest(archive)}  {archive.name}\n")
        print(archive)


def validate_release(release):
    if not isinstance(release, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", release):
        raise RuntimeError("Invalid package release identifier")


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise RuntimeError("Invalid package manifest")
    validate_release(manifest.get("release"))
    for name, expected in manifest["files"].items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise RuntimeError("Invalid package file entry")
        path = safe_path(root, name)
        if not allowed_name(name) or digest(path) != expected:
            raise RuntimeError(f"Package integrity failed: {name}")
    return manifest


def install(prefix):
    prerequisites()
    if os.geteuid() == 0:
        raise RuntimeError("Install as an ordinary user, without sudo")
    manifest = verify(ROOT)
    prefix = prefix.expanduser().absolute()
    safe_path(Path("/"), str(prefix).lstrip("/"))
    destination = safe_path(prefix, "releases/" + manifest["release"])
    if prefix.exists() and prefix.stat().st_uid != os.geteuid():
        raise RuntimeError("Install prefix must belong to the current user")
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    # Copy only manifested files, never credentials, generated data or arbitrary extras.
    for name in list(manifest["files"]) + ["manifest.json"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    checked([sys.executable, "-m", "venv", str(destination / ".venv")])
    checked([str(destination / ".venv/bin/python"), "-m", "pip", "install", "-r",
             str(destination / "backend/requirements-linux-py311.lock.txt")])
    for directory in ("frontend", "agent-runtime"):
        checked(["npm", "ci", "--include=dev", "--no-audit", "--no-fund"], cwd=destination / directory)
    (destination / ".installed").write_text(manifest["release"] + "\n")
    print("Installed. Start with: " + shlex.join([sys.executable, str(destination / "tools/linux/vibe_linux.py"), "run"]))


def stop_children(children):
    # Each child owns a separate session; do not signal unrelated user processes.
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 8
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("A child did not exit after SIGKILL; inspect operating-system process state", file=sys.stderr)


def commands(root):
    return [
        ([str(root / ".venv/bin/python"), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8900"], root / "backend"),
        (["node", "src/server.mjs"], root / "agent-runtime"),
        (["node", "node_modules/vite/bin/vite.js", "preview", "--host", "127.0.0.1", "--port", "5899", "--strictPort"], root / "frontend"),
    ]


def run(open_browser=False):
    import fcntl
    prerequisites()
    verify(ROOT)
    if not (ROOT / ".installed").is_file():
        raise RuntimeError("Run install successfully first")
    data = Path(os.environ.get("VR_DATA_DIR", str(Path.home() / ".vibe-research"))).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data / ".linux-launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for port in PORTS:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        env = dict(os.environ, VR_DATA_DIR=str(data), VR_AGENT_RUNTIME_URL="http://127.0.0.1:8911",
                   VR_AGENT_RUNTIME_PORT="8911", VITE_API_URL="http://127.0.0.1:8900")
        children = []
        old_handlers = {}
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, interrupted)
            for args, cwd in commands(ROOT):
                children.append(subprocess.Popen(args, cwd=cwd, env=env, start_new_session=True))
            deadline = time.monotonic() + 90
            pending = {"http://127.0.0.1:8900/api/health", "http://127.0.0.1:8911/health", URL}
            # Never use a network proxy for loopback health checks.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while pending:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("A service exited during startup; see terminal output")
                for url in tuple(pending):
                    try:
                        with opener.open(url, timeout=1) as response:
                            if response.status == 200:
                                pending.remove(url)
                    except OSError:
                        pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Services did not become ready within 90 seconds")
                time.sleep(0.2)
            print(f"Ready: {URL}\nKeep this terminal open; Ctrl+C stops all three services.", flush=True)
            if open_browser:
                subprocess.Popen(["xdg-open", URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise RuntimeError("A service exited; stopped remaining services")
        except KeyboardInterrupt:
            pass
        finally:
            # Prevent a second Ctrl+C interrupting cleanup.
            for sig in old_handlers:
                signal.signal(sig, signal.SIG_IGN)
            stop_children(children)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--output", type=Path, default=ROOT / "dist")
    install_parser = sub.add_parser("install")
    install_parser.add_argument("--prefix", type=Path, default=Path.home() / ".local/share/vibe-research")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--open-browser", action="store_true", help="Ask your existing default browser to open the app")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "build":
            build(args.output)
        elif args.command == "install":
            install(args.prefix)
        else:
            run(args.open_browser)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        parser.exit(1, f"Vibe Linux: {error}\n")


if __name__ == "__main__":
    main()
