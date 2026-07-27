"""持仓后台刷新调度器生命周期专项测试。

覆盖 5 个场景：
1. 导入 app 模块不启动调度器
2. 进入 FastAPI lifespan 后启动一次
3. 多次进入 lifespan 不创建多余线程
4. start_scheduler() 幂等
5. 调度器线程是 daemon

注意：daemon 线程无法在测试间销毁，因此涉及“线程数”的断言一律采用
“操作前后差值”的方式，避免被前序测试残留的线程污染。
"""
from __future__ import annotations

import asyncio
import threading

import pytest

import app as app_module
import portfolio as pf


def _refresh_threads() -> list[threading.Thread]:
    """当前存活的、名为 portfolio-refresh 的线程列表。"""
    return [t for t in threading.enumerate() if t.name == "portfolio-refresh"]


@pytest.fixture(autouse=True)
def _stub_refresh_snapshot(monkeypatch):
    """所有测试自动应用：打桩 _refresh_snapshot 防止后台线程联网抓取。

    调度器线程内部 loop() 通过模块 globals 查找 _refresh_snapshot，
    所以 monkeypatch pf._refresh_snapshot 即可让即便真的触发刷新也变成 no-op。
    实际上 interval=1800s，测试期间不会触发，此为 defense-in-depth。
    """
    monkeypatch.setattr(pf, "_refresh_snapshot", lambda: None, raising=False)


@pytest.fixture()
def _reset_scheduler_flag():
    """重置 portfolio._scheduler_started 标志，使本测试可重新触发 start_scheduler。

    setup 与 teardown 各重置一次，保证测试间隔离。
    """
    pf._scheduler_started = False
    yield
    pf._scheduler_started = False


# ---------------------------------------------------------------------------
# 场景 1：导入 app.py 不启动调度器
# ---------------------------------------------------------------------------
def test_import_app_does_not_start_scheduler():
    """导入 app 模块后，_scheduler_started 仍为 False，且无 portfolio-refresh 线程。

    app 已在测试模块顶部导入（模块体执行完毕）。若导入过程触发了
    start_scheduler，_scheduler_started 会变为 True 且会存在 portfolio-refresh 线程。
    本测试不使用 _reset_scheduler_flag，以保留导入后的真实状态。
    """
    assert pf._scheduler_started is False
    assert len(_refresh_threads()) == 0, "导入 app 不应启动 portfolio-refresh 线程"


# ---------------------------------------------------------------------------
# 场景 2：进入 FastAPI lifespan 后启动一次
# ---------------------------------------------------------------------------
def test_lifespan_starts_scheduler_once(_reset_scheduler_flag):
    """进入 lifespan 触发 pf.start_scheduler(1800)，标志变 True 且仅新增 1 个线程。"""
    before = len(_refresh_threads())
    assert pf._scheduler_started is False

    async def _run() -> int:
        async with app_module.lifespan(app_module.app):
            # 上下文内：调度器已启动
            assert pf._scheduler_started is True
            return len(_refresh_threads())

    during = asyncio.run(_run())

    assert during - before == 1, "lifespan 进入应仅新增 1 个 portfolio-refresh 线程"
    # 退出 lifespan 后标志仍为 True（lifespan 不负责停止调度器）
    assert pf._scheduler_started is True
    assert len(_refresh_threads()) - before == 1


# ---------------------------------------------------------------------------
# 场景 3：多次进入 lifespan 不创建多余线程
# ---------------------------------------------------------------------------
def test_repeated_lifespan_no_thread_explosion(_reset_scheduler_flag):
    """连续 3 次进入 lifespan，仍然只新增 1 个 portfolio-refresh 线程。"""
    before = len(_refresh_threads())

    async def _run():
        for _ in range(3):
            async with app_module.lifespan(app_module.app):
                pass

    asyncio.run(_run())

    after = len(_refresh_threads())
    assert after - before == 1, "多次进入 lifespan 应仅创建 1 个线程"
    assert pf._scheduler_started is True


# ---------------------------------------------------------------------------
# 场景 4：start_scheduler() 幂等
# ---------------------------------------------------------------------------
def test_start_scheduler_idempotent(_reset_scheduler_flag):
    """直接调用 pf.start_scheduler() 两次，线程数不增加。"""
    before = len(_refresh_threads())

    pf.start_scheduler(1800)
    assert pf._scheduler_started is True
    mid = len(_refresh_threads())
    assert mid - before == 1, "首次调用应创建 1 个线程"

    pf.start_scheduler(1800)
    after = len(_refresh_threads())
    assert after == mid, "第二次调用不应创建新线程"


# ---------------------------------------------------------------------------
# 场景 5：调度器线程是 daemon
# ---------------------------------------------------------------------------
def test_scheduler_thread_is_daemon(_reset_scheduler_flag):
    """portfolio-refresh 线程的 daemon 属性为 True。"""
    existing_idents = {t.ident for t in _refresh_threads()}

    pf.start_scheduler(1800)

    new_threads = [t for t in _refresh_threads() if t.ident not in existing_idents]
    assert len(new_threads) == 1, "应仅新增 1 个 portfolio-refresh 线程"
    t = new_threads[0]
    assert t.daemon is True, "调度器线程应为 daemon"
    assert t.is_alive(), "调度器线程应正在运行"
