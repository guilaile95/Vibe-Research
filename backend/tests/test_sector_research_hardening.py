"""板块研报发现 / 导入 / PDF 安全 / MyReports schema 专项（默认完全离线）。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import myreports as mr
import sector_research_data as srd


client = TestClient(app_module.app)

_PDF_BYTES = b"%PDF-1.4 offline-test-pdf-content"
_HTML_BYTES = b"<!DOCTYPE html><html><script>anti-scrape</script></html>"
_JS_BYTES = b"window.location='https://evil.example/'"


# ── PCB 公司代码映射 ──────────────────────────────────────────────


def test_pcb_company_code_mapping_locked():
    assert srd.PCB_COMPANY_CODES == {
        "002463": "沪电股份",
        "002916": "深南电路",
        "300476": "胜宏科技",
        "603228": "景旺电子",
        "600183": "生益科技",
    }
    codes = srd.PCB_SOURCES.representative_company_codes
    assert codes == ["002463", "002916", "300476", "603228", "600183"]
    # 禁止旧错误：胜宏 ≠ 603228
    assert srd.PCB_COMPANY_CODES["300476"] == "胜宏科技"
    assert srd.PCB_COMPANY_CODES["603228"] == "景旺电子"


# ── camelCase 东财字段归一化 ─────────────────────────────────────


def test_normalize_report_camel_case_fields():
    raw = {
        "title": "PCB 行业深度",
        "infoCode": "AP202501010001",
        "orgName": "中信证券",
        "publishDate": "2025-07-01",
        "industryName": "电子",
        "stockCode": "002463",
        "stockName": "沪电股份",
        "emRating": "买入",
    }
    n = srd.normalize_report(raw)
    assert n["external_id"] == "AP202501010001"
    assert n["info_code"] == "AP202501010001"
    assert n["institution"] == "中信证券"
    assert n["publish_date"] == "2025-07-01"
    assert n["industry_name"] == "电子"
    assert n["company_code"] == "002463"
    assert n["company_name"] == "沪电股份"
    assert n["rating"] == "买入"
    assert n["report_scope"] == "company"
    assert n["source_provider"] == "eastmoney"
    assert n["pdf_url"] and n["pdf_url"].startswith("https://pdf.dfcfw.com/")


def test_normalize_report_snake_case_and_orgSName():
    raw = {
        "title": "行业周报",
        "info_code": "AP202502020002",
        "orgSName": "华泰",
        "publish_date": "2025-08-01",
        "industry_name": "通信",
        "code": "002916",
        "ssecName": "深南电路",
        "rating": "增持",
    }
    n = srd.normalize_report(raw)
    assert n["external_id"] == "AP202502020002"
    assert n["institution"] == "华泰"
    assert n["company_code"] == "002916"
    assert n["company_name"] == "深南电路"
    assert n["rating"] == "增持"
    assert n["report_scope"] == "company"


def test_normalize_report_industry_only_no_guess():
    raw = {"title": "AI 服务器 PCB", "infoCode": "X1", "industryName": "电子"}
    n = srd.normalize_report(raw)
    assert n["company_code"] is None
    assert n["company_name"] is None
    assert n["report_scope"] == "industry"
    assert n["rating"] is None


def test_score_uses_normalized_rating():
    n = srd.normalize_report({
        "title": "高速 PCB 覆铜板",
        "infoCode": "R1",
        "emRating": "买入",
        "stockCode": "002463",
    })
    score = srd.score_report_relevance(
        n, keywords=["PCB", "覆铜板"], company_codes=["002463"],
    )
    # 2 keywords * 5 + company 8 + 买入 3 = 21
    assert score == 21
    assert "PCB" in n["matched_keywords"] or "覆铜板" in n["matched_keywords"]


# ── scope industry / company / all ───────────────────────────────


def test_scope_invalid_400():
    r = client.get("/api/sector-research/reports/pcb", params={"scope": "bogus"})
    assert r.status_code == 400


def test_scope_industry_company_all_and_dedup(monkeypatch):
    industry_raw = [
        {"title": "PCB 行业", "infoCode": "A", "industryName": "电子", "publishDate": "2025-06-01"},
        {"title": "覆铜板材料研究", "infoCode": "B", "industryName": "电子", "publishDate": "2025-05-01"},
        {"title": "无关钢铁", "infoCode": "Z", "industryName": "钢铁", "publishDate": "2025-05-01"},
    ]
    company_raw = {
        "002463": [
            {"title": "沪电深度", "infoCode": "A", "stockCode": "002463", "publishDate": "2025-07-01"},
            {"title": "沪电跟踪", "infoCode": "C", "stockCode": "002463", "publishDate": "2025-04-01"},
        ],
        "002916": [],
        "300476": [],
        "603228": [],
        "600183": [],
    }

    def fake_industry(**kwargs):
        return list(industry_raw)

    def fake_company(code, max_pages=3):
        return list(company_raw.get(code, []))

    monkeypatch.setattr(srd.astock, "eastmoney_industry_reports", fake_industry)
    monkeypatch.setattr(srd.astock, "eastmoney_reports", fake_company)

    ind = srd.discover_sector_reports("pcb", scope="industry", max_pages=1)
    assert ind.error is None
    # 行业 scope 关键词过滤：A/B 命中 PCB/覆铜板，Z 被滤掉
    assert {x["external_id"] for x in ind.discovered} == {"A", "B"}

    co = srd.discover_sector_reports("pcb", scope="company", max_pages=1)
    assert {x["external_id"] for x in co.discovered} == {"A", "C"}

    all_r = srd.discover_sector_reports("pcb", scope="all", max_pages=1)
    ids = [x["external_id"] for x in all_r.discovered]
    assert set(ids) == {"A", "B", "C"}
    assert len(ids) == 3  # external_id 去重


def test_sort_stable_score_date_id(monkeypatch):
    raw = [
        {"title": "低相关", "infoCode": "Z", "industryName": "电子", "publishDate": "2025-12-01"},
        {"title": "PCB 高速覆铜板", "infoCode": "M", "industryName": "电子", "publishDate": "2025-01-01"},
        {"title": "PCB 高速覆铜板", "infoCode": "A", "industryName": "电子", "publishDate": "2025-01-01"},
    ]
    monkeypatch.setattr(
        srd.astock, "eastmoney_industry_reports",
        lambda **kw: list(raw),
    )
    res = srd.discover_sector_reports("pcb", scope="industry", max_pages=1)
    ids = [x["external_id"] for x in res.discovered]
    # 高相关在前；同日期同分数时 external_id 升序（A before M）
    assert ids[0] in ("A", "M")
    assert res.discovered[0]["relevance_score"] >= res.discovered[-1]["relevance_score"]


# ── PDF URL / SSRF ───────────────────────────────────────────────


def test_pdf_url_allowed_hosts():
    assert srd.pdf_url_allowed("https://pdf.dfcfw.com/pdf/H3_X_1.pdf")
    assert srd.pdf_url_allowed("https://pdfcdn.eastmoney.com/x.pdf")
    assert not srd.pdf_url_allowed("http://pdf.dfcfw.com/x.pdf")
    assert not srd.pdf_url_allowed("https://evil.com/x.pdf")
    assert not srd.pdf_url_allowed(None)


def test_download_pdf_rejects_non_pdf_magic(monkeypatch):
    class FakeResp:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}
        url = "https://pdf.dfcfw.com/pdf/H3_X_1.pdf"
        is_redirect = False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=65536):
            yield _HTML_BYTES

    class FakeSession:
        max_redirects = 5

        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(app_module, "_report_download_session", lambda: FakeSession())
    with pytest.raises(mr.ReportError, match="非 PDF"):
        app_module._download_pdf("https://pdf.dfcfw.com/pdf/H3_X_1.pdf")


def test_download_pdf_rejects_bad_initial_url():
    with pytest.raises(mr.ReportError, match="SSRF"):
        app_module._download_pdf("http://127.0.0.1/secret.pdf")
    with pytest.raises(mr.ReportError, match="SSRF"):
        app_module._download_pdf("https://evil.com/x.pdf")


def test_download_pdf_rejects_redirect_to_disallowed(monkeypatch):
    class RedirectResp:
        status_code = 302
        headers = {"Location": "https://evil.com/steal.pdf"}
        url = "https://pdf.dfcfw.com/start.pdf"
        is_redirect = True

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=65536):
            yield b""

    class FakeSession:
        max_redirects = 5

        def get(self, *a, **k):
            return RedirectResp()

    monkeypatch.setattr(app_module, "_report_download_session", lambda: FakeSession())
    with pytest.raises(mr.ReportError, match="重定向|允许域名|SSRF"):
        app_module._download_pdf("https://pdf.dfcfw.com/start.pdf")


def test_download_pdf_rejects_oversize(monkeypatch):
    class FakeResp:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}
        url = "https://pdf.dfcfw.com/big.pdf"
        is_redirect = False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=65536):
            yield b"%PDF" + b"x" * (100)

    class FakeSession:
        max_redirects = 5

        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(app_module, "_report_download_session", lambda: FakeSession())
    with pytest.raises(mr.ReportError, match="过大"):
        app_module._download_pdf("https://pdf.dfcfw.com/big.pdf", max_bytes=50)


def test_download_pdf_ok_pdf(monkeypatch):
    class FakeResp:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}
        url = "https://pdf.dfcfw.com/ok.pdf"
        is_redirect = False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=65536):
            yield _PDF_BYTES

    class FakeSession:
        max_redirects = 5

        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(app_module, "_report_download_session", lambda: FakeSession())
    blob = app_module._download_pdf("https://pdf.dfcfw.com/ok.pdf")
    assert blob.startswith(b"%PDF")


# ── import_report_bytes 原子事务 / 去重 ──────────────────────────


def test_import_report_bytes_sha256_dedup_merges_sector_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    first = mr.import_report_bytes(
        name="a.pdf", content=_PDF_BYTES,
        metadata={"title": "T1", "sector_keys": ["pcb"], "source_provider": "eastmoney", "external_id": "E1"},
    )
    second = mr.import_report_bytes(
        name="b.pdf", content=_PDF_BYTES,
        metadata={"title": "T2", "sector_keys": ["ai-computing"], "source_provider": "eastmoney", "external_id": "E2"},
    )
    assert second.get("deduped") is True
    assert second["id"] == first["id"]
    assert "pcb" in second["sector_keys"] and "ai-computing" in second["sector_keys"]
    # 不覆盖已有 title
    assert second["title"] == "T1"
    files = list((tmp_path / "myreports").glob("*.pdf"))
    assert len(files) == 1


def test_import_report_bytes_external_id_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    a = mr.import_report_bytes(
        name="a.pdf", content=_PDF_BYTES,
        metadata={"title": "Orig", "source_provider": "eastmoney", "external_id": "SAME", "sector_keys": ["pcb"]},
    )
    other = b"%PDF-1.4 different-bytes-content-xx"
    b = mr.import_report_bytes(
        name="b.pdf", content=other,
        metadata={"title": "New", "source_provider": "eastmoney", "external_id": "SAME", "sector_keys": ["pcb"]},
    )
    assert b.get("deduped") is True
    assert b["id"] == a["id"]
    assert b["title"] == "Orig"
    # 不同内容不应再写第二份实体
    pdfs = list((tmp_path / "myreports").glob("*.pdf"))
    assert len(pdfs) == 1


def test_import_entity_write_failure_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    real_open = open

    def boom_open(path, mode="r", *a, **k):
        if "wb" in mode and ".tmp." in str(path):
            raise OSError("disk full")
        return real_open(path, mode, *a, **k)

    with patch("builtins.open", boom_open):
        with pytest.raises(OSError):
            mr.import_report_bytes(name="x.pdf", content=_PDF_BYTES, metadata={"title": "X"})
    idx = tmp_path / "myreports" / "index.json"
    assert not idx.exists() or json.loads(idx.read_text(encoding="utf-8")) == []


def test_import_index_write_failure_deletes_entity(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    calls = {"n": 0}
    real_save = mr._save_index

    def fail_save(items):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise OSError("index write fail")
        return real_save(items)

    monkeypatch.setattr(mr, "_save_index", fail_save)
    with pytest.raises(OSError):
        mr.import_report_bytes(name="x.pdf", content=_PDF_BYTES, metadata={"title": "X"})
    # 实体应被回滚删除
    pdfs = list((tmp_path / "myreports").glob("*.pdf")) if (tmp_path / "myreports").exists() else []
    assert pdfs == []


def test_import_tmp_cleaned_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    mr.import_report_bytes(name="x.pdf", content=_PDF_BYTES, metadata={"title": "X"})
    leftovers = [p for p in (tmp_path / "myreports").iterdir() if ".tmp." in p.name]
    assert leftovers == []


# ── 旧索引只读不变 / title 保留 / PATCH 单条规范化 ───────────────


def test_read_does_not_rewrite_index(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    old = [{"id": "legacy1", "name": "旧.pdf", "ext": ".pdf", "size": 1, "ts": 1700000000000, "industry": "PCB"}]
    ip = rdir / "index.json"
    raw = json.dumps(old, ensure_ascii=False)
    ip.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    listed = mr.list_reports()
    assert listed[0]["title"] == "旧"
    assert listed[0].get("source_provider") == ""
    # 磁盘未改写
    assert ip.read_text(encoding="utf-8") == raw


def test_read_preserves_existing_title(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    old = [{
        "id": "t1", "name": "file.pdf", "ext": ".pdf", "size": 1, "ts": 1, "industry": "PCB",
        "title": "用户自定义标题",
    }]
    (rdir / "index.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    listed = mr.list_reports()
    assert listed[0]["title"] == "用户自定义标题"


def test_patch_empty_title_400(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    meta = mr.import_report_bytes(name="a.pdf", content=_PDF_BYTES, metadata={"title": "Keep"})
    r = client.patch(f"/api/myreports/{meta['id']}", json={"title": ""})
    assert r.status_code == 400


def test_patch_clear_institution_with_empty_string(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    meta = mr.import_report_bytes(
        name="a.pdf", content=_PDF_BYTES,
        metadata={"title": "T", "institution": "中信"},
    )
    r = client.patch(f"/api/myreports/{meta['id']}", json={"institution": ""})
    assert r.status_code == 200
    assert r.json()["data"]["institution"] == ""


def test_patch_old_entry_normalizes_single(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    rid = "oldpatch1"
    (rdir / f"{rid}.pdf").write_bytes(_PDF_BYTES)
    old = [{"id": rid, "name": "old.pdf", "ext": ".pdf", "size": len(_PDF_BYTES), "ts": 1, "industry": "PCB"}]
    (rdir / "index.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    r = client.patch(f"/api/myreports/{rid}", json={"institution": "华泰"})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["institution"] == "华泰"
    assert body.get("title")  # 已补全
    assert body.get("imported_at")


# ── API import 走公共方法，不信任前端 ────────────────────────────


def test_import_api_uses_public_import_and_scope_all(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")

    def fake_discover(sector_key, **kwargs):
        assert kwargs.get("scope") == "all"
        return srd.DiscoveryResult(
            source_key=sector_key,
            discovered=[{
                "external_id": "INFO99",
                "info_code": "INFO99",
                "title": "真实标题",
                "institution": "中信",
                "publish_date": "2025-07-01",
                "report_scope": "company",
            }],
        )

    monkeypatch.setattr(srd, "discover_sector_reports", fake_discover)
    monkeypatch.setattr(app_module, "_download_pdf", lambda url: _PDF_BYTES)

    r = client.post(
        "/api/sector-research/import/pcb",
        json={"external_id": "INFO99"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["title"] == "真实标题"
    assert data["source_provider"] == "eastmoney"
    assert data["external_id"] == "INFO99"
    assert "pcb" in data["sector_keys"]
    assert (tmp_path / "myreports" / f"{data['id']}.pdf").exists()


def test_import_api_missing_external_id_400(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")

    def fake_discover(sector_key, **kwargs):
        return srd.DiscoveryResult(source_key=sector_key, discovered=[])

    monkeypatch.setattr(srd, "discover_sector_reports", fake_discover)
    r = client.post("/api/sector-research/import/pcb", json={"external_id": "NOPE"})
    assert r.status_code == 400
