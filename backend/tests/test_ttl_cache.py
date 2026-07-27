"""TTLCache 专项单测：覆盖 TTL 过期 / LRU 淘汰 / 容量上限 / 假值缓存 / 并发安全。

时间不依赖真实睡眠：通过 monkeypatch 替换 app 模块的 `time` 命名空间为可控时钟，
TTLCache 内部 `time.time()` 解析到 app.time.time，从而精确控制过期判定。
"""
import threading
from types import SimpleNamespace

import app
from app import TTLCache, _CACHE_MISS


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


# 3. TTL 过期后返回 miss sentinel
def test_get_miss_after_ttl_expired(monkeypatch):
    clock = _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", "v")
    clock.advance(10)  # time.time() - ts == 10，不满足 < ttl(=10) → 过期
    assert cache.get("k", ttl=10) is _CACHE_MISS


# 4. 过期项从缓存中删除
def test_expired_entry_evicted_from_data(monkeypatch):
    clock = _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", "v")
    clock.advance(10)
    assert cache.get("k", ttl=10) is _CACHE_MISS
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
    assert cache.get("a", ttl=10) is _CACHE_MISS


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
    assert val is not _CACHE_MISS
    assert val == []


# 9. 空字典可以缓存
def test_empty_dict_cacheable(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", {})
    val = cache.get("k", ttl=10)
    assert val is not _CACHE_MISS
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
    assert false_val is not _CACHE_MISS


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


# 12. None 可以作为合法缓存值命中
def test_none_value_cacheable(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    cache.set("k", None)
    val = cache.get("k", ttl=10)
    assert val is None  # 实际值就是 None
    assert val is not _CACHE_MISS  # 但不是 miss sentinel


# 13. 不存在的 key 返回 _CACHE_MISS 而非 None
def test_missing_key_returns_miss_sentinel(monkeypatch):
    _install_clock(monkeypatch)
    cache = TTLCache()
    result = cache.get("missing", ttl=10)
    assert result is _CACHE_MISS
    assert result is not None


# 14. _cached() 辅助函数：fetch 返回 None 时缓存命中，不重复调用 fetch
def test_cached_caches_none_and_skips_refetch(monkeypatch):
    """_cached() 第一次 fetch 返回 None，第二次应命中缓存不再 fetch。"""
    _install_clock(monkeypatch)
    call_count = 0

    def fetch():
        nonlocal call_count
        call_count += 1
        return None

    # 第一次调用：执行 fetch
    result1 = app._cached("test_endpoint", "test_code", 1800, fetch)
    assert result1 is None
    assert call_count == 1

    # 第二次调用：应命中缓存，不再执行 fetch
    result2 = app._cached("test_endpoint", "test_code", 1800, fetch)
    assert result2 is None
    assert call_count == 1, "TTL 内第二次调用不应再执行 fetch"


# 15. _cached() 辅助函数：TTL 过期后重新 fetch
def test_cached_refetches_after_ttl_expiry(monkeypatch):
    """_cached() TTL 过期后应重新执行 fetch。"""
    clock = _install_clock(monkeypatch)
    call_count = 0

    def fetch():
        nonlocal call_count
        call_count += 1
        return {"data": call_count}

    result1 = app._cached("ep", "code", 10, fetch)
    assert result1 == {"data": 1}
    assert call_count == 1

    clock.advance(10)  # 过期
    result2 = app._cached("ep", "code", 10, fetch)
    assert result2 == {"data": 2}
    assert call_count == 2
