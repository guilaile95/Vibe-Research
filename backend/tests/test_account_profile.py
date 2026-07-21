"""account_profile 数据层离线测试（存储 + 校验，不联网、不改 portfolio.json）。"""
from __future__ import annotations

import json
import os

import pytest

import account_profile


def _delete_file() -> None:
    try:
        os.remove(account_profile.ACCOUNT_FILE)
    except FileNotFoundError:
        pass


def test_unconfigured_returns_none():
    """文件不存在 → None（未配置，不是 0）。"""
    _delete_file()
    assert account_profile.load_account_profile() is None


def test_save_and_load_round_trip():
    """正常保存 → 读取一致，含 updated_at。"""
    _delete_file()
    saved = account_profile.save_account_profile(100000, 20000)
    assert saved["total_assets"] == 100000.0
    assert saved["available_cash"] == 20000.0
    assert isinstance(saved["updated_at"], str)
    assert "202" in saved["updated_at"]  # 年份合理（防 _now 未实现）

    loaded = account_profile.load_account_profile()
    assert loaded is not None
    assert loaded["total_assets"] == 100000.0
    assert loaded["available_cash"] == 20000.0
    assert loaded["updated_at"] == saved["updated_at"]


def test_available_cash_zero_is_valid():
    """available_cash=0 合法。"""
    _delete_file()
    saved = account_profile.save_account_profile(50000, 0)
    assert saved["available_cash"] == 0.0
    assert account_profile.load_account_profile()["available_cash"] == 0.0


def test_save_does_not_modify_portfolio():
    """保存账户资金不改 portfolio.json（文件路径隔离）。"""
    _delete_file()
    portfolio_file = os.path.join(account_profile.CACHE_DIR, "portfolio.json")
    # 写入一个标记文件，确认后续不被覆盖
    os.makedirs(account_profile.CACHE_DIR, exist_ok=True)
    sentinel = {"holdings": [], "last_refresh": "sentinel"}
    with open(portfolio_file, "w", encoding="utf-8") as f:
        json.dump(sentinel, f)

    account_profile.save_account_profile(100000, 20000)

    with open(portfolio_file, encoding="utf-8") as f:
        after = json.load(f)
    assert after == sentinel


# ---- 校验 ----

def test_validate_normal():
    """正常值通过校验。"""
    total, cash = account_profile.validate_account_payload({
        "total_assets": 100000, "available_cash": 20000,
    })
    assert total == 100000.0
    assert cash == 20000.0


def test_validate_total_assets_le_zero_rejected():
    """total_assets<=0 拒绝。"""
    with pytest.raises(ValueError, match="大于 0"):
        account_profile.validate_account_payload({"total_assets": 0, "available_cash": 0})
    with pytest.raises(ValueError, match="大于 0"):
        account_profile.validate_account_payload({"total_assets": -100, "available_cash": 0})


def test_validate_available_cash_negative_rejected():
    """available_cash<0 拒绝。"""
    with pytest.raises(ValueError, match="不能小于 0"):
        account_profile.validate_account_payload({"total_assets": 100000, "available_cash": -1})


def test_validate_cash_exceeds_total_rejected():
    """available_cash>total_assets 拒绝。"""
    with pytest.raises(ValueError, match="不能大于账户总资产"):
        account_profile.validate_account_payload({
            "total_assets": 100000, "available_cash": 100001,
        })


def test_validate_nan_rejected():
    """NaN 拒绝。"""
    with pytest.raises(ValueError, match="NaN"):
        account_profile.validate_account_payload({
            "total_assets": float("nan"), "available_cash": 0,
        })
    with pytest.raises(ValueError, match="NaN"):
        account_profile.validate_account_payload({
            "total_assets": 100000, "available_cash": float("nan"),
        })


def test_validate_infinity_rejected():
    """Infinity 拒绝。"""
    with pytest.raises(ValueError, match="Infinity"):
        account_profile.validate_account_payload({
            "total_assets": float("inf"), "available_cash": 0,
        })


def test_validate_string_rejected():
    """字符串拒绝。"""
    with pytest.raises(ValueError, match="数字"):
        account_profile.validate_account_payload({
            "total_assets": "100000", "available_cash": 20000,
        })


def test_validate_bool_rejected():
    """布尔值拒绝（bool 是 int 子类，必须先拒）。"""
    with pytest.raises(ValueError, match="布尔值"):
        account_profile.validate_account_payload({
            "total_assets": True, "available_cash": 20000,
        })
    with pytest.raises(ValueError, match="布尔值"):
        account_profile.validate_account_payload({
            "total_assets": 100000, "available_cash": False,
        })


def test_validate_unknown_field_rejected():
    """未知字段拒绝。"""
    with pytest.raises(ValueError, match="未知字段"):
        account_profile.validate_account_payload({
            "total_assets": 100000, "available_cash": 20000, "extra": 1,
        })


def test_validate_updated_at_rejected():
    """客户端提交 updated_at 拒绝。"""
    with pytest.raises(ValueError, match="updated_at"):
        account_profile.validate_account_payload({
            "total_assets": 100000, "available_cash": 20000,
            "updated_at": "2026-01-01 00:00:00",
        })


