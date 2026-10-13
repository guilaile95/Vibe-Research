"""Explicit, bounded, local-only OCR. No executable/path/URL comes from callers."""
from __future__ import annotations

import csv
import hashlib
import io
import os
from pathlib import Path
import re
import signal
import sys
import stat
import struct
import subprocess
import tempfile
import threading
import time

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 12
MAX_DIMENSION = 6000
MAX_PIXELS = 16_000_000
MAX_OUTPUT = 1024 * 1024
MAX_TEXT = 100_000
TIMEOUT = 90
LIMITATIONS = ["OCR_UNVERIFIED: 机器识别可能错字、错行或遗漏，不是来源事实核验", "原文件保持不变；仅本机处理，无模型或网络调用", "最多12页、8MiB；中文需要本机 chi_sim 语言包"]
_SLOT = threading.BoundedSemaphore(1)


class OcrError(ValueError):
    pass


def _resource_supported() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        import resource
        return all(hasattr(resource, key) for key in ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NOFILE"))
    except ImportError:
        return False


def _binary(name: str) -> str | None:
    # Never resolve PATH, relative names, environment configuration or user input.
    candidates = {
        "tesseract": ["/usr/bin/tesseract", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"],
        "pdftoppm": ["/usr/bin/pdftoppm", "/opt/homebrew/bin/pdftoppm", "/usr/local/bin/pdftoppm"],
        "pdfinfo": ["/usr/bin/pdfinfo", "/opt/homebrew/bin/pdfinfo", "/usr/local/bin/pdfinfo"],
    }
    if os.name == "nt":
        return None  # No bundled, verified Windows dependency adapter yet.
    return next((p for p in candidates[name] if Path(p).is_file() and os.access(p, os.X_OK)), None)


def _tessdata_directory() -> Path | None:
    for root in ("/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tessdata", "/usr/local/share/tessdata"):
        path = Path(root)
        if (path / "eng.traineddata").is_file() and os.access(path / "eng.traineddata", os.R_OK):
            return path
    return None


def _language_config(language: str) -> Path:
    if not _resource_supported() or _binary("tesseract") is None:
        raise OcrError("OCR_DEPENDENCY_UNAVAILABLE")
    root = _tessdata_directory()
    if root is None:
        raise OcrError("ENGLISH_LANGUAGE_UNAVAILABLE")
    if language == "chi_sim+eng" and not ((root / "chi_sim.traineddata").is_file() and os.access(root / "chi_sim.traineddata", os.R_OK)):
        raise OcrError("CHINESE_LANGUAGE_UNAVAILABLE")
    return root


def capability() -> dict:
    tessdata = _tessdata_directory()
    chinese = tessdata is not None and (tessdata / "chi_sim.traineddata").is_file() and os.access(tessdata / "chi_sim.traineddata", os.R_OK)
    image = _resource_supported() and _binary("tesseract") is not None and tessdata is not None
    pdf = image and all(_binary(n) for n in ("pdftoppm", "pdfinfo"))
    return {"status": "AVAILABLE" if image else "DEPENDENCY_UNAVAILABLE", "image": image,
            "pdf": bool(pdf), "engine": "local-tesseract", "languages": ["eng", "chi_sim+eng"],
            "language_availability": "FILES_CHECKED_EXECUTION_VALIDATED_ON_ACTION",
            "chinese_language_status": "INSTALLED_QUALITY_NOT_VERIFIED" if chinese else "CHINESE_LANGUAGE_UNAVAILABLE",
            "english_language_status": "INSTALLED_QUALITY_NOT_VERIFIED" if tessdata else "ENGLISH_LANGUAGE_UNAVAILABLE",
            "automatic_language_fallback": False, "max_bytes": MAX_BYTES,
            "max_pages": MAX_PAGES, "timeout_seconds": TIMEOUT, "limitations": LIMITATIONS,
            "resource_limits": {"memory_mib": 768, "file_mib": 16, "cpu_seconds": 90, "open_files": 64},
            "platform_status": "WINDOWS_DEPENDENCIES_NOT_BUNDLED" if os.name == "nt" else ("LINUX_RESOURCE_GUARD" if _resource_supported() else "RESOURCE_GUARD_UNAVAILABLE")}


def _check(cancel: threading.Event, deadline: float) -> None:
    if cancel.is_set():
        raise OcrError("OCR_CANCELLED")
    if time.monotonic() >= deadline:
        raise OcrError("OCR_TIMEOUT")


def _run(name: str, args: list[str], root: Path, cancel: threading.Event, deadline: float) -> bytes:
    binary = _binary(name)
    if binary is None or not _resource_supported():
        raise OcrError("OCR_DEPENDENCY_UNAVAILABLE")
    _check(cancel, deadline)
    # File-backed output avoids unbounded PIPE buffers, and polling enforces a
    # shared wall-time/output budget across every child in this extraction.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        process = subprocess.Popen([sys.executable, "-I", "-S", str(Path(__file__).with_name("local_ocr_exec.py")), binary, *args], stdin=subprocess.DEVNULL, stdout=output, stderr=error,
                                   cwd=root, env={"PATH": "/usr/bin:/bin", "LANG": "C", "OMP_THREAD_LIMIT": "1"},
                                   shell=False, close_fds=True, start_new_session=True)
        try:
            while process.poll() is None:
                _check(cancel, deadline)
                if os.fstat(output.fileno()).st_size + os.fstat(error.fileno()).st_size > MAX_OUTPUT:
                    raise OcrError("OCR_OUTPUT_LIMIT")
                time.sleep(.025)
            _check(cancel, deadline)
            if process.returncode:
                raise OcrError("OCR_RESOURCE_GUARD_UNAVAILABLE" if process.returncode == 78 else "OCR_INPUT_OR_LANGUAGE_INVALID")
            if os.fstat(output.fileno()).st_size + os.fstat(error.fileno()).st_size > MAX_OUTPUT:
                raise OcrError("OCR_OUTPUT_LIMIT")
            output.seek(0)
            return output.read(MAX_OUTPUT + 1)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)


