"""P0-SEC2 目标测试：CLI 执行面安全边界（执行门 / 最小环境 / 预算 / 并发 / 进程树）。

覆盖 docs/p0/CLI_SECURITY_V01.md 的目标测试 A-AL：
HTTP 执行门（A-E）、argv 契约（F-H）、最小环境（I-K）、输入预算（L-N）、
输出预算（O-R）、有界队列（S-T）、并发（U-Y）、截止时间（Z）、
进程树终止（AA-AC）、临时目录（AD-AF）、shell 安全（AG-AH）、
错误净化（AI-AJ）、注册表确定性（AK）、fail-closed（AL）。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

import cli_runtime


# ---------- helpers ----------

def _register_fake(monkeypatch, *, code="import sys\nsys.stdout.write('ok')\n", delivery="stdin"):
    """注册一个以本机 python 为执行体的 fake provider（stdin delivery）。"""
    monkeypatch.setitem(cli_runtime._CLI_DEFS, "fake", {
        "bins": [sys.executable],
        "delivery": delivery,
        "build_args": lambda _: ["-c", code],
        "env": {},
    })
    return "fake"


def _authorize_fake(monkeypatch, *, http_allowed=True):
    """模拟「已 opt-in + 鉴权 + fake provider 已证明 text-only」的部署。"""
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", True)
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "test-key")
    monkeypatch.setitem(
        cli_runtime.CLI_SECURITY_CAPABILITIES, "fake",
        {"text_only_proven": http_allowed, "proof_mode": "TEST", "http_allowed": http_allowed},
    )


def _fresh_sem(monkeypatch, value=1):
    sem = threading.BoundedSemaphore(value)
    monkeypatch.setattr(cli_runtime, "_PROC_SEM", sem)
    return sem


def _capture_popen(monkeypatch):
    """包装真实 Popen，返回 (captured_dict)。过滤 taskkill（subprocess.run 内部会走 Popen）。"""
    captured = {}
    real_popen = cli_runtime.subprocess.Popen

    def cap_popen(*args, **kwargs):
        argv = args[0] if args else []
        if argv and os.path.basename(str(argv[0])).lower().startswith("taskkill"):
            return real_popen(*args, **kwargs)  # 树终止系统调用：不捕获
        proc = real_popen(*args, **kwargs)
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(cli_runtime.subprocess, "Popen", cap_popen)
    return captured


def _wait_poll(proc, timeout=10.0):
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return proc.poll()


def _is_windows_process_alive(pid: int) -> bool:
    """Windows 原生判断进程是否存活（STILL_ACTIVE=259）。进程不存在/打不开 → False。"""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    try:
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        if not ok:
            return False
        return code.value == STILL_ACTIVE
    except Exception:  # noqa: BLE001
        return False


# 进程树脚本：parent 先 spawn 一个 child sleeper 并打印其 pid，然后自己也挂起。
_TREE_CODE = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print('spawned', child.pid, flush=True)\n"
    "time.sleep(120)\n"
)

_TREE_CODE_FLOOD = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print('spawned', child.pid, flush=True)\n"
    "for i in range(100):\n"
    "    print('x' * 1000, flush=True)\n"
    "time.sleep(120)\n"
)


# ================= A-D：HTTP 执行门 =================

def test_http_cli_disabled_by_default(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", False)
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "")
    with pytest.raises(cli_runtime.CliExecutionDisabled) as ei:
        cli_runtime.run_cli("fake", "s", "u", via_http=True)
    assert ei.value.code == "CLI_EXECUTION_DISABLED"


def test_http_cli_stream_disabled_by_default(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", False)
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "")
    with pytest.raises(cli_runtime.CliExecutionDisabled):
        next(cli_runtime.run_cli_stream("fake", "s", "u", via_http=True))


def test_http_cli_requires_explicit_opt_in(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", False)  # 未 opt-in
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "test-key")  # 有鉴权也无济于事
    with pytest.raises(cli_runtime.CliExecutionDisabled):
        cli_runtime.run_cli("fake", "s", "u", via_http=True)


def test_http_cli_requires_authentication(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", True)  # opt-in
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "")  # 但无 key：loopback 也禁止
    with pytest.raises(cli_runtime.CliExecutionDisabled):
        cli_runtime.run_cli("fake", "s", "u", via_http=True)


def test_http_cli_no_silent_fallback_not_proven_provider(monkeypatch):
    # opt-in + 鉴权都满足，但 provider 未证明 no-tools → 仍拒绝（无静默替代路径）
    _register_fake(monkeypatch)
    _authorize_fake(monkeypatch, http_allowed=False)
    with pytest.raises(cli_runtime.CliExecutionDisabled):
        cli_runtime.run_cli("fake", "s", "u", via_http=True)


# ================= E：unsafe provider 不能执行 =================

def test_unsafe_provider_cannot_execute_even_when_opted_in(monkeypatch):
    # 真实 registry：四个 provider 全部 http_allowed=False → opt-in 后依然拒绝
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", True)
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "test-key")
    for kind in ("claude", "qwen", "deepseek", "codex"):
        with pytest.raises(cli_runtime.CliExecutionDisabled):
            cli_runtime.run_cli(kind, "s", "u", via_http=True)
        with pytest.raises(cli_runtime.CliExecutionDisabled):
            next(cli_runtime.run_cli_stream(kind, "s", "u", via_http=True))


# ================= F-H：argv 契约 =================

def test_safe_provider_argv_exactly_matches_proven_mode(monkeypatch):
    # 授权后的 provider：argv 必须精确 = detect_cli 结果 + registry build_args，无任何注入
    _register_fake(monkeypatch)
    _authorize_fake(monkeypatch)
    captured = {}

    class _Pipe:
        def write(self, data):
            pass

        def close(self):
            self.closed = True

    class _Stdout:
        def __init__(self, it):
            self._it = it

        def __iter__(self):
            return self._it

        def close(self):
            pass

    class _Proc:
        def __init__(self):
            self.stdin = _Pipe()
            self.stdout = _Stdout(iter(["ok\n"]))
            self._rc = None

        def poll(self):
            return self._rc

        def wait(self, timeout=None):
            self._rc = 0
            return 0

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(cli_runtime.subprocess, "Popen", fake_popen)

    out = cli_runtime.run_cli("fake", "sys", "usr", via_http=True)
    assert out == "ok"
    assert captured["argv"][0] == sys.executable  # binary 来自 detect_cli
    assert captured["argv"][1:] == ["-c", "import sys\nsys.stdout.write('ok')\n"]  # 精确 registry args
    assert captured["kwargs"].get("shell", False) is False


def test_no_yolo_in_any_http_allowed_provider():
    # 任何被放行（http_allowed=True）的 provider 都不得携带 --yolo（Qwen agentic 模式）
    for kind, cap in cli_runtime.CLI_SECURITY_CAPABILITIES.items():
        if cap.get("http_allowed"):
            args = cli_runtime._CLI_DEFS[kind]["build_args"](None)
            assert "--yolo" not in args, f"{kind} http_allowed 但 argv 含 --yolo"


def test_no_auto_in_any_http_allowed_provider():
    # 任何被放行（http_allowed=True）的 provider 都不得携带 exec --auto（DeepSeek agentic 模式）
    for kind, cap in cli_runtime.CLI_SECURITY_CAPABILITIES.items():
        if cap.get("http_allowed"):
            args = cli_runtime._CLI_DEFS[kind]["build_args"](None)
            assert "--auto" not in args, f"{kind} http_allowed 但 argv 含 --auto"


# ================= I-K：最小子进程环境 =================

def test_full_os_environ_not_inherited(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VAR", "x")
    monkeypatch.setenv("VR_DATA_DIR", "/somewhere")
    env = cli_runtime._build_child_env({})
    assert "SOME_UNRELATED_VAR" not in env
    assert "VR_DATA_DIR" not in env


def test_secret_sentinel_env_absent(monkeypatch):
    secrets = [
        "VR_API_KEY", "IWENCAI_API_KEY", "TUSHARE_TOKEN",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
        "DATABASE_URL", "DB_URL", "SOME_RANDOM_SECRET",
        "MY_PASSWORD", "AWS_SECRET_ACCESS_KEY",
    ]
    for var in secrets:
        monkeypatch.setenv(var, "super-secret")
    env = cli_runtime._build_child_env({})
    for var in secrets:
        assert var not in env


def test_secret_env_not_passed_to_child(monkeypatch):
    # 端到端：spawn 前的 child env 不含 secret sentinel
    _register_fake(monkeypatch)
    captured = _capture_popen(monkeypatch)
    monkeypatch.setenv("VR_API_KEY", "super-secret")
    monkeypatch.setenv("TUSHARE_TOKEN", "super-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    cli_runtime.run_cli("fake", "s", "u")
    child_env = captured["kwargs"]["env"]
    assert "VR_API_KEY" not in child_env
    assert "TUSHARE_TOKEN" not in child_env
    assert "OPENAI_API_KEY" not in child_env


def test_required_runtime_env_preserved(monkeypatch):
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    env = cli_runtime._build_child_env({})
    for key in cli_runtime._CHILD_ENV_ALLOWLIST:
        if os.environ.get(key):
            assert env.get(key) == os.environ[key], f"allowlist 变量 {key} 应保留"


# ================= L-N：输入预算 =================

def test_input_under_budget_works(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "CLI_INPUT_LIMIT_BYTES", 10_000)
    assert cli_runtime.run_cli("fake", "s" * 100, "u" * 100) == "ok"


def test_input_exactly_at_budget_works(monkeypatch):
    monkeypatch.setattr(cli_runtime, "CLI_INPUT_LIMIT_BYTES", 200)
    cli_runtime._check_input_budget("s" * 100, "u" * 100)  # == 200 不抛


def test_input_budget_counts_utf8_bytes(monkeypatch):
    # "中文" = 6 个 UTF-8 字节
    monkeypatch.setattr(cli_runtime, "CLI_INPUT_LIMIT_BYTES", 5)
    with pytest.raises(cli_runtime.CliInputLimit):
        cli_runtime._check_input_budget("中文", "")


def test_input_over_budget_rejected_before_spawn(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "CLI_INPUT_LIMIT_BYTES", 199)
    popen = MagicMock()
    monkeypatch.setattr(cli_runtime.subprocess, "Popen", popen)
    with pytest.raises(cli_runtime.CliInputLimit):
        cli_runtime.run_cli("fake", "s" * 100, "u" * 100)
    popen.assert_not_called()  # spawn 前 fail-closed 拒绝


# ================= O-R：输出预算 =================

def test_nonstream_output_under_limit_works(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "CLI_OUTPUT_LIMIT_BYTES", 10_000)
    assert cli_runtime.run_cli("fake", "s", "u") == "ok"


def test_nonstream_output_over_limit_kills_process(monkeypatch):
    _register_fake(monkeypatch, code="import time\nprint('x' * 10000, flush=True)\ntime.sleep(30)")
    monkeypatch.setattr(cli_runtime, "CLI_OUTPUT_LIMIT_BYTES", 100)
    captured = _capture_popen(monkeypatch)
    with pytest.raises(cli_runtime.CliOutputLimit):
        cli_runtime.run_cli("fake", "s", "u")
    assert _wait_poll(captured["proc"]) is not None  # 进程树已终止


def test_stream_output_under_limit_works(monkeypatch):
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "CLI_OUTPUT_LIMIT_BYTES", 10_000)
    assert "".join(cli_runtime.run_cli_stream("fake", "s", "u")).strip() == "ok"


def test_stream_output_over_limit_kills_process(monkeypatch):
    _register_fake(monkeypatch, code="import time\nprint('x' * 10000, flush=True)\ntime.sleep(30)")
    monkeypatch.setattr(cli_runtime, "CLI_OUTPUT_LIMIT_BYTES", 100)
    captured = _capture_popen(monkeypatch)
    with pytest.raises(cli_runtime.CliOutputLimit):
        for _ in cli_runtime.run_cli_stream("fake", "s", "u"):
            pass
    assert _wait_poll(captured["proc"]) is not None


# ================= S-T：有界队列 =================

def test_stream_queue_bounded(monkeypatch):
    _register_fake(monkeypatch)
    captured = {}
    real_queue = cli_runtime.queue.Queue

    def cap_queue(*args, **kwargs):
        q = real_queue(*args, **kwargs)
        captured["maxsize"] = q.maxsize
        return q

    monkeypatch.setattr(cli_runtime.queue, "Queue", cap_queue)
    list(cli_runtime.run_cli_stream("fake", "s", "u"))
    assert captured["maxsize"] == cli_runtime.CLI_QUEUE_MAXSIZE


def test_slow_consumer_close_no_deadlock_no_leak(monkeypatch):
    # 慢消费者：pump 堆积 → 队列满 → 消费者关闭 → pump 经 stop_event 退出，进程树被杀
    _register_fake(monkeypatch, code="import time\nfor i in range(100000):\n    print(i, flush=True)")
    monkeypatch.setattr(cli_runtime, "CLI_QUEUE_MAXSIZE", 4)
    captured = _capture_popen(monkeypatch)
    stream = cli_runtime.run_cli_stream("fake", "s", "u")
    next(stream)  # 只取一块，之后不消费
    stream.close()
    assert _wait_poll(captured["proc"]) is not None
    assert not any(
        t.name == "vibe-cli-fake-stdout" and t.is_alive()
        for t in cli_runtime.threading.enumerate()
    )


# ================= U-Y：全局并发 =================

def test_concurrency_never_exceeds_max(monkeypatch):
    _fresh_sem(monkeypatch, value=2)
    cli_runtime._PROC_SEM.acquire()
    cli_runtime._PROC_SEM.acquire()
    monkeypatch.setattr(cli_runtime, "CLI_CONCURRENCY_ACQUIRE_TIMEOUT", 0.2)
    with pytest.raises(cli_runtime.CliBusy):
        cli_runtime._acquire_slot()
    cli_runtime._PROC_SEM.release()
    cli_runtime._PROC_SEM.release()


def test_semaphore_released_after_success(monkeypatch):
    _register_fake(monkeypatch)
    sem = _fresh_sem(monkeypatch, value=1)
    assert cli_runtime.run_cli("fake", "s", "u") == "ok"
    assert sem._value == 1


def test_semaphore_released_after_failure(monkeypatch):
    _register_fake(monkeypatch, code="import sys\nsys.exit(3)")
    sem = _fresh_sem(monkeypatch, value=1)
    with pytest.raises(cli_runtime.CliError):
        cli_runtime.run_cli("fake", "s", "u")
    assert sem._value == 1


def test_semaphore_released_after_cancel(monkeypatch):
    _register_fake(monkeypatch, code="import time\nprint('x', flush=True)\ntime.sleep(30)")
    sem = _fresh_sem(monkeypatch, value=1)
    cancel = threading.Event()
    stream = cli_runtime.run_cli_stream("fake", "s", "u", cancel_event=cancel)
    next(stream)
    cancel.set()
    with pytest.raises(cli_runtime.CliError, match="取消"):
        next(stream)
    assert sem._value == 1


# ================= Z：总 wall-clock 截止 =================

def test_total_wall_clock_timeout_nonstream(monkeypatch):
    _register_fake(monkeypatch, code="import time\ntime.sleep(30)")
    monkeypatch.setattr(cli_runtime, "CLI_TOTAL_DEADLINE_SECONDS", 1)
    captured = _capture_popen(monkeypatch)
    with pytest.raises(cli_runtime.CliTimeout):
        cli_runtime.run_cli("fake", "s", "u")
    assert _wait_poll(captured["proc"]) is not None


# ================= AA-AC：进程树终止 =================

@pytest.mark.skipif(os.name != "nt", reason="Windows 原生进程树验证")
def test_cancel_kills_full_process_tree_windows(monkeypatch):
    _register_fake(monkeypatch, code=_TREE_CODE)
    cancel = threading.Event()
    captured = _capture_popen(monkeypatch)
    child_pid = None
    stream = cli_runtime.run_cli_stream("fake", "s", "u", cancel_event=cancel)
    for line in stream:
        if line.startswith("spawned"):
            child_pid = int(line.split()[1])
            break
    cancel.set()
    with pytest.raises(cli_runtime.CliError, match="取消"):
        for _ in stream:
            pass
    assert child_pid is not None
    assert _wait_poll(captured["proc"]) is not None  # parent dead
    deadline = time.monotonic() + 10
    while _is_windows_process_alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _is_windows_process_alive(child_pid)  # child dead


@pytest.mark.skipif(os.name != "nt", reason="Windows 原生进程树验证")
def test_timeout_kills_full_process_tree_windows(monkeypatch):
    _register_fake(monkeypatch, code=_TREE_CODE)
    monkeypatch.setattr(cli_runtime, "CLI_TOTAL_DEADLINE_SECONDS", 2)
    captured = _capture_popen(monkeypatch)
    child_pid = None
    with pytest.raises(cli_runtime.CliTimeout):
        for line in cli_runtime.run_cli_stream("fake", "s", "u"):
            if line.startswith("spawned"):
                child_pid = int(line.split()[1])
    assert child_pid is not None
    assert _wait_poll(captured["proc"]) is not None
    deadline = time.monotonic() + 10
    while _is_windows_process_alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _is_windows_process_alive(child_pid)


@pytest.mark.skipif(os.name != "nt", reason="Windows 原生进程树验证")
def test_output_limit_kills_full_process_tree_windows(monkeypatch):
    _register_fake(monkeypatch, code=_TREE_CODE_FLOOD)
    monkeypatch.setattr(cli_runtime, "CLI_OUTPUT_LIMIT_BYTES", 1000)
    captured = _capture_popen(monkeypatch)
    child_pid = None
    with pytest.raises(cli_runtime.CliOutputLimit):
        for line in cli_runtime.run_cli_stream("fake", "s", "u"):
            if line.startswith("spawned"):
                child_pid = int(line.split()[1])
    assert child_pid is not None
    assert _wait_poll(captured["proc"]) is not None
    deadline = time.monotonic() + 10
    while _is_windows_process_alive(child_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _is_windows_process_alive(child_pid)


# ================= AD-AF：临时目录 =================

def _capture_tmpdir(monkeypatch):
    dirs = []
    real_mkdtemp = cli_runtime.tempfile.mkdtemp

    def cap_mkdtemp(*args, **kwargs):
        d = real_mkdtemp(*args, **kwargs)
        dirs.append(d)
        return d

    monkeypatch.setattr(cli_runtime.tempfile, "mkdtemp", cap_mkdtemp)
    return dirs


def test_temp_dir_removed_after_success(monkeypatch):
    _register_fake(monkeypatch)
    dirs = _capture_tmpdir(monkeypatch)
    cli_runtime.run_cli("fake", "s", "u")
    assert dirs and not os.path.exists(dirs[0])


def test_temp_dir_removed_after_failure(monkeypatch):
    _register_fake(monkeypatch, code="import sys\nsys.exit(3)")
    dirs = _capture_tmpdir(monkeypatch)
    with pytest.raises(cli_runtime.CliError):
        cli_runtime.run_cli("fake", "s", "u")
    assert dirs and not os.path.exists(dirs[0])


def test_system_prompt_file_removed(monkeypatch):
    # system-file delivery：system.txt 在临时目录内，run 后随目录删除
    monkeypatch.setitem(cli_runtime._CLI_DEFS, "fake", {
        "bins": [sys.executable],
        "delivery": "system-file",
        "build_args": lambda _sf: ["-c", "print('ok')"],
        "env": {},
    })
    dirs = _capture_tmpdir(monkeypatch)
    assert cli_runtime.run_cli("fake", "sys", "usr") == "ok"
    assert dirs
    assert not os.path.exists(os.path.join(dirs[0], "system.txt"))
    assert not os.path.exists(dirs[0])


# ================= AG-AH：shell 与 binary 注入 =================

def test_shell_is_false(monkeypatch):
    _register_fake(monkeypatch)
    captured = _capture_popen(monkeypatch)
    cli_runtime.run_cli("fake", "s", "u")
    assert captured["kwargs"].get("shell", False) is False
    assert isinstance(captured["argv"], list)  # argv 是 list，非 shell 字符串


def test_binary_cannot_be_user_injected():
    # kind 只能命中固定 registry；路径/命令注入一律 fail closed
    with pytest.raises(cli_runtime.CliUnavailable):
        cli_runtime.run_cli("C:\\Windows\\System32\\calc.exe", "s", "u")
    with pytest.raises(cli_runtime.CliUnavailable):
        cli_runtime.run_cli("claude; rm -rf /", "s", "u")
    with pytest.raises(cli_runtime.CliUnavailable):
        next(cli_runtime.run_cli_stream("&& whoami", "s", "u"))
    assert cli_runtime.detect_cli("../../etc/passwd") is None


# ================= AI-AJ：错误净化 =================

def test_stderr_not_reflected(monkeypatch):
    _register_fake(
        monkeypatch,
        code="import sys\nsys.stderr.write('SECRET-STDERR')\nsys.stdout.write('ok')\n",
    )
    captured = _capture_popen(monkeypatch)
    out = cli_runtime.run_cli("fake", "s", "u")
    assert "SECRET-STDERR" not in out
    assert captured["kwargs"]["stderr"] == cli_runtime.subprocess.DEVNULL


def test_errors_do_not_contain_prompt(monkeypatch):
    _register_fake(monkeypatch, code="import sys\nsys.exit(7)")
    with pytest.raises(cli_runtime.CliError) as ei:
        cli_runtime.run_cli("fake", "SENSITIVE-SYSTEM-PROMPT", "SENSITIVE-USER-PROMPT")
    assert "SENSITIVE" not in str(ei.value)


def test_errors_have_fixed_public_codes():
    assert cli_runtime.CliUnavailable.code == "CLI_UNAVAILABLE"
    assert cli_runtime.CliExecutionDisabled.code == "CLI_EXECUTION_DISABLED"
    assert cli_runtime.CliTimeout.code == "CLI_TIMEOUT"
    assert cli_runtime.CliOutputLimit.code == "CLI_OUTPUT_LIMIT"
    assert cli_runtime.CliBusy.code == "CLI_BUSY"
    assert cli_runtime.CliInputLimit.code in ("CLI_FAILED", "CLI_EXECUTION_DISABLED")


# ================= AK-AL：注册表与 fail-closed =================

def test_provider_registry_deterministic():
    kinds = cli_runtime.supported_kinds()
    assert kinds == ["claude", "qwen", "deepseek", "codex"]  # 固定顺序
    assert set(cli_runtime.CLI_SECURITY_CAPABILITIES) == set(kinds)
    for kind in kinds:
        cap = cli_runtime.CLI_SECURITY_CAPABILITIES[kind]
        assert cap["http_allowed"] is False  # 当前全部 fail-closed
        assert "text_only_proven" in cap and "proof_mode" in cap


def test_unsupported_kind_fail_closed():
    assert cli_runtime.detect_cli("nonexistent-kind") is None
    with pytest.raises(cli_runtime.CliUnavailable):
        cli_runtime.run_cli("nonexistent-kind", "s", "u")
    with pytest.raises(cli_runtime.CliUnavailable):
        next(cli_runtime.run_cli_stream("nonexistent-kind", "s", "u"))


def test_non_http_direct_call_not_gated(monkeypatch):
    # 非 HTTP 直调（via_http 默认 False）不触发执行门（防御层边界仍生效）
    _register_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "VR_ENABLE_LOCAL_CLI", False)
    monkeypatch.setattr(cli_runtime, "VR_API_KEY", "")
    assert cli_runtime.run_cli("fake", "s", "u") == "ok"


# ================= POSIX 进程树终止逻辑（仅真实 Linux 跑，验证 killpg 防御） =================

@pytest.mark.skipif(os.name != "posix", reason="POSIX-only")
def test_posix_killpg_skips_host_process_group(monkeypatch):
    # 防御：子进程未能脱离宿主进程组（start_new_session 失效）→ 绝不 killpg 宿主组，
    # 降级为单进程 kill，避免误杀宿主 runner。
    proc = MagicMock()
    proc.pid = 12345
    proc.poll.return_value = None
    monkeypatch.setattr(cli_runtime.os, "getpgid", lambda pid: 999)
    monkeypatch.setattr(cli_runtime.os, "getpgrp", lambda: 999)  # 宿主组 == 子进程组
    killpg = MagicMock()
    monkeypatch.setattr(cli_runtime.os, "killpg", killpg)
    cli_runtime._terminate_process_tree(proc)
    killpg.assert_not_called()  # 不杀宿主组
    proc.kill.assert_called_once()


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only")
def test_posix_killpg_kills_isolated_group(monkeypatch):
    # 正常：子进程已脱离为独立进程组 → killpg 杀该组。
    proc = MagicMock()
    proc.pid = 12345
    proc.poll.return_value = None
    monkeypatch.setattr(cli_runtime.os, "getpgid", lambda pid: 12345)
    monkeypatch.setattr(cli_runtime.os, "getpgrp", lambda: 1)
    killpg = MagicMock()
    monkeypatch.setattr(cli_runtime.os, "killpg", killpg)
    cli_runtime._terminate_process_tree(proc)
    killpg.assert_called_once_with(12345, cli_runtime.signal.SIGKILL)


def test_terminate_already_exited_is_noop(monkeypatch):
    proc = MagicMock()
    proc.poll.return_value = 0  # 已退出
    cli_runtime._terminate_process_tree(proc)
    proc.kill.assert_not_called()


# ================= P0-SEC2-R1 补强 =================

def _posix_wait_dead(pid: int, timeout: float = 10.0) -> bool:
    """POSIX 判断 pid 是否不再存活（kill(pid, 0) 抛 ProcessLookupError = 已死）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.05)
    return False


