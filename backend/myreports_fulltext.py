"""Rebuildable full-text index for files owned by ``VR_REPORTS_DIR``.

The report file remains the sole source of truth.  This module stores only a
local extraction/search index beside it, never moves or rewrites the source.
Read helpers open the index read-only and never create it.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


INDEX_NAME = ".fulltext-index.sqlite3"
SCHEMA_VERSION = 1
SEARCHABLE_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".markdown", ".csv"})
STATUS_SEARCHABLE = "SEARCHABLE"
STATUS_NOT_INDEXED = "NOT_INDEXED"
STATUS_OCR_REQUIRED = "OCR_REQUIRED"
STATUS_ARCHIVED = "ARCHIVED_NOT_SEARCHABLE"
STATUS_ERROR = "INDEX_ERROR"
_LOCK = threading.Lock()
_SPACE_RE = re.compile(r"\s+")
# This is deliberately a small question grammar, not semantic search.  Only
# report-scoped questions may drop this framing; their remaining topic must
# still occur literally in an indexed page.
_REPORT_QUESTION_RE = re.compile(
    r"^(?:(?:请(?:帮我|你)?|帮我)\s*)?"
    r"(?P<action>比较|对比|分析|总结|梳理|解释)?(?:一下)?\s*"
    r"(?:这|那|上述|所选(?:的)?|选中(?:的)?|已选(?:中)?(?:的)?)?"
    r"(?:[一二两三四五六七八九十百\d]+)?(?:份|篇)?(?:报告|研报|资料)"
    r"(?:之间)?\s*(?:中|里)?\s*"
    r"(?P<predicate>怎么看|如何看待|怎么评价|如何评价|关于|对于|对|在|的)\s*"
    r"(?P<topic>.+?)\s*[。！？?!]*$"
)
_REPORT_QUESTION_SUFFIX_RE = re.compile(
    r"(?:"
    r"(?:判断|观点|看法)?(?:方面|上)?的(?:分歧|差异|异同|不同|区别)(?:点|之处)?"
    r"|(?:方面|上)?(?:的(?:判断|观点|看法))?(?:有何|有什么|有哪些)(?:分歧|差异|不同|区别)(?:点|之处)?"
    r"|(?:方面|上)?的(?:判断|观点|看法)(?:如何|是什么)?"
    r"|(?:方面|上)?(?:分别)?(?:怎么看|是否一致)"
    r")$"
)
_REPORT_TOPIC_ASPECT_RE = re.compile(r"(?:的)?(?:变化情况|变化|走势|趋势|表现)(?:如何|怎么样)?$")
_REPORT_TOPIC_SEPARATOR_RE = re.compile(r"\s+|以及|和|与|[、，,]")
_GENERIC_REPORT_TOPICS = frozenset({
    "分歧", "差异", "不同", "异同", "区别", "判断", "观点", "看法", "结论", "内容", "报告", "研报", "资料", "它们",
    "全文", "摘要", "重点", "主要内容", "主要观点", "核心观点", "主要结论", "核心结论",
})


class ReportTextIndexError(RuntimeError):
    pass


class ReportTextIndexCorruptedError(ReportTextIndexError):
    def __init__(self) -> None:
        super().__init__("研报正文索引损坏，已停止检索和写入；原始研报未改动")


def _path(reports_dir: Path) -> Path:
    return Path(reports_dir) / INDEX_NAME


def _assert_schema(conn: sqlite3.Connection) -> None:
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        expected = {
            "report_text_index": [
                "report_id", "file_sha256", "status", "indexed_at", "page_count", "error_code"
            ],
            "report_text_chunks": ["report_id", "page", "text"],
        }
        if version != SCHEMA_VERSION:
            raise ReportTextIndexCorruptedError()
        for table, columns in expected.items():
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            if actual != columns:
                raise ReportTextIndexCorruptedError()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise ReportTextIndexCorruptedError() from exc


def _connect_readonly(reports_dir: Path) -> sqlite3.Connection | None:
    index = _path(reports_dir)
    if not index.exists():
        return None
    if not index.is_file():
        raise ReportTextIndexCorruptedError()
    try:
        conn = sqlite3.connect(f"{index.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        _assert_schema(conn)
        return conn
    except ReportTextIndexCorruptedError:
        raise
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc


def _connect_write(reports_dir: Path) -> sqlite3.Connection:
    index = _path(reports_dir)
    index.parent.mkdir(parents=True, exist_ok=True)
    existed = index.exists()
    try:
        conn = sqlite3.connect(index, timeout=10, isolation_level=None)
        if existed:
            _assert_schema(conn)
        else:
            conn.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE report_text_index (
                    report_id TEXT PRIMARY KEY,
                    file_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    page_count INTEGER,
                    error_code TEXT NOT NULL
                );
                CREATE TABLE report_text_chunks (
                    report_id TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY (report_id, page),
                    FOREIGN KEY (report_id) REFERENCES report_text_index(report_id) ON DELETE CASCADE
                );
                PRAGMA user_version=1;
                COMMIT;
                """
            )
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except ReportTextIndexCorruptedError:
        raise
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc


def _clean_text(value: str) -> str:
    return value.replace("\x00", "").replace("\r\n", "\n").strip()


def _extract_pdf(path: Path) -> tuple[str, list[tuple[int, str]], int | None, str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=True)
        chunks = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = _clean_text(page.extract_text() or "")
            if text:
                chunks.append((page_number, text))
        if not chunks:
            return STATUS_OCR_REQUIRED, [], len(reader.pages), "PDF_NO_EXTRACTABLE_TEXT"
        return STATUS_SEARCHABLE, chunks, len(reader.pages), ""
    except Exception:
        return STATUS_ERROR, [], None, "PDF_EXTRACTION_FAILED"


def _extract_docx(path: Path) -> tuple[str, list[tuple[int, str]], int | None, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(f"{namespace}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
            if text:
                paragraphs.append(text)
        body = _clean_text("\n".join(paragraphs))
        if not body:
            return STATUS_ERROR, [], None, "DOCX_NO_TEXT"
        return STATUS_SEARCHABLE, [(0, body)], None, ""
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return STATUS_ERROR, [], None, "DOCX_EXTRACTION_FAILED"


def extract(path: Path, extension: str) -> tuple[str, list[tuple[int, str]], int | None, str]:
    ext = extension.lower()
    if ext not in SEARCHABLE_EXTENSIONS:
        return STATUS_ARCHIVED, [], None, "UNSUPPORTED_SEARCH_TYPE"
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    try:
        body = _clean_text(path.read_bytes().decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError):
        return STATUS_ERROR, [], None, "INVALID_UTF8"
    if not body:
        return STATUS_ERROR, [], None, "TEXT_NO_CONTENT"
    return STATUS_SEARCHABLE, [(0, body)], None, ""


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_report(reports_dir: Path, report: dict[str, Any], source_path: Path) -> dict[str, Any]:
    report_id = str(report.get("id") or "")
    extension = str(report.get("ext") or "").lower()
    if not report_id or not source_path.is_file():
        raise ReportTextIndexError("研报原文件不存在，无法建立正文索引")
    # Bind extracted text to the actual source, including legacy entries without
    # a metadata fingerprint. An unsuccessful rebuild must not retain old text.
    source_sha = ""
    extraction_error = None
    try:
        source_sha = _source_sha256(source_path)
        status, chunks, page_count, error_code = extract(source_path, extension)
        if _source_sha256(source_path) != source_sha:
            status, chunks, page_count, error_code = STATUS_ERROR, [], None, "FILE_CHANGED_DURING_INDEX"
    except Exception as exc:
        status, chunks, page_count, error_code = STATUS_ERROR, [], None, "EXTRACTION_FAILED"
        extraction_error = exc
    indexed_at = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        conn = _connect_write(reports_dir)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM report_text_chunks WHERE report_id=?", (report_id,))
            conn.execute(
                """INSERT INTO report_text_index
                   (report_id, file_sha256, status, indexed_at, page_count, error_code)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(report_id) DO UPDATE SET
                     file_sha256=excluded.file_sha256, status=excluded.status,
                     indexed_at=excluded.indexed_at, page_count=excluded.page_count,
                     error_code=excluded.error_code""",
                (report_id, source_sha, status, indexed_at, page_count, error_code),
            )
            if status == STATUS_SEARCHABLE:
                conn.executemany(
                    "INSERT INTO report_text_chunks(report_id, page, text) VALUES (?, ?, ?)",
                    [(report_id, page, text) for page, text in chunks],
                )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
    if extraction_error is not None:
        raise ReportTextIndexError("研报正文提取失败，请重新建立索引") from extraction_error
    return {
        "report_id": report_id,
        "status": status,
        "indexed_at": indexed_at,
        "page_count": page_count,
        "error_code": error_code,
        "file_sha256": source_sha,
    }


def remove_report(reports_dir: Path, report_id: str) -> None:
    if not _path(reports_dir).exists():
        return
    with _LOCK:
        conn = _connect_write(reports_dir)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM report_text_chunks WHERE report_id=?", (report_id,))
            conn.execute("DELETE FROM report_text_index WHERE report_id=?", (report_id,))
            conn.execute("COMMIT")
        finally:
            conn.close()


def status_map(
    reports_dir: Path, reports: list[dict[str, Any]], *, verify_source: bool = False,
) -> dict[str, dict[str, Any]]:
    result = {}
    for report in reports:
        ext = str(report.get("ext") or "").lower()
        result[str(report.get("id") or "")] = {
            "text_index_status": STATUS_NOT_INDEXED if ext in SEARCHABLE_EXTENSIONS else STATUS_ARCHIVED,
            "text_index_error": "" if ext in SEARCHABLE_EXTENSIONS else "UNSUPPORTED_SEARCH_TYPE",
            "indexed_at": "",
            "page_count": None,
        }
    conn = _connect_readonly(reports_dir)
    if conn is None:
        return result
    try:
        rows = conn.execute("SELECT * FROM report_text_index").fetchall()
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc
    finally:
        conn.close()
    by_id = {str(report.get("id")): report for report in reports}
    for row in rows:
        report = by_id.get(row["report_id"])
        if not report:
            continue
        error = ""
        indexed_sha = str(row["file_sha256"] or "")
        metadata_sha = str(report.get("file_sha256") or "")
        if row["status"] == STATUS_SEARCHABLE:
            path = Path(reports_dir) / f"{report['id']}{report.get('ext', '')}"
            if not indexed_sha:
                error = "INDEX_FINGERPRINT_MISSING"
            elif metadata_sha and indexed_sha != metadata_sha:
                error = "FILE_CHANGED"
            elif not path.is_file():
                error = "SOURCE_UNAVAILABLE"
            elif verify_source:
                try:
                    if _source_sha256(path) != indexed_sha:
                        error = "FILE_CHANGED"
                except OSError:
                    error = "SOURCE_UNAVAILABLE"
        if error:
            result[row["report_id"]] = {
                "text_index_status": STATUS_NOT_INDEXED,
                "text_index_error": error,
                "indexed_at": "",
                "page_count": None,
            }
            continue
        result[row["report_id"]] = {
            "text_index_status": row["status"],
            "text_index_error": row["error_code"],
            "indexed_at": row["indexed_at"],
            "page_count": row["page_count"],
            "text_index_sha256": indexed_sha,
        }
    return result


def _search_terms(value: str, *, selected_reports: bool) -> list[str]:
    """Reduce supported Chinese report questions without inventing keywords.

    Preserve ordinary whitespace-separated AND search, including unsupported
    questions.  No topic, synonym expansion, or unrelated-report fallback is
    inferred.  Limits keep the question grammar a bounded retrieval aid.
    """
    literal_terms = value.split()
    match = _REPORT_QUESTION_RE.fullmatch(value) if selected_reports else None
    if match is None:
        return literal_terms
    topic, suffix_count = _REPORT_QUESTION_SUFFIX_RE.subn("", match["topic"].strip(), count=1)
    if not match["action"] and not suffix_count and match["predicate"] not in {
        "怎么看", "如何看待", "怎么评价", "如何评价",
    }:
        return literal_terms
    topic = _REPORT_TOPIC_ASPECT_RE.sub("", topic)
    topic = topic.strip().strip('"\'“”‘’')
    terms = list(dict.fromkeys(term for term in _REPORT_TOPIC_SEPARATOR_RE.split(topic) if term))
    if (
        not terms
        or len(topic) > 80
        or len(terms) > 8
        or any(len(term) < 2 or term in _GENERIC_REPORT_TOPICS for term in terms)
        or re.search(r"[。！？?!；;]", topic)
    ):
        return literal_terms
    return terms


def _snippet(text: str, terms: list[str]) -> tuple[str, bool]:
    folded = text.casefold()
    positions = [folded.find(term.casefold()) for term in terms]
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - 90)
    return _SPACE_RE.sub(" ", text[start:start + 320]).strip(), start > 0 or start + 320 < len(text)


def search(
    reports_dir: Path,
    reports: list[dict[str, Any]],
    query: str,
    *,
    report_ids: list[str] | None = None,
    symbol: str | None = None,
    sector: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    value = (query or "").strip()
    if not value or len(value) > 500 or not 1 <= limit <= 50:
        raise ValueError("检索条件无效")
    requested = set(report_ids or [])
    if len(requested) > 100:
        raise ValueError("report_ids 过多")
    candidates = {}
    for report in reports:
        report_id = str(report.get("id") or "")
        if report_ids is not None and report_id not in requested:
            continue
        if symbol and symbol not in {str(report.get("info_code") or ""), str(report.get("external_id") or "")}:
            continue
        if sector and sector not in set(report.get("sector_keys") or []) and sector != report.get("industry"):
            continue
        candidates[report_id] = report
    if not candidates:
        return []
    # Validate only scoped candidates; never read unrelated source documents.
    statuses = status_map(reports_dir, list(candidates.values()), verify_source=True)
    candidates = {rid: report for rid, report in candidates.items()
                  if statuses[rid]["text_index_status"] == STATUS_SEARCHABLE}
    if not candidates:
        return []
    terms = _search_terms(value, selected_reports=bool(requested))
    if not terms:
        raise ValueError("检索条件无效")
    conn = _connect_readonly(reports_dir)
    if conn is None:
        return []
    placeholders = ",".join("?" for _ in candidates)
    text_filters = " AND ".join("instr(lower(c.text), lower(?)) > 0" for _ in terms)
    try:
        rows = conn.execute(
            f"""SELECT c.report_id, c.page, c.text, i.file_sha256
                FROM report_text_chunks c JOIN report_text_index i USING(report_id)
                WHERE i.status=? AND c.report_id IN ({placeholders}) AND {text_filters}""",
            [STATUS_SEARCHABLE, *candidates, *terms],
        ).fetchall()
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc
    finally:
        conn.close()
    hits = []
    for row in rows:
        if row["file_sha256"] != statuses[row["report_id"]]["text_index_sha256"]:
            continue
        folded = row["text"].casefold()
        if not all(term.casefold() in folded for term in terms):
            continue
        score = float(sum(folded.count(term.casefold()) for term in terms))
        report = candidates[row["report_id"]]
        snippet, excerpt_truncated = _snippet(row["text"], terms)
        hits.append({
            "report_id": row["report_id"],
            "title": report.get("title") or report.get("name") or row["report_id"],
            "name": report.get("name") or "",
            "page": row["page"] or None,
            "snippet": snippet,
            "excerpt_truncated": excerpt_truncated,
            "file_sha256": row["file_sha256"],
            "score": score,
            "publish_date": report.get("publish_date") or "",
            "institution": report.get("institution") or "",
            "source_url": report.get("source_url") or "",
        })
    hits.sort(key=lambda hit: (-hit["score"], hit["report_id"], hit["page"] or 0))
    return hits[:limit]