def test_validate_rounds_to_two_decimals():
    """金额保留两位小数。"""
    _delete_file()
    saved = account_profile.save_account_profile(100000.999, 20000.555)
    assert saved["total_assets"] == 100001.0  # round(100000.999, 2) == 100001.0
    assert saved["available_cash"] == 20000.56  # round(20000.555, 2) == 20000.56


def test_validate_cash_equals_total_accepted():
    """available_cash == total_assets 合法（全仓现金 == 总资产极端情形）。"""
    total, cash = account_profile.validate_account_payload({
        "total_assets": 100000, "available_cash": 100000,
    })
    assert total == 100000.0
    assert cash == 100000.0


def test_os_replace_failure_cleans_tmp():
    """os.replace 失败时：旧文件不变、不残留临时文件。"""
    _delete_file()
    account_profile.save_account_profile(99999, 33333)
    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        good_bytes = f.read()

    def fail_replace(src, dst):
        raise OSError("simulated replace failure")

    import unittest.mock as mock
    with mock.patch("account_profile.os.replace", side_effect=fail_replace):
        try:
            account_profile.save_account_profile(111, 22)
        except OSError:
            pass

    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        after = f.read()
    assert after == good_bytes

    dir_files = os.listdir(account_profile.CACHE_DIR)
    acc_files = [f for f in dir_files if f.startswith("account_profile")]
    assert len(acc_files) == 1, f"残留临时文件: {acc_files}"


def test_success_no_tmp_residue():
    """成功写入后不残留临时文件。"""
    _delete_file()
    account_profile.save_account_profile(50000, 10000)
    dir_files = os.listdir(account_profile.CACHE_DIR)
    acc_files = [f for f in dir_files if f.startswith("account_profile")]
    assert len(acc_files) == 1
    assert acc_files[0] == "account_profile.json"


def test_concurrent_write_valid():
    """并发写入后最终文件是完整合法 JSON。"""
    _delete_file()
    import threading

    n = 30
    barrier = threading.Barrier(n)
    errors = []

    def _put(total):
        barrier.wait(timeout=5)
        try:
            account_profile.save_account_profile(total, total // 10)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_put, args=(100000 + i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"并发写入错误: {errors}"
    import json
    with open(account_profile.ACCOUNT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    assert "total_assets" in data
    assert "available_cash" in data
    assert "updated_at" in data
    assert isinstance(data["total_assets"], (int, float))
    assert data["total_assets"] >= 100000

    dir_files = os.listdir(account_profile.CACHE_DIR)
    acc_files = [f for f in dir_files if f.startswith("account_profile")]
    assert len(acc_files) == 1, f"残留临时文件: {acc_files}"


def test_tmp_write_failure_no_residue():
    """临时文件写入失败（json.dump 抛出 OSError）：原文件不变、不残留临时文件。"""
    _delete_file()
    account_profile.save_account_profile(99999, 33333)
    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        good_bytes = f.read()

    import unittest.mock as mock

    def fail_dump(*args, **kwargs):
        raise OSError("simulated write failure")

    with mock.patch("account_profile.json.dump", side_effect=fail_dump):
        try:
            account_profile.save_account_profile(111, 22)
        except OSError:
            pass

    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        assert f.read() == good_bytes

    dir_files = os.listdir(account_profile.CACHE_DIR)
    acc_files = [f for f in dir_files if f.startswith("account_profile")]
    assert len(acc_files) == 1, f"残留临时文件: {acc_files}"


def test_keyboard_interrupt_not_caught():
    """KeyboardInterrupt 不被捕获为业务异常，临时文件仍被清理。"""
    _delete_file()
    account_profile.save_account_profile(99999, 33333)
    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        good_bytes = f.read()

    import unittest.mock as mock

    with mock.patch("account_profile.os.replace", side_effect=KeyboardInterrupt()):
        with pytest.raises(KeyboardInterrupt):
            account_profile.save_account_profile(111, 22)

    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        assert f.read() == good_bytes

    dir_files = os.listdir(account_profile.CACHE_DIR)
    acc_files = [f for f in dir_files if f.startswith("account_profile")]
    assert len(acc_files) == 1, f"残留临时文件: {acc_files}"


def test_system_exit_not_caught():
    """SystemExit 不被捕获为业务异常，临时文件仍被清理。"""
    _delete_file()
    account_profile.save_account_profile(99999, 33333)
    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        good_bytes = f.read()

    import unittest.mock as mock

    with mock.patch("account_profile.os.replace", side_effect=SystemExit(1)):
        with pytest.raises(SystemExit):
            account_profile.save_account_profile(111, 22)

    with open(account_profile.ACCOUNT_FILE, "rb") as f:
        assert f.read() == good_bytes

    dir_files = os.listdir(account_profile.CACHE_DIR)
    acc_files = [f for f in dir_files if f.startswith("account_profile")]
    assert len(acc_files) == 1, f"残留临时文件: {acc_files}"
