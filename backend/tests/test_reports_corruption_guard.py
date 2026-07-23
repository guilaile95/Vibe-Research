"""myreports/index.json 损坏保护专项测试。

所有测试使用临时目录，不触碰真实用户数据。
"""

from __future__ import annotations

import json
import os
import pathlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import app
import myreports as mr


_B64_SMALL = "data:text/plain;base64," + __import__("base64").b64encode(b"test report content").decode()
_B64_SMALL2 = "data:text/plain;base64," + __import__("base64").b64encode(b"second report content").decode()


def _make_reports_dir():
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    return tmp, rdir


def _write_corrupt_index(reports_dir, content, is_bytes=False):
    p = os.path.join(reports_dir, "index.json")
    os.makedirs(reports_dir, exist_ok=True)
    if is_bytes:
        with open(p, "wb") as f:
            f.write(content)
    else:
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)


# ============================
# 缺失索引
# ============================


def test_missing_index_returns_empty():
    """目录不存在 -> list_reports 返回 []。"""
    tmp, rdir = _make_reports_dir()
    try:
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            assert mr.list_reports() == []
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_first_upload_success():
    """首次上传成功。"""
    tmp, rdir = _make_reports_dir()
    try:
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            meta = mr.save_report("test.pdf", _B64_SMALL)
            assert meta["name"] == "test.pdf"
            assert len(mr.list_reports()) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_first_upload_no_bak():
    """首次上传不创建 index.json.bak。"""
    tmp, rdir = _make_reports_dir()
    try:
        rpath = Path(rdir)
        with patch.object(mr, "REPORTS_DIR", rpath):
            mr.save_report("a.pdf", _B64_SMALL)
            bak = rpath / "index.json.bak"
            assert not bak.exists()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 损坏识别
# ============================


def test_truncated_json():
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, '{"holdings"')
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_invalid_utf8():
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, b"\xff\xfe\x00", is_bytes=True)
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_top_level_not_list():
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, json.dumps({"key": "val"}))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_entry_not_dict():
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, json.dumps(["not_a_dict"]))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_id_missing():
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, json.dumps([{"ext": ".pdf"}]))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_ext_not_string():
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, json.dumps([{"id": "abc", "ext": 123}]))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 验证待保存索引
# ============================


def test_save_index_validates_new_items():
    """待保存新 items 非法：立即抛 ReportIndexCorruptedError，不动任何文件，无临时文件残留。"""
    tmp, rdir = _make_reports_dir()
    try:
        os.makedirs(rdir, exist_ok=True)
        idx_path = os.path.join(rdir, "index.json")
        bak_path = os.path.join(rdir, "index.json.bak")

        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "old", "ext": ".pdf"}], f)
        with open(bak_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "older", "ext": ".pdf"}], f)

        with open(idx_path, "rb") as f:
            idx_bytes_before = f.read()
        with open(bak_path, "rb") as f:
            bak_bytes_before = f.read()

        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr._save_index([{"invalid": "entry_missing_id_and_ext"}])

        with open(idx_path, "rb") as f:
            assert f.read() == idx_bytes_before, "主索引不应被修改"
        with open(bak_path, "rb") as f:
            assert f.read() == bak_bytes_before, "备份文件不应被修改"

        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
        assert len(tmp_files) == 0, f"不应残留临时文件: {tmp_files}"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 写入 fail-closed
# ============================


@pytest.mark.parametrize("op", [
    lambda: mr.list_reports(),
    lambda: mr.report_path("nonexistent"),
    lambda: mr.save_report("x.pdf", _B64_SMALL),
    lambda: mr.delete_report("nonexistent"),
])
def test_all_ops_fail_closed_on_corrupted(op):
    """损坏索引时：所有操作抛异常，文件不变，无临时文件。"""
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, "{broken")
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                op()
        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
        assert len(tmp_files) == 0
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_upload_fails_on_corrupted_no_orphan():
    """损坏索引时上传：抛异常，不产生新实体文件，索引不变，无临时文件。"""
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, "{broken")
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.save_report("orphan.pdf", _B64_SMALL)
        files = [f for f in os.listdir(rdir) if f != "index.json"]
        assert len(files) == 0, f"不应该创建实体文件: {files}"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 正常备份
