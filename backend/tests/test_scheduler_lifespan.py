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
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

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
# 子进程 Import Probe：在独立解释器中验证 import app 不启动 Scheduler
# ---------------------------------------------------------------------------
def _run_app_import_probe(tmp_path: Path) -> dict[str, object]:
    """在独立 Python 子进程中执行 import app，返回 probe 结果。

    使用 sys.executable 确保与当前测试相同的解释器；使用独立 cwd 与
    VR_DATA_DIR 避免污染主仓库或测试/fixtures。子进程仅做一次 probe，
    不启动 Scheduler、不写盘、不留 daemon线程。

    实现要点：
    - 通过 ``python -c`` 直接运行探针源码，不生成临时 ``.py`` 文件，
      避免修改源码工作树、避免进程异常终止时残留文件、避免并行竞争。
    - 线程基线（``before``）在任何项目模块导入前采集，确保
      ``portfolio``/``app`` 导入阶段创建的线程不被归入既有线程，
      严格验证"全新解释器导入不启动调度器"。
    - 通过 ``PYTHONPATH`` 环境变量让子进程能找到 ``backend`` 包，
      无需向源码目录写入 ``sys.path`` 相关的探码文件。
    """
    backend_dir = Path(__file__).resolve().parents[1]

    probe_source = r"""
import json
import threading

before = {
    id(thread)
    for thread in threading.enumerate()
    if thread.name == "portfolio-refresh"
}

import app
import portfolio

after = [
    thread
    for thread in threading.enumerate()
    if thread.name == "portfolio-refresh"
    and id(thread) not in before
]

print(
    "SCHEDULER_IMPORT_PROBE="
    + json.dumps({
        "scheduler_started": portfolio._scheduler_started,
        "new_portfolio_refresh_threads": len(after),
    })
)
"""

    env = os.environ.copy()
    env["VR_DATA_DIR"] = str(tmp_path)
    env["PYTHONPATH"] = (
        str(backend_dir) + os.pathsep + env.get("PYTHONPATH", "")
    )

    proc = subprocess.run(
        [sys.executable, "-c", probe_source],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            f"scheduler import probe failed: returncode={proc.returncode}\n"
            f"stdout={proc.stdout}\n"
            f"stderr={proc.stderr}"
        )

    marker = "SCHEDULER_IMPORT_PROBE="
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker):])

    raise RuntimeError(
        f"probe output missing SCHEDULER_IMPORT_PROBE marker\n"
        f"stdout={proc.stdout}\n"
        f"stderr={proc.stderr}"
    )


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
# 场景 9：import app.py 不启动调度器（独立子进程验证）
# ---------------------------------------------------------------------------
def test_import_app_does_not_start_scheduler(tmp_path: Path):
    """验证在全新的 Python 解释器中 import app 不启动 Scheduler。

    原方案检查当前 pytest 进程的全局线程状态，导致测试间顺序依赖：
    其他测试若已启动 portfolio-refresh daemon 线程，本测试会误判为失败。

    现方案：在独立子进程（sys.executable + 独立 cwd + 独立 VR_DATA_DIR）中
    import app，验证：
      - _scheduler_started 为 False
      - 未创建新的 portfolio-refresh 真实线程
    子进程退出后不留下 daemon 线程，完全与父测试进程隔离。
    """
    result = _run_app_import_probe(tmp_path)

    assert result["scheduler_started"] is False, (
        f"import app 不应启动 scheduler，probe 返回: {result}"
    )
    assert result["new_portfolio_refresh_threads"] == 0, (
        f"import app 不应创建 portfolio-refresh 线程，probe 返回: {result}"
    )


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
