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
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
    industry_raw = [
        {"title": "PCB 行业", "infoCode": "A", "industryName": "电子", "publishDate": recent},
        {"title": "覆铜板材料研究", "infoCode": "B", "industryName": "电子", "publishDate": recent},
        {"title": "无关钢铁", "infoCode": "Z", "industryName": "钢铁", "publishDate": recent},
    ]
    company_raw = {
        "002463": [
            {"title": "沪电深度", "infoCode": "A", "stockCode": "002463", "publishDate": recent},
            {"title": "沪电跟踪", "infoCode": "C", "stockCode": "002463", "publishDate": recent},
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

    ind = srd.discover_sector_reports("pcb", scope="industry", days=90, max_pages=1)
    assert ind.error is None
    # 行业 scope 关键词过滤：A/B 命中 PCB/覆铜板，Z 被滤掉
    assert {x["external_id"] for x in ind.discovered} == {"A", "B"}

    co = srd.discover_sector_reports("pcb", scope="company", days=90, max_pages=1)
    assert {x["external_id"] for x in co.discovered} == {"A", "C"}

    all_r = srd.discover_sector_reports("pcb", scope="all", days=90, max_pages=1)
    ids = [x["external_id"] for x in all_r.discovered]
    assert set(ids) == {"A", "B", "C"}
    assert len(ids) == 3  # external_id 去重


def test_sort_stable_score_date_id(monkeypatch):
    from datetime import datetime, timezone, timedelta
    d1 = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
    d0 = (datetime.now(timezone.utc).date() - timedelta(days=20)).isoformat()
    raw = [
        {"title": "PCB 低相关", "infoCode": "Z", "industryName": "电子", "publishDate": d1},
        {"title": "PCB 高速覆铜板", "infoCode": "M", "industryName": "电子", "publishDate": d0},
        {"title": "PCB 高速覆铜板", "infoCode": "A", "industryName": "电子", "publishDate": d0},
    ]
    monkeypatch.setattr(
        srd.astock, "eastmoney_industry_reports",
        lambda **kw: list(raw),
    )
    res = srd.discover_sector_reports("pcb", scope="industry", days=90, max_pages=1)
    ids = [x["external_id"] for x in res.discovered]
    assert ids[:2] == ["A", "M"]
    assert ids[-1] == "Z"


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


def _seed_discovery_cache(sector_key: str, rows: list[dict], monkeypatch) -> None:
    """通过 discover API 写入缓存（mock 数据源）。"""
    def fake_discover(sk, **kwargs):
        return srd.DiscoveryResult(source_key=sk, discovered=list(rows))
    monkeypatch.setattr(srd, "discover_sector_reports", fake_discover)
    r = client.get(f"/api/sector-research/reports/{sector_key}", params={"days": 30, "max_pages": 1})
    assert r.status_code == 200


def test_import_api_uses_public_import_via_cache(tmp_path, monkeypatch):
    """发现写入缓存后，import 用缓存身份归档（不静默重发现）。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    _seed_discovery_cache("pcb", [{
        "external_id": "INFO99",
        "info_code": "INFO99",
        "title": "真实标题",
        "institution": "中信",
        "publish_date": "2025-07-01",
        "report_scope": "company",
        "source_provider": "eastmoney",
    }], monkeypatch)
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
    app_module._clear_discovery_cache()
    r = client.post("/api/sector-research/import/pcb", json={"external_id": "NOPE"})
    assert r.status_code == 400
    assert "过期" in r.json()["detail"] or "重新" in r.json()["detail"]


# ── 追加：import 契约 / imported_at / browse / PDF 魔数 / 动态数据 ──


def test_import_api_extra_info_code_forbidden_422(tmp_path, monkeypatch):
    """POST import 带多余 info_code → extra=forbid → 422。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    r = client.post(
        "/api/sector-research/import/pcb",
        json={"external_id": "INFO99", "info_code": "INFO99"},
    )
    assert r.status_code == 422


def test_import_api_external_id_missing_from_discovery_400(tmp_path, monkeypatch):
    """缓存中无该 external_id → 400（提示重新发现）。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    _seed_discovery_cache("pcb", [{
        "external_id": "OTHER",
        "info_code": "OTHER",
        "title": "其他",
    }], monkeypatch)
    r = client.post("/api/sector-research/import/pcb", json={"external_id": "NOPE"})
    assert r.status_code == 400


def test_import_api_matched_without_info_code_400(tmp_path, monkeypatch):
    """缓存记录有 external_id 但 info_code 为空 → 400。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    _seed_discovery_cache("pcb", [{
        "external_id": "INFO_NO_CODE",
        "info_code": None,
        "title": "缺 info_code",
    }], monkeypatch)
    r = client.post(
        "/api/sector-research/import/pcb",
        json={"external_id": "INFO_NO_CODE"},
    )
    assert r.status_code == 400


def test_import_api_uses_matched_info_code_for_pdf(tmp_path, monkeypatch):
    """import 仅用缓存中的 info_code 生成 PDF URL（不信任前端）。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    seen_urls: list[str] = []
    _seed_discovery_cache("pcb", [{
        "external_id": "IC_MATCH_42",
        "info_code": "IC_MATCH_42",
        "title": "用 info_code 下载",
        "institution": "中信",
        "publish_date": "2025-07-01",
        "report_scope": "company",
    }], monkeypatch)

    def capture_download(url, *a, **k):
        seen_urls.append(url)
        return _PDF_BYTES

    monkeypatch.setattr(app_module, "_download_pdf", capture_download)

    r = client.post(
        "/api/sector-research/import/pcb",
        json={"external_id": "IC_MATCH_42"},
    )
    assert r.status_code == 200
    assert seen_urls, "应调用 _download_pdf"
    assert "IC_MATCH_42" in seen_urls[0]
    assert seen_urls[0].startswith("https://pdf.dfcfw.com/")


def test_list_reports_missing_ts_imported_at_empty(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    old = [{"id": "no_ts", "name": "a.pdf", "ext": ".pdf", "size": 1, "industry": "PCB"}]
    (rdir / "index.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    listed = mr.list_reports()
    assert listed[0]["imported_at"] == ""


def test_list_reports_ts_zero_imported_at_empty(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    old = [{"id": "ts0", "name": "a.pdf", "ext": ".pdf", "size": 1, "ts": 0, "industry": "PCB"}]
    (rdir / "index.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    listed = mr.list_reports()
    assert listed[0]["imported_at"] == ""


def test_list_reports_invalid_huge_ts_imported_at_empty(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    # 远超合理 epoch 范围，触发 OverflowError/OSError → 空串
    old = [{
        "id": "huge_ts", "name": "a.pdf", "ext": ".pdf", "size": 1,
        "ts": 10**20, "industry": "PCB",
    }]
    (rdir / "index.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    listed = mr.list_reports()
    assert listed[0]["imported_at"] == ""


def test_read_twice_does_not_change_index_content_hash(tmp_path, monkeypatch):
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    old = [{"id": "h1", "name": "旧.pdf", "ext": ".pdf", "size": 1, "ts": 1700000000000, "industry": "PCB"}]
    ip = rdir / "index.json"
    raw = json.dumps(old, ensure_ascii=False)
    ip.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)

    def _hash() -> str:
        return hashlib.sha256(ip.read_bytes()).hexdigest()

    h0 = _hash()
    mr.list_reports()
    h1 = _hash()
    mr.list_reports()
    h2 = _hash()
    assert h0 == h1 == h2
    assert ip.read_text(encoding="utf-8") == raw


def test_build_browse_year_no_dates_group_key_unconfirmed():
    items = [{
        "id": "nd1", "name": "无日期.pdf", "title": "无日期",
        "industry": "PCB", "institution": "中信",
        "publish_date": "", "imported_at": "", "sector_keys": ["pcb"],
    }]
    out = mr.build_browse(items, "year")
    assert out["total"] == 1
    assert out["groups"][0]["key"] == "日期未确认"
    assert out["groups"][0]["count"] == 1


def test_import_report_bytes_rejects_non_pdf_magic_with_pdf_ext(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    with pytest.raises(mr.ReportError, match="%PDF|魔术"):
        mr.import_report_bytes(
            name="fake.pdf",
            content=_HTML_BYTES,
            metadata={"title": "假 PDF"},
        )


def test_get_sector_dynamic_data_keys_and_partial_status(monkeypatch):
    """返回合同字段；单家失败 → partial/unavailable。"""
    # 全部成功
    monkeypatch.setattr(srd.astock, "individual_info", lambda code: {"股票简称": f"名{code}"})
    monkeypatch.setattr(srd.astock, "profit_forecast", lambda code: {"code": code})
    monkeypatch.setattr(srd.astock, "announcements", lambda code, limit=10: [])
    ok = srd.get_sector_dynamic_data("pcb")
    for key in ("source", "fetched_at", "status", "warnings"):
        assert key in ok
    assert ok["source"] == "a-stock-data"
    assert ok["status"] == "normal"
    assert isinstance(ok["warnings"], list)
    assert ok["fetched_at"]
    for company in ok["companies"]:
        for panel in company["panels"].values():
            assert set(panel) == {"status", "summary", "error"}
            assert "data" not in panel

    # 部分失败 → partial
    def boom_info(code):
        if code == "002463":
            raise RuntimeError("upstream down")
        return {"股票简称": f"名{code}"}

    monkeypatch.setattr(srd.astock, "individual_info", boom_info)
    partial = srd.get_sector_dynamic_data("pcb")
    assert partial["status"] == "partial"
    assert partial["warnings"]

    # 全部失败 → unavailable
    monkeypatch.setattr(
        srd.astock, "individual_info",
        lambda code: (_ for _ in ()).throw(RuntimeError("all down")),
    )
    monkeypatch.setattr(
        srd.astock, "profit_forecast",
        lambda code: (_ for _ in ()).throw(RuntimeError("all down")),
    )
    monkeypatch.setattr(
        srd.astock, "announcements",
        lambda code, limit=10: (_ for _ in ()).throw(RuntimeError("all down")),
    )
    bad = srd.get_sector_dynamic_data("pcb")
    assert bad["status"] == "unavailable"
    for key in ("source", "fetched_at", "status", "warnings"):
        assert key in bad


# ── 发现缓存：自定义 days / 过期 / 隔离 / 容量 ──────────────────


def test_discovery_cache_custom_days_then_import(tmp_path, monkeypatch):
    """days=1000 发现的旧研报写入缓存后可立即导入。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    seen_days: list = []

    def fake_discover(sector_key, **kwargs):
        seen_days.append(kwargs.get("days"))
        return srd.DiscoveryResult(
            source_key=sector_key,
            discovered=[{
                "external_id": "OLD1000",
                "info_code": "OLD1000",
                "title": "超一年研报",
                "institution": "中信",
                "publish_date": "2023-01-01",
                "report_scope": "industry",
                "source_provider": "eastmoney",
            }],
        )

    monkeypatch.setattr(srd, "discover_sector_reports", fake_discover)
    monkeypatch.setattr(app_module, "_download_pdf", lambda url: _PDF_BYTES)

    r = client.get(
        "/api/sector-research/reports/pcb",
        params={"days": 1000, "scope": "industry", "max_pages": 1},
    )
    assert r.status_code == 200
    assert 1000 in seen_days

    r2 = client.post("/api/sector-research/import/pcb", json={"external_id": "OLD1000"})
    assert r2.status_code == 200
    assert r2.json()["data"]["title"] == "超一年研报"
    assert r2.json()["data"]["external_id"] == "OLD1000"


def test_discovery_cache_expired_rejects_import(tmp_path, monkeypatch):
    """缓存过期后拒绝导入并提示重新发现。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    from datetime import timedelta

    _seed_discovery_cache("pcb", [{
        "external_id": "EXP1",
        "info_code": "EXP1",
        "title": "将过期",
    }], monkeypatch)
    with app_module._DISCOVERY_CACHE_LOCK:
        c = app_module._DISCOVERY_CACHE[("pcb", "EXP1")]
        c.discovered_at = c.discovered_at - timedelta(seconds=app_module._DISCOVERY_CACHE_TTL_SECONDS + 10)

    r = client.post("/api/sector-research/import/pcb", json={"external_id": "EXP1"})
    assert r.status_code == 400
    assert "过期" in r.json()["detail"] or "重新" in r.json()["detail"]


def test_discovery_cache_sector_isolation(tmp_path, monkeypatch):
    """不同 sector 不能复用同一 external_id 缓存。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    _seed_discovery_cache("pcb", [{
        "external_id": "SHARED",
        "info_code": "SHARED",
        "title": "PCB only",
    }], monkeypatch)
    r = client.post("/api/sector-research/import/not-a-sector", json={"external_id": "SHARED"})
    assert r.status_code in (400, 404)


def test_discovery_cache_capacity_limit(tmp_path, monkeypatch):
    """缓存有容量上限。"""
    app_module._clear_discovery_cache()
    monkeypatch.setattr(app_module, "_DISCOVERY_CACHE_MAX_ENTRIES", 3)
    rows = [
        {"external_id": f"C{i}", "info_code": f"C{i}", "title": f"t{i}"}
        for i in range(5)
    ]
    app_module._cache_discoveries("pcb", rows)
    with app_module._DISCOVERY_CACHE_LOCK:
        assert len(app_module._DISCOVERY_CACHE) <= 3
    app_module._clear_discovery_cache()


def test_import_does_not_accept_client_title_or_url(tmp_path, monkeypatch):
    """前端不能通过 body 覆盖 title/url/info_code。"""
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    r = client.post(
        "/api/sector-research/import/pcb",
        json={
            "external_id": "X",
            "title": "HACK",
            "source_url": "https://evil.com/x.pdf",
        },
    )
    assert r.status_code == 422


# ── 发现截断 / days 过滤 / profit_forecast list / panel data=null ──


def test_company_scope_applies_days_filter(monkeypatch):
    """company scope 按 publish_date + days 过滤；缺失日期保留并 date_unknown。"""
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    old = (today - timedelta(days=400)).isoformat()
    recent = (today - timedelta(days=10)).isoformat()

    def fake_company(code, max_pages=3):
        return [
            {"title": "旧报", "infoCode": "OLD", "stockCode": code, "publishDate": old},
            {"title": "新报 PCB", "infoCode": "NEW", "stockCode": code, "publishDate": recent},
            {"title": "无日期 PCB", "infoCode": "NODATE", "stockCode": code},
        ]

    monkeypatch.setattr(srd.astock, "eastmoney_reports", fake_company)
    res = srd.discover_sector_reports("pcb", scope="company", days=90, max_pages=1)
    ids = {x["external_id"] for x in res.discovered}
    assert "OLD" not in ids
    assert "NEW" in ids
    assert "NODATE" in ids
    nodate = next(x for x in res.discovered if x["external_id"] == "NODATE")
    assert nodate.get("date_unknown") is True


def test_all_scope_company_part_applies_days(monkeypatch):
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    old = (today - timedelta(days=500)).isoformat()
    recent = (today - timedelta(days=5)).isoformat()

    monkeypatch.setattr(
        srd.astock, "eastmoney_industry_reports",
        lambda **kw: [{"title": "PCB 行业", "infoCode": "I1", "industryName": "电子", "publishDate": recent}],
    )
    monkeypatch.setattr(
        srd.astock, "eastmoney_reports",
        lambda code, max_pages=3: [
            {"title": "公司旧", "infoCode": "C_OLD", "stockCode": code, "publishDate": old},
            {"title": "公司新 PCB", "infoCode": "C_NEW", "stockCode": code, "publishDate": recent},
        ],
    )
    res = srd.discover_sector_reports("pcb", scope="all", days=30, max_pages=1)
    ids = {x["external_id"] for x in res.discovered}
    assert "C_OLD" not in ids
    assert "C_NEW" in ids
    assert "I1" in ids


def test_discovery_truncates_to_max_and_caches_all_returned(tmp_path, monkeypatch):
    """557 条场景：返回 <= MAX，返回的每条均可缓存导入。"""
    from datetime import datetime, timezone, timedelta
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    app_module._clear_discovery_cache()
    recent = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
    n = 557
    rows = [
        {
            "title": f"PCB 报告 {i}",
            "infoCode": f"ID{i:04d}",
            "industryName": "电子",
            "publishDate": recent,
            "orgName": "中信",
        }
        for i in range(n)
    ]
    monkeypatch.setattr(srd.astock, "eastmoney_industry_reports", lambda **kw: list(rows))
    monkeypatch.setattr(app_module, "_download_pdf", lambda url: _PDF_BYTES)

    r = client.get("/api/sector-research/reports/pcb", params={"days": 365, "scope": "industry"})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total_discovered"] == n
    assert body["returned"] == srd.MAX_DISCOVERY_RESULTS
    assert body["truncated"] is True
    assert len(body["discovered"]) == body["returned"]
    # 每条返回记录应在缓存中
    for row in body["discovered"]:
        ext = row["external_id"]
        assert app_module._get_cached_discovery("pcb", ext) is not None
    # 被截断的不应在响应中
    returned_ids = {x["external_id"] for x in body["discovered"]}
    assert len(returned_ids) == body["returned"]
    assert f"ID{srd.MAX_DISCOVERY_RESULTS:04d}" not in returned_ids
    # 导入第一条成功
    first = body["discovered"][0]["external_id"]
    imp = client.post("/api/sector-research/import/pcb", json={"external_id": first})
    assert imp.status_code == 200


def test_summarize_profit_forecast_list_shapes():
    assert srd._summarize_profit_forecast([])["note"]
    one = srd._summarize_profit_forecast([
        {"年度": "2026", "均值": "1.23", "预测机构数": "12"},
    ])
    assert one.get("year") == "2026"
    assert one.get("eps") == "1.23" or one.get("forecast") == "1.23"
    assert one.get("coverage") == "12"
    assert one.get("record_count") == 1
    multi = srd._summarize_profit_forecast([
        {"年度": "2025", "均值": "0.9", "预测机构数": "8"},
        {"年度": "2027", "均值": "1.5", "预测机构数": "15"},
    ])
    assert multi.get("year") == "2027"
    # 不得把 len 当机构数
    assert multi.get("coverage") == "15"
    missing = srd._summarize_profit_forecast([{"foo": "bar"}])
    assert "note" in missing or missing.get("record_count") == 1


def test_panel_ok_has_no_data_or_raw_payload():
    panel = srd._panel_ok({"name": "x"})
    assert "data" not in panel
    assert panel["summary"]["name"] == "x"
    assert "股票简称" not in panel