# ============================


def test_second_save_creates_bak():
    tmp, rdir = _make_reports_dir()
    try:
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            bak = os.path.join(rdir, "index.json.bak")
            assert not os.path.exists(bak), "首次不应创建 bak"
            # 用不同内容触发第二次真实写入（同内容会被 SHA-256 去重跳过索引写入，不会产生 bak）。
            mr.save_report("b.pdf", _B64_SMALL2)
            assert os.path.exists(bak), "第二次应创建 bak"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_bak_matches_pre_save():
    tmp, rdir = _make_reports_dir()
    try:
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            idx_path = os.path.join(rdir, "index.json")
            with open(idx_path, "rb") as f:
                before = f.read()
            # 用不同内容触发第二次真实写入（同内容会被 SHA-256 去重跳过索引写入，不会产生 bak）。
            mr.save_report("b.pdf", _B64_SMALL2)
            bak_path = os.path.join(rdir, "index.json.bak")
            with open(bak_path, "rb") as f:
                bak = f.read()
            assert bak == before
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_no_tmp_residue_after_save():
    tmp, rdir = _make_reports_dir()
    try:
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            mr.save_report("b.pdf", _B64_SMALL)
        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
        assert len(tmp_files) == 0
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 动态路径测试（重写）
# ============================


def test_bak_path_follows_reports_dir():
    """测试动态派生备份路径：在 isolated_dir 连续上传两份研报，验证文件均生成在 isolated_dir。"""
    import tempfile, shutil
    old_tmp = tempfile.mkdtemp()
    isolated_tmp = tempfile.mkdtemp()
    old_dir = os.path.join(old_tmp, "old_myreports")
    isolated_dir = os.path.join(isolated_tmp, "isolated_myreports")

    try:
        os.makedirs(old_dir, exist_ok=True)
        old_idx = os.path.join(old_dir, "index.json")
        old_bak = os.path.join(old_dir, "index.json.bak")
        with open(old_idx, "w", encoding="utf-8") as f:
            json.dump([{"id": "sentinel_old", "ext": ".pdf"}], f)
        with open(old_bak, "w", encoding="utf-8") as f:
            json.dump([{"id": "sentinel_bak", "ext": ".pdf"}], f)

        with open(old_idx, "rb") as f:
            old_idx_bytes = f.read()
        with open(old_bak, "rb") as f:
            old_bak_bytes = f.read()

        with patch.object(mr, "REPORTS_DIR", Path(isolated_dir)):
            mr.save_report("first.pdf", _B64_SMALL)

            iso_idx = Path(isolated_dir) / "index.json"
            assert iso_idx.exists()
            first_idx_bytes = iso_idx.read_bytes()

            mr.save_report("second.pdf", _B64_SMALL2)

            iso_bak = Path(isolated_dir) / "index.json.bak"
            assert iso_bak.exists()
            assert iso_bak.read_bytes() == first_idx_bytes, ".bak 应等于第二次上传前的索引内容"

            reports = mr.list_reports()
            assert len(reports) == 2
            for r in reports:
                ep = Path(isolated_dir) / f"{r['id']}{r['ext']}"
                assert ep.exists(), f"实体文件应在 isolated_dir: {ep}"

        with open(old_idx, "rb") as f:
            assert f.read() == old_idx_bytes, "old_dir 主索引不得改变"
        with open(old_bak, "rb") as f:
            assert f.read() == old_bak_bytes, "old_dir 备份文件不得改变"

        assert not any(".tmp." in f for f in os.listdir(old_dir))
        assert not any(".tmp." in f for f in os.listdir(isolated_dir))
    finally:
        shutil.rmtree(old_tmp, ignore_errors=True)
        shutil.rmtree(isolated_tmp, ignore_errors=True)


# ============================
# 失败注入
# ============================