def _assert_no_cli_threads_alive():
    alive = [
        t.name for t in cli_runtime.threading.enumerate()
        if t.name.startswith("vibe-cli-") and t.is_alive()
    ]
    assert not alive, f"残留 CLI 线程: {alive}"


# ---------- BLOCKER A：ONE EXECUTION = ONE DEADLINE（阻塞 stdin 复用同一 deadline） ----------

def test_blocked_stdin_uses_same_total_deadline(monkeypatch):
    """CLI 不读 stdin + payload 超过 pipe 容量时，stdin 阻塞必须消费同一总 deadline
    （不被拆成 writer 300s + stdout 300s 两个 budget）。证明 total elapsed 受单一
    deadline + 清理 allowance 限制，且进程/线程/信号量/临时目录全部清理。"""
    _register_fake(monkeypatch, code="import time\nprint('x', flush=True)\ntime.sleep(30)")
    monkeypatch.setattr(cli_runtime, "CLI_TOTAL_DEADLINE_SECONDS", 2)
    monkeypatch.setattr(cli_runtime, "CLI_INPUT_LIMIT_BYTES", 500_000)
    big_system = "s" * 70_000  # > 常见 pipe 容量（64KB）但 < CLI_INPUT_LIMIT_BYTES
    sem = _fresh_sem(monkeypatch, value=1)
    dirs = _capture_tmpdir(monkeypatch)
    cap = _capture_popen(monkeypatch)

    started = time.monotonic()
    with pytest.raises(cli_runtime.CliTimeout):
        cli_runtime.run_cli("fake", big_system, "u")
    elapsed = time.monotonic() - started

    # 单一 2s deadline + 清理 allowance；若被拆成两个 budget 会 ~4s+
    assert elapsed < 5.0, f"total elapsed {elapsed:.2f}s 超出单一 deadline 允许范围"
    assert _wait_poll(cap["proc"]) is not None          # 进程树已终止
    _assert_no_cli_threads_alive()                       # stdin writer + stdout pump 均死
    assert sem._value == 1                               # 信号量释放
    assert dirs and not os.path.exists(dirs[0])          # 临时目录已删除


