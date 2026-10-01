"""Frozen backend entry, plus Windows lifetime job holder for the service supervisor."""
import json
import multiprocessing
import os
from pathlib import Path
import socket
import signal
import time
import contextlib
import io
import tempfile
import subprocess
import sys


def windows_job():
    """Assign this holder and all future descendants to a kill-on-close job.

    The handle is deliberately non-inheritable. Holder failure therefore closes
    the final handle and terminates every service descendant, even if Node died.
    """
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount",
                    "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimit()
    limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    return kernel, handle


def linux_subreaper():
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def reap_linux_descendants():
    """Only signal kernel-confirmed owned children; never match process names."""
    children_file = Path("/proc/thread-self/children")
    # /proc can be mounted from an outer PID namespace (containers). Translate
    # only kernel-recorded child PIDs to this holder's namespace before signaling.
    def namespace_pids(status):
        for line in status.splitlines():
            if line.startswith("NSpid:"):
                return [int(value) for value in line.split()[1:]]
        return []
    own_pids = namespace_pids(Path("/proc/self/status").read_text())
    namespace_index = len(own_pids) - 1
    def direct_children():
        try:
            return [int(value) for value in children_file.read_text().split()]
        except FileNotFoundError:
            # Some kernels omit the children file. Match only exact parent IDs
            # in status metadata, never names, commands, or unrelated PIDs.
            proc_self = int(os.readlink("/proc/self"))
            result = []
            for candidate in Path("/proc").iterdir():
                if not candidate.name.isdecimal():
                    continue
                try:
                    status = (candidate / "status").read_text()
                    ppid = next(int(line.split()[1]) for line in status.splitlines() if line.startswith("PPid:"))
                    if ppid == proc_self:
                        result.append(int(candidate.name))
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    pass
            return result
    deadline = time.monotonic() + 1.0
    while True:
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                break
        children = direct_children()
        if not children:
            return
        sig = signal.SIGTERM if time.monotonic() < deadline else signal.SIGKILL
        for proc_pid in children:
            try:
                pids = namespace_pids(Path(f"/proc/{proc_pid}/status").read_text())
                pid = pids[namespace_index] if pids and namespace_index >= 0 else proc_pid
                os.kill(pid, sig)
            except (ProcessLookupError, FileNotFoundError):
                pass
        # Killing an adopted parent reparents its children to this subreaper.
        # Continue until all generations have exited and have been reaped.
        time.sleep(0.02)


def supervise(arguments):
    if len(arguments) != 4:
        raise ValueError("--desktop-supervisor requires NODE SCRIPT RESOURCES DATA")
    if sys.platform == "linux":
        linux_subreaper()
        def shutdown(_signum, _frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            return subprocess.call(arguments, close_fds=True)
        finally:
            # Do not allow a second signal to interrupt descendant cleanup.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            reap_linux_descendants()
    if sys.platform != "win32":
        raise RuntimeError("The service holder supports Linux and Windows only")
    kernel, handle = windows_job()
    try:
        # stdin/out/err intentionally inherit the Electron pipes. Node observes
        # stdin EOF when Electron exits and performs its own graceful shutdown.
        return subprocess.call(arguments, close_fds=True)
    finally:
        kernel.CloseHandle(handle)


def self_test():
    """Exercise native/runtime dependencies offline without importing the app."""
    original = os.environ.copy()
    success = False
    try:
        with tempfile.TemporaryDirectory(prefix="vibe-native-self-test-") as home:
            os.environ.update(HOME=home, USERPROFILE=home, XDG_CONFIG_HOME=home,
                              XDG_CACHE_HOME=home, APPDATA=home, LOCALAPPDATA=home)
            # Dependency imports must not pollute the one-line machine contract.
            with contextlib.redirect_stdout(io.StringIO()):
                import numpy as np
                import pandas
                import akshare
                import mootdx
                import duckdb
                import pypdf
                import mcp
                _, values, _ = np.linalg.svd(np.eye(2))
                assert np.allclose(values, [1.0, 1.0])
                with duckdb.connect(":memory:") as connection:
                    assert connection.execute("SELECT 1").fetchone() == (1,)
            success = True
    except Exception as exc:
        print(f"Desktop dependency self-test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        os.environ.clear()
        os.environ.update(original)
    print(json.dumps({"ok": success, "service": "desktop-self-test"}), flush=True)
    return 0 if success else 1


def main():
    if sys.argv[1:2] == ["--desktop-supervisor"]:
        return supervise(sys.argv[2:])
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "backend"))
    if sys.argv[1:] == ["--desktop-self-test"]:
        return self_test()
    port = int(os.environ.get("VR_DESKTOP_BACKEND_PORT", "0"))
    if not 0 <= port <= 65535:
        raise ValueError("VR_DESKTOP_BACKEND_PORT must be between 0 and 65535")
    import uvicorn
    # Binding before announcing eliminates find-free-port / rebind races.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        print(json.dumps({"type": "listening", "service": "backend", "port": listener.getsockname()[1]}), flush=True)
        config = uvicorn.Config("app:app", host="127.0.0.1", port=listener.getsockname()[1],
                                loop="asyncio", http="h11", ws="websockets", access_log=False)
        uvicorn.Server(config).run(sockets=[listener])
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
