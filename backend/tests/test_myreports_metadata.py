"""myreports 统一研档档案：丰富元数据 / 迁移 / 去重 / 浏览 / 检索 / PATCH 元数据回归测。

全部离线、用临时目录，不触碰真实用户数据（~/.vibe-research/myreports）。
覆盖后端新增面：
- 新字段校验（publish_date / sector_keys / source_kind）fail-closed 400
- 旧 index.json 首次启动一次性升级（幂等、原子写、失败不阻塞）
- SHA-256 去重（同内容不写重复文件，返回既有条目 + deduped）
- build_browse 按 year / industry / institution 分组（含 未确认机构 分桶、sector_key 过滤）
- search_reports 全文检索
- PATCH 元数据（部分更新、未知字段拒绝、不存在 404）
- PCB 独立成类（不再折进 AI算力）
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import myreports as mr


client = TestClient(app_module.app)

_B64 = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 meta-test").decode()
_B64_ALT = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 another-pdf").decode()


def _upload(temp_dir: Path, name: str, b64: str = _B64, **meta) -> dict:
    """上传一份研报到临时目录，返回元数据。"""
    return client.post("/api/myreports", json={"name": name, "content_b64": b64, **meta}).json()["data"]


# ── 新字段校验（fail-closed 400） ─────────────────────────────


def test_publish_date_invalid_formats_400(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    for bad in ["2025-13-01", "2025-00-10", "2025-07-32", "2025/07/23", "2025-1-1", "abc", "20250723"]:
        r = client.post("/api/myreports", json={"name": "a.pdf", "content_b64": _B64, "publish_date": bad})
        assert r.status_code == 400, f"{bad!r} 应被拒"


def test_publish_date_valid_formats_200(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    for good in ["2025-07-23", "2025-07", "2025"]:
        r = client.post("/api/myreports", json={"name": "a.pdf", "content_b64": _B64, "publish_date": good})
        assert r.status_code == 200, f"{good!r} 应通过"


def test_source_kind_whitelist_400(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    r = client.post("/api/myreports", json={"name": "a.pdf", "content_b64": _B64, "source_kind": "blockchain"})
    assert r.status_code == 400


def test_source_kind_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    r = client.post("/api/myreports", json={"name": "a.pdf", "content_b64": _B64, "source_kind": "whitepaper"})
    assert r.status_code == 200
    assert r.json()["data"]["source_kind"] == "whitepaper"


def test_sector_keys_must_be_string_list(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    # 123 非字符串，Pydantic list[str] 校验失败 → 422
    r = client.post("/api/myreports", json={"name": "a.pdf", "content_b64": _B64, "sector_keys": ["pcb", 123]})
    assert r.status_code == 422


# ── 旧 index.json 一次性升级（幂等、失败不阻塞） ────────────────


def test_migrate_old_index_adds_new_fields(tmp_path, monkeypatch):
    """旧格式条目（缺imported_at）首次启动应被就地补全为新schema。"""
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    old_entry = {
        "id": "legacy001", "name": "旧研报.pdf", "ext": ".pdf",
        "size": 1234, "ts": 1700000000000, "industry": "半导体",
    }
    (rdir / "index.json").write_text(json.dumps([old_entry], ensure_ascii=False), encoding="utf-8")
    # 实体文件存在时 SHA-256 应被补全
    (rdir / "legacy001.pdf").write_bytes(b"legacy-bytes")

    # 幂等：直接调用迁移；应补全 imported_at / file_sha256 / 新字段，且不抛错
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    mr._migrate_index()
    items = mr._load_index()
    assert len(items) == 1
    e = items[0]
    assert e["imported_at"]  # 已派生归档日期
    assert e["file_sha256"]  # 已算 SHA-256
    assert e["title"] == "旧研报"
    assert e["institution"] == ""
    assert e["publish_date"] == ""
    assert e["sector_keys"] == []

    # 二次迁移：已升级条目不重复处理（幂等）
    mr._migrate_index()
    assert mr._load_index()[0]["id"] == "legacy001"


def test_migrate_index_failure_does_not_block(tmp_path, monkeypatch, capsys):
    """迁移抛错时只告警、不阻塞启动。"""
    rdir = tmp_path / "myreports"
    rdir.mkdir()
    (rdir / "index.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(mr, "REPORTS_DIR", rdir)
    # 不抛错；应打印告警到 stderr
    mr._migrate_index()
    err = capsys.readouterr().err
    assert "迁移失败" in err


# ── SHA-256 去重 ───────────────────────────────────────────────


def test_dedup_same_content_returns_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    first = _upload(tmp_path, "研报v1.pdf")
    second = _upload(tmp_path, "研报v2-不同文件名.pdf")  # 同名内容不同名
    assert second["id"] == first["id"]
    assert second.get("deduped") is True
    # 不应写两份实体文件
    files = list((tmp_path / "myreports").glob("*.pdf"))
    assert len(files) == 1


def test_dedup_distinct_content_writes_new(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    first = _upload(tmp_path, "a.pdf", b64=_B64)
    second = _upload(tmp_path, "b.pdf", b64=_B64_ALT)
    assert second["id"] != first["id"]
    assert "deduped" not in second


# ── build_browse 分组浏览 ───────────────────────────────────────


def _seed_items() -> list[dict]:
    """构造一批异构条目供分组 / 检索用。"""
    return [
        {"id": "1", "name": "生益科技PCB覆铜板.pdf", "title": "PCB 高频基材",
         "industry": "PCB", "institution": "中信证券", "publish_date": "2025-07-10",
         "sector_keys": ["pcb", "ai-computing"], "imported_at": "2025-07-12T01:00:00+00:00"},
        {"id": "2", "name": "深南电路.pdf", "title": "载板国产替代",
         "industry": "PCB", "institution": "中信证券", "publish_date": "2025-06-01",
         "sector_keys": ["pcb"], "imported_at": "2025-06-02T01:00:00+00:00"},
        {"id": "3", "name": "英伟达算力.pdf", "title": "AI 服务器",
         "industry": "AI算力", "institution": "高盛", "publish_date": "2024-12-20",
         "sector_keys": ["ai-computing"], "imported_at": "2025-01-02T01:00:00+00:00"},
        {"id": "4", "name": "无名报告.pdf", "title": "某未署名研报",
         "industry": "未分类", "institution": "", "publish_date": "",
         "sector_keys": [], "imported_at": "2025-05-05T01:00:00+00:00"},
    ]


def test_browse_by_year_groups_and_sorts():
    out = mr.build_browse(_seed_items(), "year")
    years = [g["key"] for g in out["groups"]]
    # 2025 三份（id 1、2 有 publish_date；id 4 无 publish_date，回退 imported_at=2025）、2024 一份；按年降序
    assert years == ["2025", "2024"]
    y2025 = next(g for g in out["groups"] if g["key"] == "2025")
    assert y2025["count"] == 3
    months = [m["key"] for m in y2025["months"]]
    assert months == ["2025-07", "2025-06", "2025-05"]  # 月份降序（id 4 回退 imported_at 月）
    assert out["total"] == 4


def test_browse_by_industry_with_unknown_and_sector_keys():
    out = mr.build_browse(_seed_items(), "industry")
    keys = {g["key"]: g for g in out["groups"]}
    assert "PCB" in keys and "AI算力" in keys and "未分类" in keys
    # 未分类 排最末
    assert out["groups"][-1]["key"] == "未分类"
    pcb = keys["PCB"]
    assert pcb["count"] == 2
    assert "pcb" in pcb["sector_keys"] and "ai-computing" in pcb["sector_keys"]


def test_browse_by_institution_unknown_bucket():
    out = mr.build_browse(_seed_items(), "institution")
    keys = {g["key"]: g for g in out["groups"]}
    assert "__unknown__" in keys  # 空机构 → 未确认机构 分桶
    assert keys["__unknown__"]["label"] == "未确认机构"
    assert keys["__unknown__"]["count"] == 1
    # 未确认机构 排最末
    assert out["groups"][-1]["key"] == "__unknown__"
    # 其余按数量降序（中信证券 2 份 > 高盛 1 份）
    assert out["groups"][0]["key"] == "中信证券"


def test_browse_sector_key_filter():
    out = mr.build_browse(_seed_items(), "industry", sector_key="pcb")
    # 过滤后只保留 sector_keys 含 pcb 的条目：id 1、2 → 都归 PCB
    assert out["total"] == 2
    keys = {g["key"]: g for g in out["groups"]}
    assert keys["PCB"]["count"] == 2
    assert "AI算力" not in keys  # id 3 不含 pcb，被过滤


def test_browse_invalid_group_raises():
    with pytest.raises(ValueError):
        mr.build_browse(_seed_items(), "color")


# ── search_reports 全文检索 ─────────────────────────────────────


def test_search_matches_title_institution_sector():
    items = _seed_items()
    assert len(mr.search_reports(items, "中信")) == 2
    assert len(mr.search_reports(items, "生益")) == 1  # 匹配 name
    assert len(mr.search_reports(items, "AI 服务器")) == 1  # 匹配 title
    assert len(mr.search_reports(items, "pcb")) == 2  # 匹配 sector_keys


def test_search_empty_query_returns_empty():
    assert mr.search_reports(_seed_items(), "  ") == []
    assert mr.search_reports(_seed_items(), "") == []


def test_search_no_match():
    assert mr.search_reports(_seed_items(), "不存在的关键词") == []


# ── PATCH 元数据（部分更新、未知字段拒绝、不存在 404） ─────────


def test_patch_meta_partial_update(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    meta = _upload(tmp_path, "可更新.pdf")
    rid = meta["id"]
    r = client.patch(f"/api/myreports/{rid}", json={"institution": "中信证券", "publish_date": "2025-07-10"})
    assert r.status_code == 200
    updated = r.json()["data"]
    assert updated["institution"] == "中信证券"
    assert updated["publish_date"] == "2025-07-10"
    # 未传字段保持原值（原 title 默认取文件名去扩展名）
    assert updated["title"] == "可更新"


def test_patch_meta_unknown_field_422(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    meta = _upload(tmp_path, "不可乱改.pdf")
    # "id" 非 ReportMetaPatch 允许字段，Pydantic extra="forbid" → 422
    r = client.patch(f"/api/myreports/{meta['id']}", json={"id": "hack"})
    assert r.status_code == 422


def test_patch_meta_invalid_publish_date_400(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    meta = _upload(tmp_path, "日期校验.pdf")
    r = client.patch(f"/api/myreports/{meta['id']}", json={"publish_date": "2025-13-45"})
    assert r.status_code == 400


def test_patch_meta_not_found_404(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    r = client.patch("/api/myreports/does-not-exist", json={"institution": "x"})
    assert r.status_code == 404


# ── API：browse / search 路由 ─────────────────────────────────────


def test_api_browse_route(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    _upload(tmp_path, "生益科技PCB覆铜板.pdf", institution="中信证券", sector_keys=["pcb"])
    _upload(tmp_path, "英伟达算力.pdf", b64=_B64_ALT, institution="高盛", sector_keys=["ai-computing"])
    r = client.get("/api/myreports/browse", params={"group": "institution"})
    assert r.status_code == 200
    labels = [g["label"] for g in r.json()["data"]["groups"]]
    assert "中信证券" in labels and "高盛" in labels


def test_api_browse_invalid_group_400(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    r = client.get("/api/myreports/browse", params={"group": "bogus"})
    assert r.status_code == 400


def test_api_search_route(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    _upload(tmp_path, "生益科技PCB覆铜板.pdf", institution="中信证券")
    _upload(tmp_path, "英伟达算力.pdf", institution="高盛")
    r = client.get("/api/myreports/search", params={"q": "中信"})
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1


# ── PCB 独立成类 ─────────────────────────────────────────────────


def test_pcb_classified_independently():
    """PCB 应归独立 PCB 类，而非 AI算力（过去 '沪电' 等关键词会错折）。"""
    assert mr.classify("生益科技PCB覆铜板.pdf") == "PCB"
    assert mr.classify("深南电路_HDI板.pdf") == "PCB"
    assert mr.classify("沪电股份.pdf") == "PCB"
    # 纯算力 / GPU 仍归 AI算力
    assert mr.classify("英伟达算力GPU.pdf") == "AI算力"


# ── update_report_meta 纯函数行为（不走 HTTP） ─────────────────────


def test_update_report_meta_via_function(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "REPORTS_DIR", tmp_path / "myreports")
    meta = _upload(tmp_path, "直接调函数.pdf")
    updated = mr.update_report_meta(meta["id"], {"title": "新标题", "source_kind": "report"})
    assert updated is not None
    assert updated["title"] == "新标题"
    assert updated["source_kind"] == "report"
    # 不允许改的字段
    with pytest.raises(mr.ReportError):
        mr.update_report_meta(meta["id"], {"id": "x", "size": 1})
    # 不存在
    assert mr.update_report_meta("nope", {"title": "x"}) is None