def test_deadline_not_reset_for_stdout(monkeypatch):
    """stdin 快速完成 + stdout 持续输出：stdout 消费必须继续消费同一 deadline，
    不得在 stdin 阶段后重置 300s。"""
    _register_fake(monkeypatch, code="import time\nfor i in range(20):\n    print('x' * 1000, flush=True)\n    time.sleep(0.1)\ntime.sleep(30)")
    monkeypatch.setattr(cli_runtime, "CLI_TOTAL_DEADLINE_SECONDS", 2)
    sem = _fresh_sem(monkeypatch, value=1)
    cap = _capture_popen(monkeypatch)

    started = time.monotonic()
    with pytest.raises(cli_runtime.CliTimeout):
        for _ in cli_runtime.run_cli_stream("fake", "s", "u"):
            pass
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"stdout 阶段重置了 deadline：{elapsed:.2f}s"
    assert _wait_poll(cap["proc"]) is not None
    _assert_no_cli_threads_alive()
    assert sem._value == 1


# ---------- BLOCKER B：真实 POSIX 进程树终止（不 mock killpg） ----------

_TREE_CODE_POSIX = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print('spawned', child.pid, flush=True)\n"
    "time.sleep(120)\n"
)

_TREE_CODE_POSIX_FLOOD = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print('spawned', child.pid, flush=True)\n"
    "for i in range(100):\n"
    "    print('x' * 1000, flush=True)\n"
    "time.sleep(120)\n"
)


