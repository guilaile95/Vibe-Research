from __future__ import annotations
import base64
import hashlib
import io
import multiprocessing
from pathlib import Path
import time
import zipfile

import pytest
import document_parse_budget as budget
import myreports as reports
import myreports_fulltext as fulltext


def _slow_worker(result, source, extension):
    Path(source + '.started').write_text('started')
    time.sleep(30)
    Path(source + '.continued').write_text('must not execute')


def _docx(text):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:document>')
    return out.getvalue()


def test_docx_expansion_is_archived_not_searchable(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, 'REPORTS_DIR', tmp_path)
    content = _docx('Z' * (budget.MAX_TEXT_CHARS + 1))
    saved = reports.save_report('expanded.docx', base64.b64encode(content).decode())
    assert saved['text_index_status'] == fulltext.STATUS_ARCHIVED
    assert saved['text_index_error'] == 'DOCUMENT_RESOURCE_LIMIT'
    assert (tmp_path / (saved['id'] + '.docx')).read_bytes() == content
    assert reports.search_report_text('ZZZ', report_ids=[saved['id']]) == []


def test_docx_zip_declared_expansion_rejected(tmp_path):
    source = tmp_path / 'large.docx'
    source.write_bytes(_docx('X' * (budget.MAX_XML_BYTES + 1)))
    assert budget.extract(source, '.docx')[3] == 'DOCUMENT_RESOURCE_LIMIT'


def test_ordinary_docx_remains_searchable(tmp_path):
    source = tmp_path / 'small.docx'
    source.write_bytes(_docx('Ordinary report 毛利率'))
    status, chunks, _, error = budget.extract(source, '.docx')
    assert status == fulltext.STATUS_SEARCHABLE and error == ''
    assert chunks == [(0, 'Ordinary report 毛利率')]


def test_timeout_kills_and_reaps_parser(tmp_path):
    source = tmp_path / 'input.txt'
    source.write_text('ordinary')
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    result = budget.extract(source, '.txt', timeout=1, _target=_slow_worker)
    assert time.monotonic() - started < 4
    assert Path(str(source) + '.started').exists()
    assert result[0] == fulltext.STATUS_ARCHIVED and result[1] == []
    assert {p.pid for p in multiprocessing.active_children()} == before
    assert not Path(str(source) + '.continued').exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_concurrency_admission_fail_closed(tmp_path):
    source = tmp_path / 'input.txt'
    source.write_text('ordinary')
    assert budget._SLOTS.acquire(False) and budget._SLOTS.acquire(False)
    try:
        assert budget.extract(source, '.txt')[3] == 'DOCUMENT_PARSER_BUSY'
    finally:
        budget._SLOTS.release()
        budget._SLOTS.release()
    assert budget.extract(source, '.txt')[0] == fulltext.STATUS_SEARCHABLE


def test_predecode_size_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, 'REPORTS_DIR', tmp_path)
    monkeypatch.setattr(reports, 'MAX_BYTES', 8)
    monkeypatch.setattr(reports.base64, 'b64decode', lambda *a, **kw: pytest.fail('decode must not run'))
    with pytest.raises(reports.ReportError, match='大小上限'):
        reports.save_report('large.txt', 'A' * 1100)
    assert not list(tmp_path.iterdir())


def test_pdf_page_and_character_budgets(tmp_path, monkeypatch):
    import pypdf
    class Page:
        def extract_text(self):
            return 'x' * (budget.MAX_PAGE_CHARS + 1)
    class Reader:
        pages = [Page()]
        def __init__(self, *a, **kw): pass
    monkeypatch.setattr(pypdf, 'PdfReader', Reader)
    assert fulltext._extract_pdf(tmp_path / 'synthetic.pdf')[3] == 'DOCUMENT_RESOURCE_LIMIT'
    Reader.pages = [Page()] * (budget.MAX_PAGES + 1)
    assert fulltext._extract_pdf(tmp_path / 'synthetic.pdf')[3] == 'DOCUMENT_RESOURCE_LIMIT'


def test_reindex_failure_removes_old_searchable_text(tmp_path):
    source = tmp_path / 'report.docx'
    source.write_bytes(_docx('formerly searchable uniquephrase'))
    report = {'id': 'report', 'ext': '.docx'}
    assert fulltext.index_report(tmp_path, report, source)['status'] == fulltext.STATUS_SEARCHABLE
    source.write_bytes(_docx('Z' * (budget.MAX_TEXT_CHARS + 1)))
    result = fulltext.index_report(tmp_path, report, source)
    assert result['status'] == fulltext.STATUS_ARCHIVED
    import sqlite3
    with sqlite3.connect(tmp_path / fulltext.INDEX_NAME) as conn:
        assert conn.execute('SELECT count(*) FROM report_text_chunks').fetchone()[0] == 0
