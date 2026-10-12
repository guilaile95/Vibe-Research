from __future__ import annotations
import base64
import hashlib
import io
import json
import struct
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, EncodedStreamObject, DecodedStreamObject

import app
import local_ocr as ocr
import myreports as mr
import myreports_fulltext as ft

FIXTURE = Path(__file__).parent / "fixtures/local_ocr/synthetic.png"


def scanned_pdf() -> bytes:
    data = FIXTURE.read_bytes()
    # Embed the synthetic RGB PNG's filtered IDAT stream, with no PDF text layer.
    offset = 8; compressed = b""
    while offset < len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        if data[offset + 4:offset + 8] == b"IDAT":
            compressed += data[offset + 8:offset + 8 + size]
        offset += 12 + size
    writer = PdfWriter()
    page = writer.add_blank_page(width=1000, height=240)
    image = EncodedStreamObject()
    image._data = compressed
    image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                  NameObject("/Width"): NumberObject(1000), NameObject("/Height"): NumberObject(240),
                  NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8),
                  NameObject("/Filter"): NameObject("/FlateDecode"), NameObject("/DecodeParms"): DictionaryObject({
                      NameObject("/Predictor"): NumberObject(15), NameObject("/Colors"): NumberObject(3),
                      NameObject("/BitsPerComponent"): NumberObject(8), NameObject("/Columns"): NumberObject(1000)})})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): writer._add_object(image)})})
    stream = DecodedStreamObject(); stream.set_data(b"q 1000 0 0 240 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()


def extraction(data: bytes) -> dict:
    return {"schema_version": "local_ocr_preview.v1", "status": "OCR_UNVERIFIED", "source_sha256": hashlib.sha256(data).hexdigest(), "engine": "local-tesseract", "language": "eng",
            "source_truth_verified": False, "limitations": ocr.LIMITATIONS,
            "pages": [{"page_number": 1, "text": "synthetic catalyst 600000", "source_sha256": hashlib.sha256(data).hexdigest(),
                       "image_sha256": "a" * 64, "text_sha256": hashlib.sha256(b"synthetic catalyst 600000").hexdigest(), "mean_word_confidence": 92.5}]}


def upload(client, data, ext=".png"):
    result = client.post("/api/myreports", json={"name": "synthetic" + ext, "content_b64": base64.b64encode(data).decode()})
    assert result.status_code == 200
    return result.json()["data"]


def test_explicit_ocr_index_reuses_source_search_pages_and_readonly(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    client = TestClient(app.app)
    assert client.get("/api/local-ocr/capability").status_code == 200
    assert not mr.REPORTS_DIR.exists()
    original = FIXTURE.read_bytes()
    report = upload(client, original)
    source = mr.REPORTS_DIR / (report["id"] + report["ext"])
    snapshot = source.read_bytes()
    monkeypatch.setattr(ocr, "extract", lambda *args: extraction(original))
    response = client.post(f"/api/local-ocr/reports/{report['id']}", json={"expected_file_sha256": report["file_sha256"], "language": "eng", "confirm_local_processing": True})
    assert response.status_code == 200, response.text
    assert source.read_bytes() == snapshot
    hit = mr.search_report_text("catalyst")[0]
    assert hit["page"] == 1 and hit["extraction_kind"] == "LOCAL_OCR_UNVERIFIED"
    assert "UNVERIFIED" in hit["snippet"]
    page = mr.read_report_pages(report_id=report["id"], selected_report_ids=[report["id"]], expected_file_sha256=report["file_sha256"], page_from=1, page_to=1)
    assert page["coverage"]["readable"] == [1]
    assert page["extraction"]["pages"][0]["image_sha256"] == "a" * 64
    assert page["extraction"]["source_truth_verified"] is False
    # Modified source invalidates both existing retrieval routes, no stale fallback.
    source.write_bytes(b"changed")
    assert mr.search_report_text("catalyst") == []
    assert mr.read_report_pages(report_id=report["id"], selected_report_ids=[report["id"]], expected_file_sha256=report["file_sha256"], page_from=1, page_to=1)["coverage"]["error"] == [1]


def test_no_mutation_on_cancel_stale_or_failed_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    client = TestClient(app.app)
    original = FIXTURE.read_bytes(); report = upload(client, original)
    index = mr.REPORTS_DIR / ft.INDEX_NAME
    before = index.read_bytes()
    def cancelled(data, ext, lang, cancel):
        cancel.set(); return extraction(data)
    monkeypatch.setattr(ocr, "extract", cancelled)
    with pytest.raises(ocr.OcrError, match="OCR_CANCELLED"):
        mr.ocr_report_text(report["id"], report["file_sha256"], "eng", threading.Event())
    assert index.read_bytes() == before
    with pytest.raises(ocr.OcrError, match="OCR_SOURCE_CHANGED"):
        mr.ocr_report_text(report["id"], "0" * 64, "eng", threading.Event())
    with pytest.raises(ocr.OcrError, match="OCR_REPORT_NOT_FOUND"):
        mr.ocr_report_text("../../secret", report["file_sha256"], "eng", threading.Event())


def test_preview_schema_ephemeral_and_no_models(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    client = TestClient(app.app)
    data = FIXTURE.read_bytes()
    monkeypatch.setattr(ocr, "extract", lambda *args: extraction(data))
    body = {"content_b64": base64.b64encode(data).decode(), "extension": ".png", "confirm_local_processing": True}
    assert client.post("/api/local-ocr/preview", json=body).json()["data"]["source_truth_verified"] is False
    assert not mr.REPORTS_DIR.exists()
    for update in ({"path": "/private"}, {"extension": ".pdf"}, {"language": "--help"}, {"confirm_local_processing": False}, {"confirm_local_processing": 1}, {"confirm_local_processing": "true"}):
        assert client.post("/api/local-ocr/preview", json=body | update).status_code == 422
    assert client.post("/api/local-ocr/preview", json=body | {"content_b64": "%%"}).status_code == 400


def test_limits_magic_malformed_and_semaphore(monkeypatch):
    with pytest.raises(ocr.OcrError, match="SIZE_LIMIT"):
        ocr.extract(b"x" * (ocr.MAX_BYTES + 1), ".png")
    with pytest.raises(ocr.OcrError, match="INVALID_IMAGE"):
        ocr.extract(b"not png", ".png")
    huge = bytearray(FIXTURE.read_bytes()); huge[16:24] = struct.pack(">II", 6001, 10)
    with pytest.raises(ocr.OcrError, match="DIMENSION_LIMIT"):
        ocr.extract(bytes(huge), ".png")
    with pytest.raises(ocr.OcrError, match="MALFORMED_OUTPUT"):
        ocr._parse_tsv(b"bad\toutput")
    cancel = threading.Event(); cancel.set()
    with pytest.raises(ocr.OcrError, match="CANCELLED"):
        ocr.extract(FIXTURE.read_bytes(), ".png", cancel=cancel)
    ocr._SLOT.acquire()
    try:
        with pytest.raises(ocr.OcrError, match="BUSY"):
            ocr.extract(FIXTURE.read_bytes(), ".png")
    finally:
        ocr._SLOT.release()
    monkeypatch.setattr(ocr, "_binary", lambda name: None)
    assert ocr.capability()["status"] == "DEPENDENCY_UNAVAILABLE"
    with pytest.raises(ocr.OcrError, match="DEPENDENCY_UNAVAILABLE"):
        ocr.extract(FIXTURE.read_bytes(), ".png")


def test_real_installed_tesseract_and_poppler_synthetic_only(tmp_path):
    if not ocr.capability()["pdf"]:
        pytest.skip("Local Tesseract/Poppler are not installed; no installation in tests")
    for data, ext in ((FIXTURE.read_bytes(), ".png"), (scanned_pdf(), ".pdf")):
        original_sha = hashlib.sha256(data).hexdigest()
        result = ocr.extract(data, ext)
        assert result["status"] == "OCR_UNVERIFIED"
        assert "SYNTHETIC REPORT 600000" in result["pages"][0]["text"]
        assert result["source_sha256"] == original_sha
        assert result["pages"][0]["text_sha256"] == hashlib.sha256(result["pages"][0]["text"].encode()).hexdigest()
        if ext == ".pdf":
            source = tmp_path / "synthetic.pdf"; source.write_bytes(data)
            assert ft._extract_pdf(source)[0] == ft.STATUS_OCR_REQUIRED
            assert source.read_bytes() == data


def test_command_adapter_fixed_arguments_timeout_group_cleanup(tmp_path, monkeypatch):
    calls = []; killed = []
    class Process:
        pid = 123456
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout): self.returncode = -9; return -9
    process = Process()
    def launch(args, **kwargs):
        calls.append((args, kwargs)); return process
    monkeypatch.setattr(ocr, "_binary", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr, "_resource_supported", lambda: True)
    monkeypatch.setattr(ocr.subprocess, "Popen", launch)
    monkeypatch.setattr(ocr.os, "killpg", lambda pid, sig: killed.append(pid), raising=False)
    ticks = iter([0, 2])
    monkeypatch.setattr(ocr.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ocr.OcrError, match="TIMEOUT"):
        ocr._run("tesseract", [str(tmp_path / "source.png"), "stdout"], tmp_path, threading.Event(), 1)
    assert calls[0][0][1:3] == ["-I", "-S"]
    assert calls[0][0][4] == "/usr/bin/tesseract"
    assert calls[0][1]["shell"] is False and calls[0][1]["start_new_session"] is True
    assert "HTTP_PROXY" not in calls[0][1]["env"]
    assert killed == [123456]


def test_source_change_during_extraction_keeps_index(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    original = FIXTURE.read_bytes(); report = upload(TestClient(app.app), original)
    source = mr.REPORTS_DIR / (report["id"] + ".png")
    before = (mr.REPORTS_DIR / ft.INDEX_NAME).read_bytes()
    def changed(data, *args):
        source.write_bytes(b"replaced"); return extraction(data)
    monkeypatch.setattr(ocr, "extract", changed)
    with pytest.raises(ocr.OcrError, match="SOURCE_CHANGED"):
        mr.ocr_report_text(report["id"], report["file_sha256"], "eng", threading.Event())
    assert (mr.REPORTS_DIR / ft.INDEX_NAME).read_bytes() == before


def test_corrupt_ocr_page_binding_fails_closed(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    original = FIXTURE.read_bytes(); report = upload(TestClient(app.app), original)
    monkeypatch.setattr(ocr, "extract", lambda *args: extraction(original))
    mr.ocr_report_text(report["id"], report["file_sha256"], "eng", threading.Event())
    conn = sqlite3.connect(mr.REPORTS_DIR / ft.INDEX_NAME)
    conn.execute("UPDATE report_text_chunks SET text='corrupt'"); conn.commit(); conn.close()
    page = mr.read_report_pages(report_id=report["id"], selected_report_ids=[report["id"]], expected_file_sha256=report["file_sha256"], page_from=1, page_to=1)
    assert page["coverage"]["error"] == [1]


def test_actual_encrypted_and_overpage_pdf_fail_closed():
    if not ocr.capability()["pdf"]:
        pytest.skip("Local PDF executables not installed")
    writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt("synthetic-only")
    out = io.BytesIO(); writer.write(out)
    with pytest.raises(ocr.OcrError):
        ocr.extract(out.getvalue(), ".pdf")
    writer = PdfWriter()
    for _ in range(13): writer.add_blank_page(100, 100)
    out = io.BytesIO(); writer.write(out)
    with pytest.raises(ocr.OcrError, match="PAGE_LIMIT"):
        ocr.extract(out.getvalue(), ".pdf")
    with pytest.raises(ocr.OcrError):
        ocr.extract(b"%PDF-1.7 broken", ".pdf")


def test_legacy_image_readonly_identity_then_explicit_index(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    mr.REPORTS_DIR.mkdir()
    data = FIXTURE.read_bytes(); source = mr.REPORTS_DIR / "legacy.png"; source.write_bytes(data)
    catalog = mr.REPORTS_DIR / "index.json"
    catalog.write_text(json.dumps([{"id": "legacy", "name": "legacy.png", "industry": "", "ext": ".png", "size": len(data), "ts": 1}]))
    before = catalog.read_bytes()
    identity = mr.ocr_report_identity("legacy")
    assert identity["writes"] == 0 and catalog.read_bytes() == before
    assert not (mr.REPORTS_DIR / ft.INDEX_NAME).exists()
    monkeypatch.setattr(ocr, "extract", lambda *args: extraction(data))
    mr.ocr_report_text("legacy", identity["file_sha256"], "eng", threading.Event())
    assert source.read_bytes() == data
    assert mr.list_reports()[0]["file_sha256"] == identity["file_sha256"]


def test_disconnect_cancels_worker_before_return():
    import asyncio
    import local_ocr_router
    from fastapi import HTTPException
    class Request:
        async def is_disconnected(self): return True
    stopped = threading.Event()
    def action(cancel):
        assert cancel.wait(1)
        stopped.set()
        raise ocr.OcrError("OCR_CANCELLED")
    with pytest.raises(HTTPException) as failure:
        asyncio.run(local_ocr_router._action(Request(), action))
    assert failure.value.detail == "OCR_CANCELLED" and stopped.is_set()


def test_checkpointed_wal_reads_never_open_source_sqlite(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "reports")
    data = FIXTURE.read_bytes(); report = upload(TestClient(app.app), data)
    index = mr.REPORTS_DIR / ft.INDEX_NAME
    connection = sqlite3.connect(index)
    connection.execute("PRAGMA journal_mode=WAL"); connection.close()
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in mr.REPORTS_DIR.iterdir() if p.is_file()}
    real_connect = ft.sqlite3.connect
    calls = []
    def private_only(target, *args, **kwargs):
        calls.append(target)
        assert target == ":memory:"
        return real_connect(target, *args, **kwargs)
    monkeypatch.setattr(ft.sqlite3, "connect", private_only)
    assert mr.list_reports()[0]["id"] == report["id"]
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in mr.REPORTS_DIR.iterdir() if p.is_file()}
    assert before == after and calls == [":memory:"]


def test_source_symlink_swap_never_reads_replacement(tmp_path, monkeypatch):
    if not hasattr(__import__('os'), 'O_NOFOLLOW'):
        pytest.skip('POSIX nofollow test; platform otherwise capability-closed')
    source = tmp_path / 'source.png'; source.write_bytes(FIXTURE.read_bytes())
    replacement = tmp_path / 'replacement.png'; replacement.write_bytes(b'private replacement')
    real_open = ocr.os.open
    def swapped(path, flags, *args, **kwargs):
        source.unlink(); source.symlink_to(replacement)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(ocr.os, 'open', swapped)
    with pytest.raises((OSError, ocr.OcrError)):
        ocr.OcrSource(source)
    assert replacement.read_bytes() == b'private replacement'


def test_native_exec_resource_limits_before_exec(monkeypatch):
    pytest.importorskip('resource')
    import local_ocr_exec
    calls = []
    monkeypatch.setattr(local_ocr_exec.sys, 'platform', 'linux')
    monkeypatch.setattr(local_ocr_exec.sys, 'argv', ['launcher', '/usr/bin/tesseract', 'synthetic.png', 'stdout'])
    monkeypatch.setattr(local_ocr_exec.resource, 'setrlimit', lambda key, limits: calls.append((key, limits)))
    monkeypatch.setattr(local_ocr_exec.os, 'execv', lambda executable, args: calls.append(('exec', executable, args)))
    local_ocr_exec.main()
    assert calls[0][1] == (768 * 1024 * 1024,) * 2
    assert calls[1][1] == (90, 90)
    assert calls[2][1] == (16 * 1024 * 1024,) * 2
    assert calls[-1] == ('exec', '/usr/bin/tesseract', ['/usr/bin/tesseract', 'synthetic.png', 'stdout'])


def test_resource_failure_removes_temporary_files(monkeypatch):
    roots = []
    def failure(name, args, root, cancel, deadline):
        roots.append(root)
        raise ocr.OcrError('OCR_RESOURCE_GUARD_UNAVAILABLE')
    monkeypatch.setattr(ocr, '_run', failure)
    monkeypatch.setattr(ocr, '_language_config', lambda language: Path('/synthetic/tessdata'))
    with pytest.raises(ocr.OcrError, match='RESOURCE_GUARD_UNAVAILABLE'):
        ocr.extract(FIXTURE.read_bytes(), '.png')
    assert roots and not roots[0].exists()


def test_running_cancel_kills_group_and_reaps(tmp_path, monkeypatch):
    cancelled = threading.Event(); killed = []; reaped = []
    class Process:
        pid = 123456; returncode = None
        def poll(self): return None
        def wait(self, timeout): reaped.append(timeout)
    def launch(*args, **kwargs):
        cancelled.set(); return Process()
    monkeypatch.setattr(ocr, '_resource_supported', lambda: True)
    monkeypatch.setattr(ocr, '_binary', lambda name: '/usr/bin/tesseract')
    monkeypatch.setattr(ocr.subprocess, 'Popen', launch)
    monkeypatch.setattr(ocr.os, 'killpg', lambda pid, sig: killed.append(pid), raising=False)
    with pytest.raises(ocr.OcrError, match='CANCELLED'):
        ocr._run('tesseract', ['synthetic.png', 'stdout'], tmp_path, cancelled, ocr.time.monotonic() + 5)
    assert killed == [123456] and reaped == [5]


def test_late_page_excerpt_keeps_server_verified_ocr_uncertainty(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, 'REPORTS_DIR', tmp_path / 'reports')
    data = FIXTURE.read_bytes(); report = upload(TestClient(app.app), data)
    result = extraction(data)
    text = ('synthetic filler ' * 100) + 'rare-catalyst'
    result['pages'][0]['text'] = text
    result['pages'][0]['text_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    monkeypatch.setattr(ocr, 'extract', lambda *args: result)
    mr.ocr_report_text(report['id'], report['file_sha256'], 'eng', threading.Event())
    hit = mr.search_report_text('rare-catalyst')[0]
    assert 'LOCAL OCR' not in hit['snippet']
    hit.pop('extraction_kind')  # Client labels cannot remove server uncertainty.
    context, sources, _ = mr.build_chat_report_context([hit], report_ids=[report['id']])
    assert sources and 'LOCAL_OCR_UNVERIFIED' in context and 'rare-catalyst' in context


@pytest.mark.parametrize('update', [{'limitations': {}}, {'limitations': ['x' * 501]}, {'extra': 'unknown'}])
def test_ocr_metadata_unknown_or_invalid_fields_fail_closed(tmp_path, monkeypatch, update):
    import sqlite3
    monkeypatch.setattr(mr, 'REPORTS_DIR', tmp_path / 'reports')
    data = FIXTURE.read_bytes(); report = upload(TestClient(app.app), data)
    monkeypatch.setattr(ocr, 'extract', lambda *args: extraction(data))
    mr.ocr_report_text(report['id'], report['file_sha256'], 'eng', threading.Event())
    with sqlite3.connect(mr.REPORTS_DIR / ft.INDEX_NAME) as connection:
        payload = json.loads(connection.execute('SELECT payload FROM report_text_ocr').fetchone()[0])
        payload.update(update)
        connection.execute('UPDATE report_text_ocr SET payload=?', (json.dumps(payload),))
    page = mr.read_report_pages(report_id=report['id'], selected_report_ids=[report['id']], expected_file_sha256=report['file_sha256'], page_from=1, page_to=1)
    assert page['coverage']['error'] == [1]


def test_chinese_unavailable_is_distinct_without_english_fallback(tmp_path, monkeypatch):
    root = tmp_path / 'tessdata'; root.mkdir(); (root / 'eng.traineddata').write_bytes(b'synthetic')
    monkeypatch.setattr(ocr, '_tessdata_directory', lambda: root)
    monkeypatch.setattr(ocr, '_resource_supported', lambda: True)
    monkeypatch.setattr(ocr, '_binary', lambda name: '/usr/bin/' + name)
    calls = []
    monkeypatch.setattr(ocr, '_run', lambda *args: calls.append(args))
    capability = ocr.capability()
    assert capability['image'] is True and capability['chinese_language_status'] == 'CHINESE_LANGUAGE_UNAVAILABLE'
    assert capability['automatic_language_fallback'] is False
    with pytest.raises(ocr.OcrError, match='CHINESE_LANGUAGE_UNAVAILABLE'):
        ocr.extract(FIXTURE.read_bytes(), '.png', 'chi_sim+eng')
    assert calls == []