def _run_posix_tree(monkeypatch, code, *, deadline_s=None, limit=None, cancel=None):
    """spawn 真实 parent→child 树，返回 (captured_proc, child_pid)。不 mock killpg。"""
    _register_fake(monkeypatch, code=code)
    if deadline_s is not None:
        monkeypatch.setattr(cli_runtime, "CLI_TOTAL_DEADLINE_SECONDS", deadline_s)
    if limit is not None:
        monkeypatch.setattr(cli_runtime, "CLI_OUTPUT_LIMIT_BYTES", limit)
    cap = _capture_popen(monkeypatch)
    child_pid = None

    def consume(gen):
        nonlocal child_pid
        for line in gen:
            if line.startswith("spawned"):
                child_pid = int(line.split()[1])

    if cancel is not None:
        stream = cli_runtime.run_cli_stream("fake", "s", "u", cancel_event=cancel)
        for line in stream:
            if line.startswith("spawned"):
                child_pid = int(line.split()[1])
                break
        assert child_pid is not None
        cancel.set()
        with pytest.raises(cli_runtime.CliError, match="取消"):
            for _ in stream:
                pass
    elif deadline_s is not None:
        with pytest.raises(cli_runtime.CliTimeout):
            consume(cli_runtime.run_cli_stream("fake", "s", "u"))
    elif limit is not None:
        with pytest.raises(cli_runtime.CliOutputLimit):
            consume(cli_runtime.run_cli_stream("fake", "s", "u"))
    assert child_pid is not None
    return cap, child_pid


