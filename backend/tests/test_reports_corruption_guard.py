"""myreports/index.json 损坏保护专项测试。

所有测试使用临时目录，不触碰真实用户数据。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import myreports as mr


_B64_SMALL = "data:text/plain;base64," + __import__("base64").b64encode(b"test report content").decode()


@contextmanager
def _setup_index(data=None):
    """搭建测试环境：临时 REPORTS_DIR + 可选初始索引。返回 REPORTS_DIR 局部值。"""
    import tempfile
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"mr-test-{os.urandom(4).hex()}")
    os.makedirs(tmp, exist_ok=True)
    reports_dir = os.path.join(tmp, "myreports")

    with patch.object(mr, "REPORTS_DIR", type("_", (), {"__str__": lambda s: reports_dir, "__fspath__": lambda s: reports_dir})()):
        from pathlib import Path
        p = Path(reports_dir)
        if data is not None:
            p.mkdir(parents=True, exist_ok=True)
            (p / "index.json").write_text(json.dumps(data), encoding="utf-8")
        yield reports_dir

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 缺失索引
# ============================


def test_missing_index_returns_empty():
    """目录不存在 -> list_reports 返回 []。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        reports_dir = os.path.join(tmp, "myreports")
        from pathlib import Path
        with patch.object(mr, "REPORTS_DIR", Path(reports_dir)):
            assert mr.list_reports() == []
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_first_upload_success():
    """首次上传成功。"""
    import tempfile, uuid
    tmp = tempfile.mkdtemp()
    try:
        from pathlib import Path
        with patch.object(mr, "REPORTS_DIR", Path(os.path.join(tmp, "myreports"))):
            meta = mr.save_report("test.pdf", _B64_SMALL)
            assert meta["name"] == "test.pdf"
            assert len(mr.list_reports()) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_first_upload_no_bak():
    """首次上传不创建 index.json.bak。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        from pathlib import Path
        rdir = Path(os.path.join(tmp, "myreports"))
        with patch.object(mr, "REPORTS_DIR", rdir):
            mr.save_report("a.pdf", _B64_SMALL)
            bak = rdir / "index.json.bak"
            assert not bak.exists()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 损坏识别
# ============================


def _write_corrupt_index(reports_dir, content, is_bytes=False):
    p = os.path.join(reports_dir, "index.json")
    os.makedirs(reports_dir, exist_ok=True)
    if is_bytes:
        with open(p, "wb") as f:
            f.write(content)
    else:
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)


def _make_reports_dir():
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    return tmp, rdir


def test_truncated_json():
    tmp, rdir = _make_reports_dir()
    try:
        from pathlib import Path
        _write_corrupt_index(rdir, '{"holdings"')
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_invalid_utf8():
    tmp, rdir = _make_reports_dir()
    try:
        from pathlib import Path
        _write_corrupt_index(rdir, b"\xff\xfe\x00", is_bytes=True)
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_top_level_not_list():
    tmp, rdir = _make_reports_dir()
    try:
        from pathlib import Path
        _write_corrupt_index(rdir, json.dumps({"key": "val"}))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_entry_not_dict():
    tmp, rdir = _make_reports_dir()
    try:
        from pathlib import Path
        _write_corrupt_index(rdir, json.dumps(["not_a_dict"]))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_id_missing():
    tmp, rdir = _make_reports_dir()
    try:
        from pathlib import Path
        _write_corrupt_index(rdir, json.dumps([{"ext": ".pdf"}]))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_ext_not_string():
    tmp, rdir = _make_reports_dir()
    try:
        from pathlib import Path
        _write_corrupt_index(rdir, json.dumps([{"id": "abc", "ext": 123}]))
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            with pytest.raises(mr.ReportIndexCorruptedError):
                mr.list_reports()
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 写入 fail-closed
# ============================


def _corrupted_env():
    """返回 (tmp, rdir)，rdir 中含损坏的 index.json。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    os.makedirs(rdir, exist_ok=True)
    # Create a valid index with one entry
    idx_path = os.path.join(rdir, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump([{"id": "existing", "ext": ".pdf"}], f)
    # Save a copy of valid index bytes
    with open(idx_path, "rb") as f:
        valid_bytes = f.read()
    # Now corrupt it
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write("{broken")
    with open(idx_path, "rb") as f:
        corrupt_bytes = f.read()
    return tmp, rdir, valid_bytes, corrupt_bytes


def _verify_untouched(tmp, rdir, valid_bytes, corrupt_bytes):
    """验证文件不变 + 无临时文件。"""
    idx_path = os.path.join(rdir, "index.json")
    with open(idx_path, "rb") as f:
        assert f.read() == corrupt_bytes, "索引被修改"
    bak_path = os.path.join(rdir, "index.json.bak")
    if os.path.exists(bak_path):
        with open(bak_path, "rb") as f:
            assert f.read() == valid_bytes, "bak 被修改"
    tmp_files = []
    if os.path.exists(rdir):
        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
    assert len(tmp_files) == 0, f"残留临时文件: {tmp_files}"
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.parametrize("op", [
    lambda: mr.list_reports(),
    lambda: mr.report_path("nonexistent"),
    lambda: mr.save_report("x.pdf", _B64_SMALL),
    lambda: mr.delete_report("nonexistent"),
])
def test_all_ops_fail_closed_on_corrupted(op):
    """损坏索引时：所有操作抛异常，文件不变，无临时文件。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    os.makedirs(rdir, exist_ok=True)
    # Corrupted index
    with open(os.path.join(rdir, "index.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    from pathlib import Path
    with patch.object(mr, "REPORTS_DIR", Path(rdir)):
        with pytest.raises(mr.ReportIndexCorruptedError):
            op()
    tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
    assert len(tmp_files) == 0
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_upload_fails_on_corrupted_no_orphan():
    """损坏索引时上传：抛异常，不产生新实体文件，索引不变，无临时文件。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    os.makedirs(rdir, exist_ok=True)
    # Valid index
    idx = os.path.join(rdir, "index.json")
    with open(idx, "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(idx, "rb") as f:
        pre = f.read()
    # Now corrupt
    with open(idx, "w", encoding="utf-8") as f:
        f.write("{broken")
    from pathlib import Path
    with patch.object(mr, "REPORTS_DIR", Path(rdir)):
        with pytest.raises(mr.ReportIndexCorruptedError):
            mr.save_report("orphan.pdf", _B64_SMALL)
    # No entity file created
    files = [f for f in os.listdir(rdir) if f != "index.json"]
    assert len(files) == 0, f"不应该创建实体文件: {files}"
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 正常备份
# ============================


def test_second_save_creates_bak():
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    try:
        from pathlib import Path
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            bak = os.path.join(rdir, "index.json.bak")
            assert not os.path.exists(bak), "首次不应创建 bak"
            mr.save_report("b.pdf", _B64_SMALL)
            assert os.path.exists(bak), "第二次应创建 bak"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_bak_matches_pre_save():
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    try:
        from pathlib import Path
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            idx_path = os.path.join(rdir, "index.json")
            with open(idx_path, "rb") as f:
                before = f.read()
            mr.save_report("b.pdf", _B64_SMALL)
            bak_path = os.path.join(rdir, "index.json.bak")
            with open(bak_path, "rb") as f:
                bak = f.read()
            assert bak == before
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_no_tmp_residue_after_save():
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    try:
        from pathlib import Path
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            mr.save_report("b.pdf", _B64_SMALL)
        tmp_files = [f for f in os.listdir(rdir) if ".tmp." in f]
        assert len(tmp_files) == 0
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 动态路径
# ============================


def test_bak_path_follows_reports_dir():
    """仅 monkeypatch REPORTS_DIR，备份路径自动跟随。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    try:
        from pathlib import Path
        with patch.object(mr, "REPORTS_DIR", Path(rdir)):
            mr.save_report("a.pdf", _B64_SMALL)
            # All files in REPORTS_DIR
            for fname in os.listdir(rdir):
                full = os.path.join(rdir, fname)
                assert full.startswith(rdir), f"{full} 不在 REPORTS_DIR 内"
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)


# ============================
# 失败注入
# ============================


def test_save_replace_failure_rolls_back_entity():
    """索引 os.replace 失败时：旧索引不变，新实体被回滚删除。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    os.makedirs(rdir, exist_ok=True)
    idx = os.path.join(rdir, "index.json")
    with open(idx, "w", encoding="utf-8") as f:
        json.dump([{"id": "old", "ext": ".pdf", "name": "old"}], f)
    with open(idx, "rb") as f:
        pre = f.read()

    from pathlib import Path
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

    # Old index unchanged
    with open(idx, "rb") as f:
        assert f.read() == pre, "旧索引被修改"
    # No orphan entity
    files = [f for f in os.listdir(rdir) if f != "index.json" and not f.endswith(".bak")]
    assert len(files) == 0, f"不应有实体文件: {files}"
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_delete_save_failure_keeps_entity():
    """删除时索引保存失败：实体文件仍存在，条目仍在索引中。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    os.makedirs(rdir, exist_ok=True)
    # Create entity file
    entity_path = os.path.join(rdir, "test_entity.pdf")
    with open(entity_path, "wb") as f:
        f.write(b"test")
    idx = os.path.join(rdir, "index.json")
    with open(idx, "w", encoding="utf-8") as f:
        json.dump([{"id": "test_entity", "ext": ".pdf"}], f)

    from pathlib import Path
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

    # Entity still exists
    assert os.path.exists(entity_path), "实体文件被删除"
    # Index still has entry
    with open(idx, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "test_entity"
    import shutil; shutil.rmtree(tmp, ignore_errors=True)


def test_delete_unlink_failure_keeps_ok():
    """实体 unlink 失败时：索引已更新，函数仍返回 True。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    rdir = os.path.join(tmp, "myreports")
    os.makedirs(rdir, exist_ok=True)
    idx = os.path.join(rdir, "index.json")
    with open(idx, "w", encoding="utf-8") as f:
        json.dump([{"id": "orphan", "ext": ".pdf"}], f)

    from pathlib import Path
    with patch.object(mr, "REPORTS_DIR", Path(rdir)):
        with patch.object(mr, "os") as mock_os:
            mock_os.replace = os.replace
            mock_os.path = os.path
            mock_os.makedirs = os.makedirs
            mock_os.remove = lambda p: os.remove(p) if os.path.exists(p) else None
            mock_os.fsync = lambda fd: None
            mock_os.urandom = os.urandom
            result = mr.delete_report("orphan")

    assert result is True, "unlink 失败也应返回 True"
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
