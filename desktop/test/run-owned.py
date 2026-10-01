"""CI command watchdog: return only after owned descendants are confirmed stopped.

124 means command deadline exceeded; 125 means containment/cleanup is uncertain.
The caller MUST NOT uninstall or delete evidence after 125. No process-name or
system-wide kill operations are used. Linux privileged commands must run this
watchdog itself under sudo so the subreaper can terminate every owned child.
"""
import importlib.util
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

TIMEOUT = 124
UNCERTAIN = 125


def backend_helpers():
    source = Path(__file__).resolve().parents[1] / "build" / "backend_entry.py"
    spec = importlib.util.spec_from_file_location("desktop_owned_backend", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LinuxOwnership:
    def __init__(self, helpers=None):
        self.helpers = helpers or backend_helpers()
        self.helpers.linux_subreaper()

    def cleanup(self):
        # The shared subreaper repeatedly kills and waits for adopted generations.
        # A stuck uninterruptible task makes cleanup uncertain, never successful.
        def expired(_signum, _frame):
            raise TimeoutError("Owned Linux descendants did not finish cleanup")
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, 30)
        try:
            self.helpers.reap_linux_descendants()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


def drain_windows_members(api, *, own_pid=None, clock=time.monotonic, deadline_seconds=30):
    """Kill only verified job members and wait on exact process handles.

    Enumerate again after waiting: descendants spawned during teardown remain in
    the non-breakaway job. Empty/non-self-free job state is checked before return.
    This function is intentionally injectable for offline ownership/race tests.
    """
    own_pid = os.getpid() if own_pid is None else own_pid
    deadline = clock() + deadline_seconds
    while True:
        if clock() >= deadline:
            raise TimeoutError("Owned Windows descendants did not finish cleanup")
        members = api.members()
        if own_pid not in members:
            raise RuntimeError("Watchdog is no longer a confirmed member of its job")
        others = [pid for pid in members if pid != own_pid]
        if not others:
            return
        handles = []
        try:
            for pid in others:
                if clock() >= deadline:
                    raise TimeoutError("Windows job enumeration exceeded cleanup deadline")
                handle = api.open_process(pid)
                if handle is None:  # Exited between enumeration and opening.
                    continue
                handles.append(handle)
                if api.is_member(handle):  # Protect against PID reuse.
                    api.terminate(handle)
                else:
                    # The PID was reused by an unrelated process; never signal it.
                    api.close(handle)
                    handles.pop()
            for handle in handles:
                while not api.wait(handle, 100):
                    if clock() >= deadline:
                        raise TimeoutError("Owned process did not terminate")
        finally:
            for handle in handles:
                api.close(handle)


class WindowsOwnership:
    def __init__(self, helpers=None):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.wintypes = wintypes
        self.kernel, self.job = (helpers or backend_helpers()).windows_job()
        kernel = self.kernel
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD

    def members(self):
        c = self.ctypes
        capacity = 64
        while capacity <= 1_048_576:
            class Pids(c.Structure):
                _fields_ = [("assigned", self.wintypes.DWORD), ("count", self.wintypes.DWORD),
                            ("ids", c.c_size_t * capacity)]
            data = Pids()
            returned = self.wintypes.DWORD()
            ok = self.kernel.QueryInformationJobObject(self.job, 3, c.byref(data), c.sizeof(data), c.byref(returned))
            if not ok:
                error = c.get_last_error()
                if error == 234:  # ERROR_MORE_DATA: job grew while being queried.
                    capacity *= 2
                    continue
                raise c.WinError(error)
            if data.count > capacity or data.assigned > data.count:
                capacity = max(capacity * 2, data.assigned)
                continue
            return [int(data.ids[i]) for i in range(data.count)]
        raise RuntimeError("Windows job member list exceeded bounded capacity")

    def open_process(self, pid):
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE
        handle = self.kernel.OpenProcess(0x00101001, False, pid)
        if not handle:
            error = self.ctypes.get_last_error()
            if error == 87:  # Process already disappeared; next query verifies.
                return None
            raise self.ctypes.WinError(error)
        return handle

    def is_member(self, handle):
        member = self.wintypes.BOOL()
        if not self.kernel.IsProcessInJob(handle, self.job, self.ctypes.byref(member)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return bool(member.value)

    def terminate(self, handle):
        if not self.kernel.TerminateProcess(handle, TIMEOUT):
            error = self.ctypes.get_last_error()
            if not self.wait(handle, 0):
                raise self.ctypes.WinError(error)

    def wait(self, handle, milliseconds):
        result = self.kernel.WaitForSingleObject(handle, milliseconds)
        if result == 0:
            return True
        if result == 258:
            return False
        raise self.ctypes.WinError(self.ctypes.get_last_error())

    def close(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def cleanup(self):
        drain_windows_members(self)
        # Never CloseHandle(job) here: watcher is itself in the kill-on-close
        # job. main uses os._exit only after cleanup, retaining our exact status.


def run_owned(command, seconds, ownership_factory, *, popen=subprocess.Popen,
              ignore_signals=lambda: None, report=lambda message: print(message, file=sys.stderr, flush=True)):
    """Injectable orchestration; no caller can observe success before cleanup."""
    owner = None
    result = UNCERTAIN
    try:
        owner = ownership_factory()  # Containment precedes the first child.
        child = popen(command, close_fds=True)
        try:
            result = child.wait(timeout=seconds)
            if result < 0:
                result = 128 - result
            if result > 255:
                # Windows NTSTATUS exits exceed os._exit's portable integer range.
                result = 1
            # Reserve 125 even when the child independently returns it: caller
            # conservatively treats it as uncertain and retains evidence.
        except subprocess.TimeoutExpired:
            result = TIMEOUT
        except (KeyboardInterrupt, InterruptedError):
            result = 130
    except BaseException as error:
        report(f"Owned command setup/execution failed: {error}")
        result = UNCERTAIN
    finally:
        if owner is not None:
            try:
                ignore_signals()
                owner.cleanup()
            except BaseException as error:
                report(f"Owned command cleanup uncertain: {error}")
                result = UNCERTAIN
    return result


def main(argv):
    if len(argv) < 2:
        print("Usage: run-owned.py SECONDS COMMAND [ARGS...]", file=sys.stderr)
        return UNCERTAIN
    try:
        seconds = float(argv[0])
        if not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError("deadline must be between zero and 3600 seconds")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return UNCERTAIN
    factory = {"linux": LinuxOwnership, "win32": WindowsOwnership}.get(sys.platform)
    if factory is None:
        print("Unsupported watchdog platform", file=sys.stderr)
        return UNCERTAIN
    def interrupt(_signum, _frame):
        raise InterruptedError("Watchdog interrupted")
    def ignore_signals():
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, interrupt)
    return run_owned(argv[1:], seconds, factory, ignore_signals=ignore_signals)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    code = main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    # A Windows job handle intentionally survives until process teardown, after
    # all member handles were waited. Do not TerminateJobObject on our own job.
    os._exit(code)