@pytest.mark.skipif(os.name != "posix", reason="真实 POSIX 进程树验证（ubuntu CI）")
def test_posix_real_cancel_kills_full_tree(monkeypatch):
    cap, child_pid = _run_posix_tree(
        monkeypatch, _TREE_CODE_POSIX, cancel=threading.Event()
    )
    assert _wait_poll(cap["proc"]) is not None       # parent dead
    assert _posix_wait_dead(child_pid)               # child dead
    _assert_no_cli_threads_alive()


@pytest.mark.skipif(os.name != "posix", reason="真实 POSIX 进程树验证（ubuntu CI）")
def test_posix_real_timeout_kills_full_tree(monkeypatch):
    cap, child_pid = _run_posix_tree(
        monkeypatch, _TREE_CODE_POSIX, deadline_s=2
    )
    assert _wait_poll(cap["proc"]) is not None
    assert _posix_wait_dead(child_pid)
    _assert_no_cli_threads_alive()


@pytest.mark.skipif(os.name != "posix", reason="真实 POSIX 进程树验证（ubuntu CI）")
def test_posix_real_output_limit_kills_full_tree(monkeypatch):
    cap, child_pid = _run_posix_tree(
        monkeypatch, _TREE_CODE_POSIX_FLOOD, limit=1000
    )
    assert _wait_poll(cap["proc"]) is not None
    assert _posix_wait_dead(child_pid)
    _assert_no_cli_threads_alive()


