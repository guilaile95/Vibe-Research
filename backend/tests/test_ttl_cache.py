"""TTLCache 专项单测：覆盖 TTL 过期 / LRU 淘汰 / 容量上限 / 假值缓存 / 并发安全。

时间不依赖真实睡眠：通过 monkeypatch 替换 app 模块的 `time` 命名空间为可控时钟，
TTLCache 内部 `time.time()` 解析到 app.time.time，从而精确控制过期判定。
"""
import threading
from types import SimpleNamespace

import app
from app import TTLCache


class _FakeClock:
    """可控时间源：advance(seconds) 推进时钟，time() 返回当前时间戳。"""

    def __init__(self, start: float = 1_000_000.0):
        self._now = start

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _install_clock(monkeypatch) -> _FakeClock:
    """挂载可控时钟，返回时钟实例供测试按需 advance。"""
    clock = _FakeClock()
    # 只替换 app 模块命名空间里的 `time`，不影响全局 time 模块，避免污染其它代码。
    monkeypatch.setattr(app, "time", SimpleNamespace(time=clock.time))
    return clock


# 1. 写入后可读取
def test_set_then_get_returns_value(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", "v")
    assert cache.get("k", ttl=10) == "v"


# 2. TTL 未过期时命中
def test_get_hit_within_ttl(monkeypatch):
    clock = _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", 42)
    clock.advance(5)  # 仍在 ttl=10 窗口内
    assert cache.get("k", ttl=10) == 42


# 3. TTL 过期后返回 miss
def test_get_miss_after_ttl_expired(monkeypatch):
    clock = _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", "v")
    clock.advance(10)  # time.time() - ts == 10，不满足 < ttl(=10) → 过期
    assert cache.get("k", ttl=10) is None


# 4. 过期项从缓存中删除
def test_expired_entry_evicted_from_data(monkeypatch):
    clock = _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", "v")
    clock.advance(10)
    assert cache.get("k", ttl=10) is None
    assert "k" not in cache._data


# 5. 超过容量后淘汰最久未使用项
def test_lru_eviction_when_over_capacity(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache(max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)  # 触发淘汰 a（最久未使用）
    assert "a" not in cache._data
    assert "b" in cache._data
    assert "c" in cache._data
    assert cache.get("a", ttl=10) is None


# 6. get() 命中后更新 LRU 顺序
def test_get_updates_lru_order(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache(max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a", ttl=10) == 1  # a 命中后提到末尾，b 变最旧
    cache.set("c", 3)  # 应淘汰 b 而非 a
    assert "a" in cache._data
    assert "b" not in cache._data
    assert "c" in cache._data


# 7. 覆盖已有 key 不增加缓存数量
def test_overwrite_existing_key_keeps_size(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", "v1")
    cache.set("k", "v2")
    assert len(cache._data) == 1
    assert cache.get("k", ttl=10) == "v2"


# 8. 空列表可以缓存
def test_empty_list_cacheable(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", [])
    val = cache.get("k", ttl=10)
    assert val is not None  # 显式校验不是 None（避免 == [] 被误判）
    assert val == []


# 9. 空字典可以缓存
def test_empty_dict_cacheable(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", {})
    val = cache.get("k", ttl=10)
    assert val is not None
    assert val == {}


# 10. 0 / False 等假值可以缓存
def test_falsy_values_cacheable(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("zero", 0)
    cache.set("false", False)

    zero_val = cache.get("zero", ttl=10)
    assert zero_val == 0
    assert type(zero_val) is int  # 区分 0 与 False（bool 是 int 子类，== 0 也成立）

    false_val = cache.get("false", ttl=10)
    assert false_val is False
    assert false_val is not None


# 11. 基本并发读写不破坏内部结构
def test_concurrent_access_does_not_corrupt(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache(max_entries=64)
    errors = []

    def worker():
        try:
            for i in range(500):
                cache.set(f"k{i % 100}", i)
                cache.get(f"k{i % 100}", ttl=10)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"并发读写抛出异常: {errors}"
    # 结构不变量：条目数不超过容量上限
    assert len(cache._data) <= cache._max
