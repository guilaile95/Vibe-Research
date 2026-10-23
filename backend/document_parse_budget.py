"""Killable document extraction, with bounded admission, input and output.

Source archives remain untouched on every failure. No partial text is searchable.
"""
from __future__ import annotations
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time

MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 2048
MAX_PAGES = 500
MAX_PAGE_CHARS = 100_000
MAX_TEXT_CHARS = 1_000_000
MAX_RESULT_BYTES = 8 * 1024 * 1024
TIMEOUT = 20.0
_SLOTS = threading.BoundedSemaphore(2)


class DocumentBudgetExceeded(ValueError):
    pass


def check_text(text, total=0):
    if len(text) > MAX_PAGE_CHARS or total + len(text) > MAX_TEXT_CHARS:
        raise DocumentBudgetExceeded()


# Retained for the child's lifetime. Closing a Windows job kills its members.
_WINDOWS_JOB = None


def _limit_windows_memory():
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.BasicLimitInformation.LimitFlags = 0x100 | 0x2000
    limits.ProcessMemoryLimit = 768 * 1024 * 1024
    if (not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        raise OSError("document resource isolation unavailable")
    global _WINDOWS_JOB
    _WINDOWS_JOB = job


def _child(result_path, source, extension):
    # Parser warnings can include document bytes, URLs or paths. Neither channel
    # is a public diagnostic interface; only fixed result codes cross the boundary.
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    try:
        if os.name == "posix":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (20, 21))
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RESULT_BYTES,) * 2)
        elif os.name == "nt":
            _limit_windows_memory()
        else:
            return  # Unsupported isolation must not fall back to in-process parsing.
        import myreports_fulltext
        value = myreports_fulltext._extract_local(Path(source), extension)
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_RESULT_BYTES:
            return
        Path(result_path).write_bytes(raw)
    except BaseException:
        return


def extract(path, extension, *, timeout=TIMEOUT, _target=None):
    failed = ("ARCHIVED_NOT_SEARCHABLE", [], None, "DOCUMENT_RESOURCE_LIMIT")
    if not _SLOTS.acquire(blocking=False):
        return ("ARCHIVED_NOT_SEARCHABLE", [], None, "DOCUMENT_PARSER_BUSY")
    process = None
    started = False
    reaped = True
    try:
        if Path(path).stat().st_size > MAX_INPUT_BYTES:
            return failed
        deadline = time.monotonic() + timeout
        with tempfile.TemporaryDirectory(prefix="vibe-document-") as temporary:
            result = str(Path(temporary) / "result.json")
            process = multiprocessing.get_context("spawn").Process(
                target=_target or _child, args=(result, str(path), extension), daemon=True)
            process.start()
            started = True
            process.join(max(0, deadline - time.monotonic()))
            if process.is_alive():
                process.kill()
                process.join(1)
                return failed
            with open(result, "rb") as handle:
                raw = handle.read(MAX_RESULT_BYTES + 1)
            if len(raw) > MAX_RESULT_BYTES:
                return failed
            value = json.loads(raw)
            return value[0], [tuple(chunk) for chunk in value[1]], value[2], value[3]
    except (OSError, ValueError, IndexError):
        return failed
    finally:
        if process is not None:
            if started and process.is_alive():
                process.kill()
                process.join(1)
            reaped = not started or not process.is_alive()
            if reaped:
                process.close()
        # Never admit a replacement while a failed-to-reap worker remains alive.
        if reaped:
            _SLOTS.release()