def test_save_replace_failure_rolls_back_entity():
    """索引 os.replace 失败时：旧索引不变，新实体被回滚删除。"""
    tmp, rdir = _make_reports_dir()
    try:
        os.makedirs(rdir, exist_ok=True)
        idx = os.path.join(rdir, "index.json")
        with open(idx, "w", encoding="utf-8") as f:
            json.dump([{"id": "old", "ext": ".pdf", "name": "old"}], f)
        with open(idx, "rb") as f:
            idx_bytes_before = f.read()

        import myreports as mr_mod
        with patch.object(mr_mod, "REPORTS_DIR", Path(rdir)):
            real_replace = os.replace
            def fail_replace(src, dst):
                if "index.json" in str(dst) and "bak" not in str(dst) and str(dst).endswith("index.json"):
                    raise OSError("simulated replace failure")
                return real_replace(src, dst)
            with patch.object(mr_mod, "os") as mock_os:
                mock_os.replace = fail_replace
                mock_os.path = os.path
                mock_os.makedirs = os.makedirs
                mock_os.remove = lambda p: os.remove(p) if os.path.exists(p) else None
                mock_os.fsync = lambda fd: None
                mock_os.urandom = os.urandom
                with pytest.raises(OSError):
                    mr_mod.save_report("new.pdf", _B64_SMALL)

        with open(idx, "rb") as f:
            assert f.read() == idx_bytes_before, "旧索引被修改"
        files = [f for f in os.listdir(rdir) if f != "index.json" and not f.endswith(".bak")]
        assert len(files) == 0, f"不应有实体文件: {files}"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_delete_save_failure_keeps_entity():
    """删除时索引保存失败：实体文件仍存在，条目仍在索引中。"""
    tmp, rdir = _make_reports_dir()
    try:
        os.makedirs(rdir, exist_ok=True)
        entity_path = os.path.join(rdir, "test_entity.pdf")
        with open(entity_path, "wb") as f:
            f.write(b"test")
        idx = os.path.join(rdir, "index.json")
        with open(idx, "w", encoding="utf-8") as f:
            json.dump([{"id": "test_entity", "ext": ".pdf"}], f)

        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            real_replace = os.replace
            def fail_replace(src, dst):
                if "index.json" in str(dst) and "bak" not in str(dst) and str(dst).endswith("index.json"):
                    raise OSError("simulated replace failure")
                return real_replace(src, dst)
            with patch.object(mr, "os") as mock_os:
                mock_os.replace = fail_replace
                mock_os.path = os.path
                mock_os.makedirs = os.makedirs
                mock_os.remove = lambda p: os.remove(p) if os.path.exists(p) else None
                mock_os.fsync = lambda fd: None
                mock_os.urandom = os.urandom
                with pytest.raises(OSError):
                    mr.delete_report("test_entity")

        assert os.path.exists(entity_path), "实体文件被删除"
        with open(idx, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["id"] == "test_entity"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_delete_unlink_failure_keeps_ok():
    """模拟实体文件 unlink 失败：索引已更新，函数仍返回 True，实体留在磁盘。"""
    tmp, rdir = _make_reports_dir()
    try:
        os.makedirs(rdir, exist_ok=True)
        target_id = "orphan_target"
        entity_path = os.path.join(rdir, f"{target_id}.pdf")
        with open(entity_path, "wb") as f:
            f.write(b"test pdf content")

        idx = os.path.join(rdir, "index.json")
        initial_data = [{"id": target_id, "ext": ".pdf", "name": "target.pdf"}]
        with open(idx, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        orig_unlink = pathlib.Path.unlink

        def mock_unlink(self, missing_ok=False):
            if f"{target_id}.pdf" in self.name:
                raise OSError("simulated unlink failure")
            return orig_unlink(self, missing_ok=missing_ok)

        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with patch.object(pathlib.Path, "unlink", mock_unlink):
                res = mr.delete_report(target_id)

        assert res is True, "delete_report 应返回 True"

        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            current_reports = mr.list_reports()
            assert not any(r["id"] == target_id for r in current_reports), "新索引中不应包含该条目"

        assert os.path.exists(entity_path), "实体文件因 unlink 失败仍存在，成为孤儿文件"

        bak_path = os.path.join(rdir, "index.json.bak")
        assert os.path.exists(bak_path)
        with open(bak_path, "r", encoding="utf-8") as f:
            bak_data = json.load(f)
        assert bak_data == initial_data, ".bak 应等于删除前的索引"

        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
        assert len(tmp_files) == 0, f"不应残留临时文件: {tmp_files}"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================

def test_upload_keyboard_interrupt_does_not_delete_entity():
    """进程级中断（KeyboardInterrupt）发生在 _save_index 时：不删除已写入的实体文件，旧索引字节不变。"""
    import uuid
    tmp, rdir = _make_reports_dir()
    try:
        os.makedirs(rdir, exist_ok=True)
        idx_path = os.path.join(rdir, "index.json")
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "old_report", "ext": ".pdf", "name": "old.pdf"}], f)
        with open(idx_path, "rb") as f:
            idx_bytes_before = f.read()

        fixed_hex = "fixed_uuid_1234"
        mock_uuid = type("MockUUID", (), {"hex": fixed_hex})

        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with patch.object(uuid, "uuid4", lambda: mock_uuid):
                with patch.object(mr, "_save_index", side_effect=KeyboardInterrupt()):
                    with pytest.raises(KeyboardInterrupt):
                        mr.save_report("new.pdf", _B64_SMALL)

        entity_path = Path(rdir) / f"{fixed_hex}.pdf"
        assert entity_path.exists(), "进程级中断时实体文件不应被删除"
        assert entity_path.read_bytes() == b"test report content", "实体文件内容应保持写入值"

        with open(idx_path, "rb") as f:
            assert f.read() == idx_bytes_before, "旧主索引字节不变"

        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
        assert len(tmp_files) == 0, f"不应残留临时文件: {tmp_files}"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# API 损坏契约测试
