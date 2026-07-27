"""持仓后台刷新调度器生命周期专项测试（FakeThread 版）。

使用 FakeThread 替换 threading.Thread，不创建任何真实线程，避免 daemon
线程无法在测试间销毁的问题。

覆盖 10 个场景：
1.  首次调用 start_scheduler() 创建一个 FakeThread
2.  第二次调用不再创建新对象（幂等）
3.  线程名称为 portfolio-refresh
4.  daemon=True
5.  start() 只调用一次
6.  lifespan 调用 start_scheduler() — 进入 lifespan 后 _scheduler_started 变 True
7.  多次进入 lifespan，仍只创建一个 FakeThread
8.  测试运行前后，真实 threading.enumerate() 中不得增加 portfolio-refresh 线程
9.  import app.py 不启动调度器（方案 B：静态调用路径验证）
10. 线程启动失败时回滚 _scheduler_started — 后续调用可重新尝试
"""
from __future__ import annotations

import asyncio
import threading

import pytest

import app as app_module
import portfolio as pf


# ---------------------------------------------------------------------------
# FakeThread：替代 threading.Thread 的测试桩，不创建真实线程
# ---------------------------------------------------------------------------
class FakeThread:
    """记录创建/启动行为的 Thread 替身。

    所有创建的实例追加到类属性 ``created``，供测试断言数量与属性。
    ``start_call_count`` 记录 start() 被调用的次数（场景 5）。
    """

    created: list["FakeThread"] = []

    def __init__(self, *, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.start_call_count = 0
        FakeThread.created.append(self)

    def start(self):
        self.start_call_count += 1
        self.started = True

    def is_alive(self):
        return self.started


class FailingFakeThread(FakeThread):
    """start() 抛 RuntimeError 的 FakeThread 子类，用于场景 10 启动失败回滚。"""

    def start(self):
        self.start_call_count += 1
        raise RuntimeError("simulated thread start failure")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _real_portfolio_refresh_threads() -> list[threading.Thread]:
    """真实 threading.enumerate() 中名为 portfolio-refresh 的线程列表。"""
    return [t for t in threading.enumerate() if t.name == "portfolio-refresh"]


# ---------------------------------------------------------------------------
# 每个测试前重置状态
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_state():
    """重置 pf._scheduler_started 标志和 FakeThread.created 列表，保证测试间隔离。"""
    pf._scheduler_started = False
    FakeThread.created = []
    yield
    pf._scheduler_started = False
    FakeThread.created = []


# ---------------------------------------------------------------------------
# 场景 1：首次调用 start_scheduler() 创建一个 FakeThread
# ---------------------------------------------------------------------------
def test_start_scheduler_creates_one_thread(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    pf.start_scheduler(1800)
    assert len(FakeThread.created) == 1


# ---------------------------------------------------------------------------
# 场景 2：第二次调用不再创建新对象（幂等）
# ---------------------------------------------------------------------------
def test_start_scheduler_idempotent(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    pf.start_scheduler(1800)
    assert len(FakeThread.created) == 1
    pf.start_scheduler(1800)
    assert len(FakeThread.created) == 1


# ---------------------------------------------------------------------------
# 场景 3：线程名称为 portfolio-refresh
# ---------------------------------------------------------------------------
def test_thread_name_is_portfolio_refresh(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    pf.start_scheduler(1800)
    assert len(FakeThread.created) == 1
    assert FakeThread.created[0].name == "portfolio-refresh"


# ---------------------------------------------------------------------------
# 场景 4：daemon=True
# ---------------------------------------------------------------------------
def test_thread_is_daemon(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    pf.start_scheduler(1800)
    assert len(FakeThread.created) == 1
    assert FakeThread.created[0].daemon is True


# ---------------------------------------------------------------------------
# 场景 5：start() 只调用一次
# ---------------------------------------------------------------------------
def test_start_called_once(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    pf.start_scheduler(1800)
    pf.start_scheduler(1800)
    pf.start_scheduler(1800)
    assert len(FakeThread.created) == 1
    assert FakeThread.created[0].start_call_count == 1


# ---------------------------------------------------------------------------
# 场景 6：lifespan 调用 start_scheduler() — 进入 lifespan 后 _scheduler_started 变 True
# ---------------------------------------------------------------------------
def test_lifespan_starts_scheduler(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    assert pf._scheduler_started is False

    async def _run():
        async with app_module.lifespan(app_module.app):
            assert pf._scheduler_started is True

    asyncio.run(_run())
    assert pf._scheduler_started is True
    assert len(FakeThread.created) == 1


# ---------------------------------------------------------------------------
# 场景 7：多次进入 lifespan，仍只创建一个 FakeThread
# ---------------------------------------------------------------------------
def test_repeated_lifespan_one_thread(monkeypatch):
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)

    async def _run():
        for _ in range(3):
            async with app_module.lifespan(app_module.app):
                pass

    asyncio.run(_run())
    assert len(FakeThread.created) == 1
    assert pf._scheduler_started is True


# ---------------------------------------------------------------------------
# 场景 8：测试运行前后，真实 threading.enumerate() 中不得增加 portfolio-refresh 线程
# ---------------------------------------------------------------------------
def test_no_real_thread_created(monkeypatch):
    before = len(_real_portfolio_refresh_threads())
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)

    pf.start_scheduler(1800)
    pf.start_scheduler(1800)

    async def _run():
        async with app_module.lifespan(app_module.app):
            pass

    asyncio.run(_run())

    after = len(_real_portfolio_refresh_threads())
    assert after == before, "不应在真实线程列表中增加 portfolio-refresh 线程"


# ---------------------------------------------------------------------------
# 场景 9：import app.py 不启动调度器（方案 B：静态调用路径验证）
# ---------------------------------------------------------------------------
def test_import_app_does_not_start_scheduler():
    """app 已在模块顶部导入。若导入触发了 start_scheduler，会有真实线程残留。

    方案 B：静态调用路径验证——检查标志和真实线程数。
    """
    assert pf._scheduler_started is False
    assert len(_real_portfolio_refresh_threads()) == 0, \
        "导入 app 不应创建 portfolio-refresh 线程"


# ---------------------------------------------------------------------------
# 场景 10：线程启动失败时回滚 _scheduler_started
# ---------------------------------------------------------------------------
def test_start_failure_rolls_back_flag(monkeypatch):
    """FakeThread.start() 抛 RuntimeError 时，_scheduler_started 应为 False，且后续可重新尝试。"""
    monkeypatch.setattr(pf.threading, "Thread", FailingFakeThread)
    assert pf._scheduler_started is False

    with pytest.raises(RuntimeError):
        pf.start_scheduler(1800)

    # 启动失败后，标志应仍为 False（回滚）
    assert pf._scheduler_started is False
    # FailingFakeThread 实例确实被创建了（但 start 失败）
    assert len(FakeThread.created) == 1

    # 后续可重新尝试：换回正常 FakeThread
    monkeypatch.setattr(pf.threading, "Thread", FakeThread)
    pf.start_scheduler(1800)

    assert pf._scheduler_started is True
    assert len(FakeThread.created) == 2