# ---------- BLOCKER C：/api/chat HTTP disconnect → cancel → 进程树清理 ----------

def test_chat_cli_http_disconnect_propagates_cancel(monkeypatch):
    """/api/chat 的 CLI 订阅接入：真实 ASGI disconnect 必须传播 cancel_event，
    终止进程树并清理（与 /api/daily-review/analyze 对齐）。"""
    import asyncio
    import json

    import app as app_module

    _register_fake(monkeypatch, code="import time\nprint('chunk', flush=True)\ntime.sleep(30)")
    _authorize_fake(monkeypatch)
    monkeypatch.setattr(cli_runtime, "CLI_TOTAL_DEADLINE_SECONDS", 30)  # 靠 cancel 终止，不靠 deadline
    sem = _fresh_sem(monkeypatch, value=1)
    real_popen = cli_runtime.subprocess.Popen
    captured = {}

    def capture_popen(*args, **kwargs):
        argv = args[0] if args else []
        if argv and os.path.basename(str(argv[0])).lower().startswith("taskkill"):
            return real_popen(*args, **kwargs)
        proc = real_popen(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(cli_runtime.subprocess, "Popen", capture_popen)

    body = json.dumps({
        "messages": [{"role": "user", "content": "hi"}],
        "context": "",
        "llm": {"provider": "cli-fake", "model": "local-test", "baseURL": "", "apiKey": ""},
    }).encode("utf-8")

    async def exercise_disconnect():
        first_body_sent = asyncio.Event()
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await first_body_sent.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                first_body_sent.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/chat",
            "raw_path": b"/api/chat",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "state": {},
        }
        await app_module.app(scope, receive, send)

    started = time.monotonic()
    asyncio.run(exercise_disconnect())
    elapsed = time.monotonic() - started

    # disconnect 后 request 必须快速返回（cancel 传播，不等到 30s deadline）
    assert elapsed < 5.0, f"disconnect 未及时传播 cancel：{elapsed:.2f}s"
    proc = captured["proc"]
    assert _wait_poll(proc) is not None        # CLI parent dead
    assert proc.stdin.closed                   # stdin closed
    assert proc.stdout.closed                  # stdout closed
    _assert_no_cli_threads_alive()             # writer + pump 均死
    assert sem._value == 1                     # semaphore released
