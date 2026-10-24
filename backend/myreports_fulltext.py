"""Rebuildable full-text index for files owned by ``VR_REPORTS_DIR``.

The report file remains the sole source of truth.  This module stores only a
local extraction/search index beside it, never moves or rewrites the source.
Read helpers open the index read-only and never create it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
import document_parse_budget as budget


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
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_text_ocr'").fetchone():
            expected["report_text_ocr"] = ["report_id", "payload"]
        for table, columns in expected.items():
            actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            if actual != columns:
                raise ReportTextIndexCorruptedError()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise ReportTextIndexCorruptedError() from exc


class _ReadSnapshotConnection:
    """Existing connection-shaped callers, but source bytes never reach SQLite."""
    def __init__(self, snapshot, conn):
        self.snapshot, self.conn, self.closed = snapshot, conn, False

    def execute(self, *args, **kwargs):
        return self.conn.execute(*args, **kwargs)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.snapshot.assert_unchanged()
        except Exception as exc:
            raise ReportTextIndexCorruptedError() from exc
        finally:
            self.conn.close()


def _connect_readonly(reports_dir: Path) -> sqlite3.Connection | None:
    # Reuse the accepted foundation's no-source-SQLite private image contract.
    # Active WAL/journals fail closed; never open a source URI or create SHM.
    from fact_lake_store import _ControlSnapshot, _is_link_or_reparse
    index = _path(reports_dir)
    if not index.exists():
        if any(_is_link_or_reparse(part) for part in (index, *index.parents)) or any(
                Path(str(index) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ReportTextIndexCorruptedError()
        return None
    conn = None
    try:
        snapshot = _ControlSnapshot(index)
        conn = snapshot.connect()
        _assert_schema(conn)
        snapshot.assert_unchanged()
        return _ReadSnapshotConnection(snapshot, conn)
    except Exception as exc:
        if conn is not None:
            conn.close()
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
        conn.execute("CREATE TABLE IF NOT EXISTS report_text_ocr (report_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
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
        if len(reader.pages) > budget.MAX_PAGES:
            raise budget.DocumentBudgetExceeded()
        chunks = []
        total = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = _clean_text(page.extract_text() or "")
            budget.check_text(text, total)
            total += len(text)
            if text:
                chunks.append((page_number, text))
        if not chunks:
            return STATUS_OCR_REQUIRED, [], len(reader.pages), "PDF_NO_EXTRACTABLE_TEXT"
        return STATUS_SEARCHABLE, chunks, len(reader.pages), ""
    except budget.DocumentBudgetExceeded:
        return STATUS_ARCHIVED, [], None, "DOCUMENT_RESOURCE_LIMIT"
    except Exception:
        return STATUS_ERROR, [], None, "PDF_EXTRACTION_FAILED"


def _extract_docx(path: Path) -> tuple[str, list[tuple[int, str]], int | None, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if (len(infos) > budget.MAX_ZIP_ENTRIES
                    or sum(info.file_size for info in infos) > budget.MAX_ZIP_BYTES
                    or archive.getinfo("word/document.xml").file_size > budget.MAX_XML_BYTES):
                raise budget.DocumentBudgetExceeded()
            with archive.open("word/document.xml") as source:
                xml = source.read(budget.MAX_XML_BYTES + 1)
            if len(xml) > budget.MAX_XML_BYTES:
                raise budget.DocumentBudgetExceeded()
        root = ElementTree.fromstring(xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        total = 0
        for paragraph in root.iter(f"{namespace}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
            total += len(text) + 1
            if total > budget.MAX_TEXT_CHARS:
                raise budget.DocumentBudgetExceeded()
            if text:
                paragraphs.append(text)
        body = _clean_text("\n".join(paragraphs))
        if not body:
            return STATUS_ERROR, [], None, "DOCX_NO_TEXT"
        return STATUS_SEARCHABLE, [(0, body)], None, ""
    except budget.DocumentBudgetExceeded:
        return STATUS_ARCHIVED, [], None, "DOCUMENT_RESOURCE_LIMIT"
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return STATUS_ERROR, [], None, "DOCX_EXTRACTION_FAILED"


def _extract_local(path: Path, extension: str) -> tuple[str, list[tuple[int, str]], int | None, str]:
    ext = extension.lower()
    if ext not in SEARCHABLE_EXTENSIONS:
        return STATUS_ARCHIVED, [], None, "UNSUPPORTED_SEARCH_TYPE"
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    try:
        with path.open("rb") as source:
            raw = source.read(budget.MAX_INPUT_BYTES + 1)
        if len(raw) > budget.MAX_INPUT_BYTES:
            return STATUS_ARCHIVED, [], None, "DOCUMENT_RESOURCE_LIMIT"
        body = _clean_text(raw.decode("utf-8", errors="strict"))
        if len(body) > budget.MAX_TEXT_CHARS:
            return STATUS_ARCHIVED, [], None, "DOCUMENT_RESOURCE_LIMIT"
    except (OSError, UnicodeDecodeError):
        return STATUS_ERROR, [], None, "INVALID_UTF8"
    if not body:
        return STATUS_ERROR, [], None, "TEXT_NO_CONTENT"
    return STATUS_SEARCHABLE, [(0, body)], None, ""


def extract(path: Path, extension: str):
    if extension.lower() not in SEARCHABLE_EXTENSIONS:
        return STATUS_ARCHIVED, [], None, "UNSUPPORTED_SEARCH_TYPE"
    return budget.extract(path, extension)


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            total += len(chunk)
            if total > budget.MAX_INPUT_BYTES:
                raise budget.DocumentBudgetExceeded()
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
    except budget.DocumentBudgetExceeded:
        status, chunks, page_count, error_code = STATUS_ARCHIVED, [], None, "DOCUMENT_RESOURCE_LIMIT"
    except Exception as exc:
        status, chunks, page_count, error_code = STATUS_ERROR, [], None, "EXTRACTION_FAILED"
        extraction_error = exc
    indexed_at = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        conn = _connect_write(reports_dir)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM report_text_ocr WHERE report_id=?", (report_id,))
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
            conn.execute("DELETE FROM report_text_ocr WHERE report_id=?", (report_id,))
            conn.execute("DELETE FROM report_text_chunks WHERE report_id=?", (report_id,))
            conn.execute("DELETE FROM report_text_index WHERE report_id=?", (report_id,))
            conn.execute("COMMIT")
        finally:
            conn.close()


def status_map(
    reports_dir: Path, reports: list[dict[str, Any]], *, verify_source: bool = False,
) -> dict[str, dict[str, Any]]:
    conn = _connect_readonly(reports_dir)
    try:
        return _status_map_in_snapshot(conn, reports_dir, reports, verify_source=verify_source)
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc
    finally:
        if conn is not None:
            conn.close()


def _status_map_in_snapshot(
    conn, reports_dir: Path, reports: list[dict[str, Any]], *, verify_source: bool = False,
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
    if conn is None:
        return result
    rows = conn.execute("SELECT * FROM report_text_index").fetchall()
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
            "extraction_kind": "LOCAL_OCR_UNVERIFIED" if row["error_code"] == "LOCAL_OCR_UNVERIFIED" else "DOCUMENT_TEXT",
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


def _chunk_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_search_hits(reports_dir: Path, hits: list[dict]) -> list[dict]:
    """Revalidate supplied hit locations against one read-only index snapshot.

    File identity alone cannot distinguish corrected extractions of the same
    bytes. Bind the whole extracted chunk, including text beyond the snippet,
    without relying on a timestamp or introducing a new index schema. Callers
    must scope hits to selected reports and independently check source freshness.
    This checks extraction identity, not the factual truth of extracted text.
    """
    if not hits:
        return []
    conn = _connect_readonly(reports_dir)
    if conn is None:
        return []
    try:
        return _current_search_hits_in_snapshot(conn, hits)
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc
    finally:
        conn.close()


def _current_search_hits_in_snapshot(conn, hits: list[dict]) -> list[dict]:
    if conn is None or not hits:
        return []
    current = []
    checked = {}
    conn.execute("BEGIN")
    for hit in hits:
        page = hit.get("page")
        if page is not None and (type(page) is not int or page <= 0):
            continue
        key = (hit.get("report_id"), 0 if page is None else page)
        if key not in checked:
            row = conn.execute(
                """SELECT c.text, i.file_sha256 FROM report_text_chunks c
                   JOIN report_text_index i USING(report_id)
                   WHERE c.report_id=? AND c.page=? AND i.status=?""",
                (*key, STATUS_SEARCHABLE),
            ).fetchone()
            checked[key] = (
                row["file_sha256"], _chunk_sha256(row["text"]),
                _SPACE_RE.sub(" ", row["text"]).strip(),
            ) if row is not None and isinstance(row["text"], str) else None
        value = checked[key]
        snippet = hit.get("snippet")
        if (value is not None and hit.get("file_sha256") == value[0]
                and hit.get("chunk_sha256") == value[1]
                and isinstance(snippet, str) and snippet and snippet in value[2]):
            current.append(hit)
    return current


def qualify_search_hits(
    reports_dir: Path, reports: list[dict], hits: list[dict],
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    """Recheck selected source and chunk identities in one operation-local image.

    This is a fresh boundary check, not reuse of the preceding search's snapshot.
    The close-time unchanged check guards both results before they can escape.
    """
    conn = _connect_readonly(reports_dir)
    try:
        statuses = _status_map_in_snapshot(conn, reports_dir, reports, verify_source=True)
        eligible = [hit for hit in hits
                    if statuses.get(hit.get("report_id"), {}).get("text_index_status") == STATUS_SEARCHABLE
                    and hit.get("file_sha256")
                    and hit["file_sha256"] == statuses[hit["report_id"]].get("text_index_sha256")]
        return statuses, _current_search_hits_in_snapshot(conn, eligible)
    except sqlite3.Error as exc:
        raise ReportTextIndexCorruptedError() from exc
    finally:
        if conn is not None:
            conn.close()



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
    conn = _connect_readonly(reports_dir)
    if conn is None:
        return []
    try:
        # Qualify sources and query chunks from the same private immutable image.
        # No cache survives this operation: close rechecks the original index bytes.
        # Keep source-file hashing, schema validation and all partial/error semantics.
        statuses = _status_map_in_snapshot(
            conn, reports_dir, list(candidates.values()), verify_source=True,
        )
        candidates = {rid: report for rid, report in candidates.items()
                      if statuses[rid]["text_index_status"] == STATUS_SEARCHABLE}
        if not candidates:
            return []
        terms = _search_terms(value, selected_reports=bool(requested))
        if not terms:
            raise ValueError("检索条件无效")
        placeholders = ",".join("?" for _ in candidates)
        text_filters = " AND ".join("instr(lower(c.text), lower(?)) > 0" for _ in terms)
        rows = conn.execute(
            f"""SELECT c.report_id, c.page, c.text, i.file_sha256, i.error_code
                FROM report_text_chunks c JOIN report_text_index i USING(report_id)
                WHERE i.status=? AND c.report_id IN ({placeholders}) AND {text_filters}""",
            [STATUS_SEARCHABLE, *candidates, *terms],
        ).fetchall()
        ocr_metadata = {}
        for row in rows:
            if row["error_code"] == "LOCAL_OCR_UNVERIFIED":
                if row["report_id"] not in ocr_metadata:
                    ocr_metadata[row["report_id"]] = _ocr_metadata(conn, row["report_id"])
                if ocr_metadata[row["report_id"]] is None:
                    raise ReportTextIndexCorruptedError()
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
            "chunk_sha256": _chunk_sha256(row["text"]),
            "extraction_kind": "LOCAL_OCR_UNVERIFIED" if row["error_code"] == "LOCAL_OCR_UNVERIFIED" else "DOCUMENT_TEXT",
            "ocr_provenance": next((page for page in (ocr_metadata.get(row["report_id"]) or {}).get("pages", []) if page["page_number"] == row["page"]), None),
            "score": score,
            "publish_date": report.get("publish_date") or "",
            "institution": report.get("institution") or "",
            "source_url": report.get("source_url") or "",
        })
    hits.sort(key=lambda hit: (-hit["score"], hit["report_id"], hit["page"] or 0))
    return hits[:limit]


def read_pages(reports_dir: Path, report: dict | None, *, report_id: str,
               selected_report_ids: list[str], expected_file_sha256: str,
               page_from: int, page_to: int, max_pages: int = 8,
               max_chars: int = 12000, max_page_chars: int = 6000) -> dict:
    """Read bounded indexed PDF page text, never a claim of reading the source PDF.

    Caller validates shape/range before expansion. Selection is a workflow scope,
    not authorization; this uses the same local report catalog as other readers.
    """
    limits = ((page_from, 1, 1000000), (page_to, 1, 1000000),
              (max_pages, 1, 20), (max_chars, 1, 20000), (max_page_chars, 1, 20000))
    if any(type(v) is not int or not low <= v <= high for v, low, high in limits):
        raise ValueError("invalid page-read limits")
    if page_to < page_from or page_to - page_from >= 200:
        raise ValueError("requested range must contain 1-200 pages")
    requested = list(range(page_from, page_to + 1))
    result = {"report_id": report_id, "file_sha256": expected_file_sha256,
              "scope": "INDEXED_PAGE_TEXT_ONLY", "full_report_read": False,
              "requested": requested, "items": [], "returned_chars": 0,
              "complete_requested_text": False,
              "limits": {"max_pages": max_pages, "max_chars": max_chars,
                         "max_page_chars": max_page_chars}}

    def finish(items):
        result["items"] = items
        result["coverage"] = {status: [item["page"] for item in items if item["status"] == status]
                              for status in ("readable", "omitted", "invalid", "unreadable", "error")}
        result["returned_chars"] = sum(item.get("returned_chars", 0) for item in items)
        result["complete_requested_text"] = all(
            item["status"] == "readable" and not item["truncated"] for item in items)
        return result

    def fail(status, reason):
        return finish([{"page": page, "status": status, "reason": reason} for page in requested])

    if report_id not in selected_report_ids:
        return fail("invalid", "REPORT_NOT_SELECTED")
    if report is None:
        return fail("invalid", "REPORT_NOT_FOUND")
    # Do not accept client-supplied paths or use catalog corruption to escape root.
    ext = str(report.get("ext") or "").lower()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", report_id) or not re.fullmatch(r"\.[a-z0-9]+", ext):
        return fail("error", "INVALID_SOURCE_METADATA")
    source = Path(reports_dir) / f"{report_id}{ext}"
    if source.resolve().parent != Path(reports_dir).resolve():
        return fail("error", "INVALID_SOURCE_METADATA")
    if report.get("file_sha256") != expected_file_sha256:
        return fail("error", "FILE_CHANGED")
    conn = None
    try:
        if _source_sha256(source) != expected_file_sha256:
            return fail("error", "FILE_CHANGED")
        conn = _connect_readonly(reports_dir)
        if conn is None:
            return fail("unreadable", "NOT_INDEXED")
        conn.execute("BEGIN")
        meta = conn.execute("SELECT * FROM report_text_index WHERE report_id=?", (report_id,)).fetchone()
        if meta is None:
            return fail("unreadable", "NOT_INDEXED")
        if meta["file_sha256"] != expected_file_sha256:
            return fail("error", "INDEX_SOURCE_MISMATCH")
        if meta["status"] == STATUS_ERROR:
            return fail("error", "INDEX_EXTRACTION_FAILED")
        if ext not in {".pdf", ".png", ".jpg", ".jpeg"} or meta["page_count"] is None:
            return fail("unreadable", "PAGE_NUMBERS_UNAVAILABLE")
        page_count = meta["page_count"]
        if type(page_count) is not int or page_count < 0:
            return fail("error", "INDEX_METADATA_INVALID")
        result["page_count"] = page_count
        result["extraction"] = _ocr_metadata(conn, report_id)
        if meta["error_code"] == "LOCAL_OCR_UNVERIFIED" and result["extraction"] is None:
            return fail("error", "INDEX_READ_FAILED")
        items = []
        used_chars = used_pages = 0
        placeholders = {"n/a", "[no text]", "[image]", "ocr_required", "pdf_no_extractable_text", "暂无正文"}
        for page in requested:
            item = {"page": page}
            if page > page_count:
                item.update(status="invalid", reason="PAGE_OUT_OF_RANGE")
            elif meta["status"] != STATUS_SEARCHABLE:
                item.update(status="unreadable", reason="NO_EXTRACTABLE_TEXT")
            else:
                # SQL substring bounds memory as well as response size, including page 1.
                capacity = min(max_page_chars, max_chars - used_chars)
                row = conn.execute("SELECT length(text), substr(text,1,?), substr(text,1,256) FROM report_text_chunks WHERE report_id=? AND page=?",
                                   (max(1, capacity), report_id, page)).fetchone()
                if row is None or not row[0]:
                    item.update(status="unreadable", reason="NO_INDEXED_PAGE_TEXT")
                elif used_pages >= max_pages or capacity <= 0:
                    item.update(status="omitted", reason="PAGE_BUDGET" if used_pages >= max_pages else "CHAR_BUDGET")
                elif not any(char.isalnum() for char in row[1]) or (row[0] <= 256 and row[2].strip().lower() in placeholders):
                    item.update(status="unreadable", reason="EMPTY_OR_PLACEHOLDER_TEXT")
                else:
                    text = row[1]
                    item.update(status="readable", text=text, returned_chars=len(text),
                                indexed_chars=row[0], truncated=len(text) < row[0],
                                reason="CHAR_TRUNCATED" if len(text) < row[0] else "INDEXED_TEXT")
                    used_chars += len(text)
                    used_pages += 1
            items.append(item)
        if _source_sha256(source) != expected_file_sha256:
            return fail("error", "FILE_CHANGED_DURING_READ")
        return finish(items)
    except (ReportTextIndexError, sqlite3.Error):
        return fail("error", "INDEX_READ_FAILED")
    except OSError:
        return fail("error", "SOURCE_UNAVAILABLE")
    finally:
        if conn is not None:
            conn.close()


def _ocr_metadata(conn: sqlite3.Connection, report_id: str) -> dict | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_text_ocr'").fetchone():
        return None
    row = conn.execute("SELECT substr(payload,1,100001) FROM report_text_ocr WHERE report_id=?", (report_id,)).fetchone()
    if row is None:
        return None
    try:
        if len(row[0]) > 100_000:
            raise ValueError()
        payload = json.loads(row[0])
        if (not isinstance(payload, dict) or set(payload) != {"schema_version", "status", "source_sha256", "engine", "language", "source_truth_verified", "limitations", "pages"}
                or not isinstance(payload.get("limitations"), list) or not 1 <= len(payload["limitations"]) <= 10
                or any(not isinstance(value, str) or not value or len(value) > 500 for value in payload["limitations"])
                or payload.get("schema_version") != "local_ocr_preview.v1" or payload.get("status") != "OCR_UNVERIFIED"
                or payload.get("engine") != "local-tesseract" or payload.get("language") not in {"eng", "chi_sim+eng"}
                or payload.get("source_truth_verified") is not False or not isinstance(payload.get("pages"), list)
                or not 1 <= len(payload["pages"]) <= 12):
            raise ValueError()
        source = conn.execute("SELECT file_sha256, page_count FROM report_text_index WHERE report_id=?", (report_id,)).fetchone()
        if source is None or source[0] != payload.get("source_sha256") or source[1] != len(payload["pages"]):
            raise ValueError()
        for number, page in enumerate(payload["pages"], 1):
            if (not isinstance(page, dict) or set(page) != {"page_number", "source_sha256", "image_sha256", "text_sha256", "mean_word_confidence"} or type(page.get("page_number")) is not int or page["page_number"] != number
                    or page.get("source_sha256") != source[0]
                    or any(not isinstance(page.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", page[key])
                           for key in ("image_sha256", "text_sha256"))):
                raise ValueError()
            confidence = page.get("mean_word_confidence")
            if confidence is not None and (type(confidence) not in {int, float} or not 0 <= confidence <= 100):
                raise ValueError()
            chunk = conn.execute("SELECT substr(text,1,100100), length(text) FROM report_text_chunks WHERE report_id=? AND page=?", (report_id, number)).fetchone()
            if chunk and chunk[1] > 100100:
                raise ValueError()
            text = chunk[0].removeprefix("[LOCAL OCR UNVERIFIED: may contain recognition errors; check original page]\n") if chunk else ""
            if _chunk_sha256(text) != page["text_sha256"]:
                raise ValueError()
        return payload
    except (ValueError, TypeError) as exc:
        raise ReportTextIndexCorruptedError() from exc


def index_ocr(reports_dir: Path, report: dict, source_path: Path, extraction: dict, cancel, *, source_snapshot) -> dict:
    """One explicit OCR replacement of the existing derived index, never the original."""
    from local_ocr import OcrError
    source_sha = extraction["source_sha256"]
    if extraction["status"] != "OCR_UNVERIFIED":
        raise OcrError("OCR_NO_TEXT")
    metadata = {key: value for key, value in extraction.items() if key != "pages"}
    metadata["pages"] = [{key: value for key, value in page.items() if key != "text"} for page in extraction["pages"]]
    indexed_at = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        if cancel.is_set():
            raise OcrError("OCR_CANCELLED")
        source_snapshot.assert_unchanged()
        if source_snapshot.sha256 != source_sha:
            raise OcrError("OCR_SOURCE_CHANGED")
        conn = _connect_write(reports_dir)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM report_text_chunks WHERE report_id=?", (report["id"],))
            conn.execute("""INSERT INTO report_text_index VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET file_sha256=excluded.file_sha256,
                status=excluded.status, indexed_at=excluded.indexed_at,
                page_count=excluded.page_count, error_code=excluded.error_code""",
                (report["id"], source_sha, STATUS_SEARCHABLE, indexed_at, len(extraction["pages"]), "LOCAL_OCR_UNVERIFIED"))
            # Keep an uncertainty marker in text so every existing retrieval / AI
            # path retains it even if it does not yet render structured metadata.
            conn.executemany("INSERT INTO report_text_chunks VALUES (?, ?, ?)", [
                (report["id"], page["page_number"], "[LOCAL OCR UNVERIFIED: may contain recognition errors; check original page]\n" + page["text"])
                for page in extraction["pages"] if page["text"]])
            conn.execute("INSERT OR REPLACE INTO report_text_ocr VALUES (?, ?)", (report["id"], json.dumps(metadata)))
            if cancel.is_set():
                raise OcrError("OCR_CANCELLED")
            source_snapshot.assert_unchanged()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    return {"schema_version": "local_ocr_report_receipt.v1", "report_id": report["id"], "file_sha256": source_sha, "status": "SEARCHABLE", "extraction": metadata, "indexed_at": indexed_at}