# ============================


def test_api_reports_corrupted_returns_http_500():
    """研报索引损坏时，GET / POST / GET file / DELETE 接口均返回 HTTP 500 + 固定安全文案。"""
    tmp, rdir = _make_reports_dir()
    try:
        _write_corrupt_index(rdir, "{broken_index_json")
        client = TestClient(app)

        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            # 1. GET /api/myreports
            res_get = client.get("/api/myreports")
            assert res_get.status_code == 500
            detail_get = res_get.json()["detail"]

            # 2. POST /api/myreports
            res_post = client.post("/api/myreports", json={"name": "test.pdf", "content_b64": _B64_SMALL})
            assert res_post.status_code == 500
            detail_post = res_post.json()["detail"]

            # 3. GET /api/myreports/file/{rid}
            res_file = client.get("/api/myreports/file/some_rid")
            assert res_file.status_code == 500
            detail_file = res_file.json()["detail"]

            # 4. DELETE /api/myreports/{rid}
            res_del = client.delete("/api/myreports/some_rid")
            assert res_del.status_code == 500
            detail_del = res_del.json()["detail"]

            # 文案校验
            for detail in [detail_get, detail_post, detail_file, detail_del]:
                assert "研报索引文件损坏" in detail
                assert "停止读写" in detail
                assert "index.json.bak" in detail

                # 负向断言：不得包含敏感信息
                assert str(rdir) not in detail, "不得暴露绝对路径"
                assert "broken_index_json" not in detail, "不得暴露原始索引内容"
                assert "Traceback" not in detail, "不得包含 Traceback"
                assert "ReportIndexCorruptedError" not in detail, "不得暴露异常类名"

            # POST 失败后的额外断言：不生成实体文件、不改动主索引、无临时文件
            files = os.listdir(rdir)
            assert files == ["index.json"], f"POST 失败后不应产生新文件: {files}"
            with open(os.path.join(rdir, "index.json"), "r", encoding="utf-8") as f:
                assert f.read() == "{broken_index_json", "损坏主索引不得被修改"

            # 确认 DELETE 与文件读取没有误返回 200 ok=false 或 404
            assert res_file.status_code != 404
            assert res_del.status_code != 200
            assert res_del.status_code != 404
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)