def _image_size(data: bytes, extension: str) -> tuple[int, int]:
    if extension == ".png":
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise OcrError("OCR_INVALID_IMAGE")
        width, height = struct.unpack(">II", data[16:24])
    elif extension in {".jpg", ".jpeg"}:
        if not data.startswith(b"\xff\xd8"):
            raise OcrError("OCR_INVALID_IMAGE")
        offset = 2
        width = height = 0
        while offset + 4 <= len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]; offset += 1
            if marker in {0xD9, 0xDA}:
                break
            if marker in {0x01, *range(0xD0, 0xD9)}:
                continue
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2} and length >= 8:
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7]); break
            offset += length
    else:
        raise OcrError("OCR_UNSUPPORTED_TYPE")
    if not width or not height:
        raise OcrError("OCR_INVALID_IMAGE")
    if max(width, height) > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise OcrError("OCR_IMAGE_DIMENSION_LIMIT")
    return width, height


def _parse_tsv(raw: bytes) -> tuple[str, float | None]:
    try:
        rows = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="strict")), delimiter="\t", quoting=csv.QUOTE_NONE)
        if rows.fieldnames != ["level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"]:
            raise ValueError()
        lines: dict[tuple, list[str]] = {}
        confidences = []
        for row in rows:
            if None in row or any(v is None for v in row.values()):
                raise ValueError()
            if row["level"] != "5" or not row["text"].strip():
                continue
            confidence = float(row["conf"])
            if not 0 <= confidence <= 100:
                raise ValueError()
            lines.setdefault(tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num")), []).append(row["text"].strip())
            confidences.append(confidence)
        text = "\n".join(" ".join(words) for words in lines.values())
        if len(text) > MAX_TEXT:
            raise OcrError("OCR_TEXT_LIMIT")
        return text, round(sum(confidences) / len(confidences), 2) if confidences else None
    except (UnicodeError, ValueError, KeyError, csv.Error) as exc:
        if isinstance(exc, OcrError):
            raise
        raise OcrError("OCR_MALFORMED_OUTPUT") from exc


def extract(data: bytes, extension: str, language: str = "eng", cancel: threading.Event | None = None) -> dict:
    cancel = cancel or threading.Event()
    if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
        raise OcrError("OCR_INPUT_SIZE_LIMIT")
    if extension not in {".pdf", ".png", ".jpg", ".jpeg"} or language not in {"eng", "chi_sim+eng"}:
        raise OcrError("OCR_UNSUPPORTED_TYPE_OR_LANGUAGE")
    if not _SLOT.acquire(blocking=False):
        raise OcrError("OCR_BUSY")
    try:
        deadline = time.monotonic() + TIMEOUT
        _check(cancel, deadline)
        source_sha = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory(prefix="vr-local-ocr-") as tmp:
            root = Path(tmp)
            source = root / ("source" + extension)
            source.write_bytes(data)
            if extension == ".pdf":
                if not data.startswith(b"%PDF-"):
                    raise OcrError("OCR_INVALID_PDF")
                info = _run("pdfinfo", [str(source)], root, cancel, deadline).decode("utf-8", errors="replace")
                match = re.search(r"^Pages:\s+(\d+)\s*$", info, re.M)
                if not match or re.search(r"^Encrypted:\s+yes", info, re.M):
                    raise OcrError("OCR_INVALID_OR_ENCRYPTED_PDF")
                count = int(match[1])
                if not 1 <= count <= MAX_PAGES:
                    raise OcrError("OCR_PAGE_LIMIT")
            else:
                _image_size(data, extension)
                count = 1
            tessdata = _language_config(language)
            pages = []
            total_pixels = 0
            for number in range(1, count + 1):
                _check(cancel, deadline)
                image = source
                if extension == ".pdf":
                    prefix = root / "render"
                    _run("pdftoppm", ["-f", str(number), "-l", str(number), "-singlefile", "-scale-to", "2000", "-png", str(source), str(prefix)], root, cancel, deadline)
                    image = root / "render.png"
                    if not image.is_file() or image.stat().st_size > MAX_BYTES:
                        raise OcrError("OCR_RENDER_LIMIT")
                    width, height = _image_size(image.read_bytes(), ".png")
                    total_pixels += width * height
                    if total_pixels > 32_000_000:
                        raise OcrError("OCR_AGGREGATE_PIXEL_LIMIT")
                raw = _run("tesseract", [str(image), "stdout", "--tessdata-dir", str(tessdata), "-l", language, "--psm", "6", "tsv"], root, cancel, deadline)
                text, confidence = _parse_tsv(raw)
                pages.append({"page_number": number, "text": text, "source_sha256": source_sha,
                              "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                              "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "mean_word_confidence": confidence})
                if sum(len(p["text"]) for p in pages) > MAX_TEXT:
                    raise OcrError("OCR_TEXT_LIMIT")
            _check(cancel, deadline)
            return {"schema_version": "local_ocr_preview.v1", "status": "OCR_UNVERIFIED" if any(p["text"] for p in pages) else "OCR_NO_TEXT", "pages": pages,
                    "source_sha256": source_sha, "engine": "local-tesseract", "language": language,
                    "limitations": LIMITATIONS, "source_truth_verified": False}
    except (OSError, subprocess.SubprocessError) as exc:
        raise OcrError("OCR_LOCAL_PROCESS_FAILED") from exc
    finally:
        _SLOT.release()


class OcrSource:
    """Bounded nofollow source identity held across extraction and index commit."""
    def __init__(self, path: Path):
        from fact_lake_store import _snapshot_identity
        self.path = path
        self._identity = _snapshot_identity
        self.before = self._stat()
        self.data = self._read()
        self.sha256 = hashlib.sha256(self.data).hexdigest()

    def _stat(self):
        from fact_lake_store import _is_link_or_reparse
        if any(_is_link_or_reparse(part) for part in (self.path, *self.path.parents)):
            raise OcrError("OCR_INVALID_SOURCE")
        value = self.path.lstat()
        if not stat.S_ISREG(value.st_mode) or not 0 < value.st_size <= MAX_BYTES:
            raise OcrError("OCR_INPUT_SIZE_LIMIT")
        return self._identity(value)

    def _read(self):
        from fact_lake_store import _snapshot_descriptor_matches
        if self._stat() != self.before:
            raise OcrError("OCR_SOURCE_CHANGED")
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            opened = os.fstat(source.fileno())
            descriptor = self._identity(opened)
            if not stat.S_ISREG(opened.st_mode) or not _snapshot_descriptor_matches(self.before, descriptor):
                raise OcrError("OCR_SOURCE_CHANGED")
            data = source.read(MAX_BYTES + 1)
            if self._identity(os.fstat(source.fileno())) != descriptor:
                raise OcrError("OCR_SOURCE_CHANGED")
        if len(data) != self.before[2] or self._stat() != self.before:
            raise OcrError("OCR_SOURCE_CHANGED")
        return data

    def assert_unchanged(self):
        try:
            if self._read() != self.data:
                raise OcrError("OCR_SOURCE_CHANGED")
        except OSError as exc:
            raise OcrError("OCR_SOURCE_CHANGED") from exc
