"""portfolio.json 损坏保护专项测试。

所有测试使用临时目录，不触碰真实用户数据。
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import portfolio as pf


@contextmanager
def _setup(data=None):
    """用测试隔离的临时目录覆盖 CACHE_DIR（不影响真实用户数据）。"""
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"pf-test-{os.urandom(4).hex()}")
    os.makedirs(tmp, exist_ok=True)
    pf_file = os.path.join(tmp, "portfolio.json")
    bak_file = pf_file + ".bak"

    with patch.multiple(pf, CACHE_DIR=tmp, PF_FILE=pf_file, BAK_FILE=bak_file):
        if data is not None:
            with open(pf_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        yield

    for f in (pf_file, bak_file):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass


# ============================
# 缺失文件
# ============================


def test_missing_file_get_portfolio_returns_empty():
    with _setup():
        d = pf.get_portfolio()
        assert d["holdings"] == []
        assert d["data_status"] == "normal"
        assert d["totals"]["market_value"] == 0
        assert d["totals"]["cost"] == 0


def test_missing_file_add_holding_success():
    with _setup():
        d = pf.add_holding("600519", 100, 150.0)
        assert len(d["holdings"]) == 1
        assert d["holdings"][0]["code"] == "600519"


def test_first_save_does_not_create_bak():
    with _setup():
        pf.add_holding("000001", 100, 10.0)
        assert not os.path.exists(pf.BAK_FILE)


def test_missing_file_close_position_success():
    with _setup():
        d = pf.close_position("600519", "2026-01-15", 200.0, 100, 150.0)
        assert len(d["closed"]) == 1


# ============================
# 正常备份
# ============================


def test_normal_save_creates_bak():
    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    with _setup(norm):
        pf.add_holding("000002", 200, 20.0)
        assert os.path.exists(pf.BAK_FILE)


def test_bak_bytes_equal_pre_save():
    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    with _setup(norm):
        with open(pf.PF_FILE, "rb") as f:
            pre = f.read()
        pf.add_holding("000002", 200, 20.0)
        with open(pf.BAK_FILE, "rb") as f:
            bak = f.read()
        assert bak == pre


def test_main_file_equals_new_data():
    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    with _setup(norm):
        pf.add_holding("000002", 200, 20.0)
        with open(pf.PF_FILE, encoding="utf-8") as f:
            after = json.load(f)
        assert len(after["holdings"]) == 2


def test_second_write_updates_bak():
    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    with _setup(norm):
        pf.add_holding("000002", 200, 20.0)
        with open(pf.PF_FILE, "rb") as f:
            pre2 = f.read()
        pf.add_holding("000003", 300, 30.0)
        with open(pf.BAK_FILE, "rb") as f:
            bak2 = f.read()
        assert bak2 == pre2


def test_no_tmp_residue_after_write():
    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    with _setup(norm):
        pf.add_holding("000002", 200, 20.0)
        tmp_files = [f for f in os.listdir(pf.CACHE_DIR) if ".tmp." in f]
        assert len(tmp_files) == 0


# ============================
# 损坏检测
# ============================


def test_truncated_json_raises_corrupted():
    with _setup("{\"holdings\""):
        with pytest.raises(pf.PortfolioDataCorruptedError):
            pf.get_portfolio()


def test_invalid_utf8_raises_corrupted():
    with _setup():
        with open(pf.PF_FILE, "wb") as f:
            f.write(b"\xff\xfe\x00")
        with pytest.raises(pf.PortfolioDataCorruptedError):
            pf.get_portfolio()


def test_top_level_list_raises_corrupted():
    with _setup([]):
        with pytest.raises(pf.PortfolioDataCorruptedError):
            pf.get_portfolio()


def test_holdings_not_list_raises_corrupted():
    with _setup({"holdings": "not-a-list"}):
        with pytest.raises(pf.PortfolioDataCorruptedError):
            pf.get_portfolio()


def test_closed_not_list_raises_corrupted():
    with _setup({"holdings": [], "closed": "not-a-list"}):
        with pytest.raises(pf.PortfolioDataCorruptedError):
            pf.get_portfolio()


# ============================
# 写操作 fail-closed（参数化）
# ============================


@contextmanager
def _corrupted_env():
    """搭建损坏文件环境，返回 (tmp, pf_file, bak_file)，teardown 清理。"""
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"pf-fail-{os.urandom(4).hex()}")
    os.makedirs(tmp, exist_ok=True)
    pf_file = os.path.join(tmp, "portfolio.json")
    bak_file = pf_file + ".bak"

    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    with open(pf_file, "w", encoding="utf-8") as f:
        json.dump(norm, f)
    with open(bak_file, "w", encoding="utf-8") as f:
        json.dump(norm, f)

    with open(pf_file, "w", encoding="utf-8") as f:
        f.write("{\"holdings")  # truncate

    with open(pf_file, "rb") as f:
        corrupted_bytes = f.read()
    with open(bak_file, "rb") as f:
        bak_bytes = f.read()

    yield tmp, pf_file, bak_file, corrupted_bytes, bak_bytes

    for f in (pf_file, bak_file):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
    try:
        os.rmdir(tmp)
    except OSError:
        pass


def _verify_corrupted(tmp, pf_file, bak_file, corrupted_bytes, bak_bytes):
    with open(pf_file, "rb") as f:
        assert f.read() == corrupted_bytes, "主文件被修改"
    with open(bak_file, "rb") as f:
        assert f.read() == bak_bytes, "bak 文件被修改"
    tmp_files = [f for f in os.listdir(tmp) if ".tmp." in f]
    assert len(tmp_files) == 0, f"残留临时文件: {tmp_files}"


@pytest.mark.parametrize("write_op", [
    lambda: pf.add_holding("000002", 100, 10.0),
    lambda: pf.remove_holding("000001"),
    lambda: pf.update_holding("000001", 200, 15.0),
    lambda: pf.close_position("000003", "2026-01-01", 20.0, 100, 10.0),
    lambda: pf.remove_closed(0),
    lambda: pf._refresh_snapshot(),
])
def test_write_ops_fail_closed(write_op):
    with _corrupted_env() as (tmp, pf_file, bak_file, corrupt_bytes, bak_bytes):
        with patch.multiple(pf, CACHE_DIR=tmp, PF_FILE=pf_file, BAK_FILE=bak_file):
            with pytest.raises(pf.PortfolioDataCorruptedError):
                write_op()
        _verify_corrupted(tmp, pf_file, bak_file, corrupt_bytes, bak_bytes)


def test_write_failure_replace_does_not_damage_original():
    """os.replace 失败时：原文件不变，.bak 保留原正常文件，临时文件被清理。"""
    norm = {"holdings": [{"code": "000001", "shares": 100, "cost": 10.0}], "last_refresh": None}
    original_bytes = json.dumps(norm, ensure_ascii=False).encode("utf-8")

    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"pf-writefail-{os.urandom(4).hex()}")
    os.makedirs(tmp, exist_ok=True)
    pf_file = os.path.join(tmp, "portfolio.json")
    bak_file = pf_file + ".bak"

    try:
        with open(pf_file, "wb") as f:
            f.write(original_bytes)

        with patch.multiple(pf, CACHE_DIR=tmp, PF_FILE=pf_file, BAK_FILE=bak_file):
            real_replace = os.replace
            real_makedirs = os.makedirs
            real_remove = os.remove
            real_fsync = os.fsync

            with patch.object(pf, "os") as mock_os:
                def _selective_replace(src, dst):
                    if bak_file == dst:
                        real_replace(src, dst)
                    else:
                        raise OSError("simulated replace failure")

                mock_os.replace = _selective_replace
                mock_os.makedirs = real_makedirs
                mock_os.path = os.path
                mock_os.remove = lambda p: os.remove(p) if os.path.exists(p) else None
                mock_os.fsync = lambda fd: None
                mock_os.urandom = os.urandom

                with pytest.raises(OSError):
                    pf.add_holding("000002", 200, 20.0)

        with open(pf_file, "rb") as f:
            assert f.read() == original_bytes, "原文件被修改"
        with open(bak_file, "rb") as f:
            assert f.read() == original_bytes, "bak 不等于原文件"
        tmp_files = [f for f in os.listdir(tmp) if ".tmp." in f]
        assert len(tmp_files) == 0, f"残留临时文件: {tmp_files}"

    finally:
        for f in (pf_file, bak_file):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
