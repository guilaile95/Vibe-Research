"""订阅接入：调本机已装、已登录的 AI CLI（Claude Code / Qwen / DeepSeek / Codex），
用用户自己的订阅额度作答、免 API key。移植自 SDesign-opensource 的 cli-runtime（Node），
改为 Python subprocess。

安全边界（P0-SEC2 v0.1，见 docs/p0/CLI_SECURITY_V01.md）：
- HTTP 可达 CLI 执行默认禁用：须同时满足 VR_ENABLE_LOCAL_CLI=1（显式 opt-in）、
  VR_API_KEY 非空（已鉴权）、且该 provider 已证明 no-tools 纯文本（registry 里
  http_allowed=True；当前四个 provider 全部 NOT_PROVEN → fail-closed 拒绝）。
- 子进程环境走显式 allowlist，绝不继承完整 os.environ；凭证由 CLI 自持
  （opencode 模式：CLI 读自己的本机 auth 文件 / keyring，父进程不传递任何 API key）。
- 组合输入（system+user）UTF-8 字节预算、stdout 字节预算（stream 与 non-stream 同限）、
  有界队列、全局并发信号量、总 wall-clock 截止时间、进程树终止
  （Windows taskkill /T /F；POSIX start_new_session + killpg）。
- 错误对外只暴露固定公开分类 code（CLI_*），不泄露路径 / argv / 环境 / 输出 / 凭证。
- shell=False 恒定；可执行文件只来自固定 provider registry + detect_cli，
  用户不得注入 binary path / 任意 argv / shell 字符串。

⚠️ 仅当后端跑在用户本机时可用——云端读不到用户本机的 CLI 与登录态。
CLI 不做 function-calling（不像 API 那条能让 AI 自己调数据工具）；因此订阅接入只适合
「数据已在提示词里」的场景（每日复盘 / 今日要点 / 个股页问 AI，页面已把数据塞进 context）。
"""

from __future__ import annotations

import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# ================= 安全常量（P0-SEC2 v0.1 frozen） =================

# HTTP 可达 CLI 执行门：默认关闭（fail-closed）。
VR_ENABLE_LOCAL_CLI = os.environ.get("VR_ENABLE_LOCAL_CLI", "").strip() == "1"
VR_API_KEY = os.environ.get("VR_API_KEY", "").strip()

CLI_INPUT_LIMIT_BYTES = 500_000      # 组合输入（system+user）UTF-8 字节上限，spawn 前拒绝
CLI_OUTPUT_LIMIT_BYTES = 1_000_000   # MAX_STDOUT_BYTES：stdout 累计上限，超限终止进程树
CLI_QUEUE_MAXSIZE = 256              # 流式 stdout 队列上限（bounded）
CLI_MAX_CONCURRENT_PROCESSES = 2     # 全局 CLI 进程并发上限（run_cli 与 run_cli_stream 共享）
CLI_CONCURRENCY_ACQUIRE_TIMEOUT = 10.0  # 并发槽获取超时（秒），超时抛 CLI_BUSY
CLI_TOTAL_DEADLINE_SECONDS = 300     # 单次执行总 wall-clock 截止（覆盖 start/stdin/stdout/exit）

# 子进程最小环境 allowlist：只传运行 CLI 与定位其本机登录态（opencode 模式）所需变量。
# 不继承任何 *_KEY / *_TOKEN / *_SECRET / *_PASSWORD / DATABASE_URL / DB_URL / proxy 变量。
# PROXY_ENV_INHERITANCE = NO（CLI 联网走各自配置，不复制父进程 proxy，避免 credential URL 泄漏）。
_CHILD_ENV_ALLOWLIST = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
    "LANG", "LC_ALL", "LC_CTYPE",
})

# 提示词投递方式（各 CLI 接口不同）：
#   system-file —— 系统提示词写临时文件用 flag 传，用户提示词走 stdin（Claude）
#   stdin       —— 系统+用户合并走 stdin（Qwen / Codex）
#   arg         —— 系统+用户合并作为最后一个位置参数（DeepSeek）
_CLI_DEFS: dict[str, dict] = {
    "claude": {
        "bins": ["claude", "openclaude"],
        "delivery": "system-file",
        # -p 非交互、纯文本输出、系统提示词走文件；禁掉所有工具（只让它把问题答成文字，不读文件/联网/执行）
        "build_args": lambda sys_file: [
            "-p", "--output-format", "text", "--system-prompt-file", sys_file,
            "--disallowedTools", "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "NotebookEdit", "WebFetch", "WebSearch", "TodoWrite", "Task",
        ],
        "env": {},
    },
    "qwen": {"bins": ["qwen"], "delivery": "stdin", "build_args": lambda _: ["--yolo"], "env": {}},
    # 注：Gemini CLI 已停止对个人版 Gemini Code Assist 的支持（登录报 "This client is no
    # longer supported for Gemini Code Assist for individuals"），故已从订阅接入中移除。
    "deepseek": {"bins": ["deepseek", "codewhale"], "delivery": "arg",
                 "build_args": lambda _: ["exec", "--auto"], "env": {}},
    # Codex：codex exec 默认纯文本（进度走 stderr、最终答案走 stdout）；`-` 从 stdin 读提示词，
    # --skip-git-repo-check 跳过 git 检查（我们在临时目录跑）。复用本机 `codex login` 的订阅登录态。
    "codex": {"bins": ["codex"], "delivery": "stdin",
              "build_args": lambda _: ["exec", "--skip-git-repo-check", "-"], "env": {}},
}

_EXTRA_PATH_DIRS = [
    "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
    str(Path.home() / ".local/bin"), str(Path.home() / ".npm-global/bin"),
    str(Path.home() / ".bun/bin"), str(Path.home() / ".deno/bin"),
    str(Path.home() / ".yarn/bin"),
]

_MAX_ARG_BYTES = 110_000  # 位置参数投递的提示词字节上限（provider-specific，DeepSeek 保留更严限制）

# 全局并发槽：run_cli 与 run_cli_stream 共享，不按 provider 各自独立 unlimited。
_PROC_SEM = threading.BoundedSemaphore(CLI_MAX_CONCURRENT_PROCESSES)


# ================= 错误（固定公开分类，不含敏感信息） =================

class CliError(RuntimeError):
    """CLI 执行失败基类。code 为固定公开分类；str() 不含路径/argv/环境/输出/凭证。"""

    code = "CLI_FAILED"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


class CliUnavailable(CliError):
    """本机未检测到对应 CLI（未安装 / 不在 PATH）。"""

    code = "CLI_UNAVAILABLE"


class CliExecutionDisabled(CliError):
    """HTTP 可达 CLI 执行被安全门拦截（未 opt-in / 未鉴权 / provider 未证明 no-tools）。"""

    code = "CLI_EXECUTION_DISABLED"


class CliTimeout(CliError):
    """总 wall-clock 截止时间到，进程树已终止。"""

    code = "CLI_TIMEOUT"


class CliOutputLimit(CliError):
    """stdout 超过字节上限，进程树已终止。"""

    code = "CLI_OUTPUT_LIMIT"


class CliBusy(CliError):
    """全局并发槽获取超时。"""

    code = "CLI_BUSY"


class CliInputLimit(CliError):
    """组合输入超过字节上限（spawn 前 fail-closed 拒绝）。"""

    code = "CLI_FAILED"


class _StreamReadFailure:
    pass


# ================= Provider 安全能力注册表 =================

# text_only_proven=False 表示尚无官方文档/实测证明其可严格 no-tools 纯文本输出
# （agent 工具路径实际不可调用）。http_allowed 必须保持 False 直到 proven（fail-closed）。
# 证据（2026-08 审计）：
#   claude   2.1.226 有 --allowedTools（allowlist）+ --permission-mode dontAsk + --safe-mode，
#           但空 allowlist 未在本机完成 argv 实测 → NOT_PROVEN
#   qwen     v0.21.10 有 --exclude-tools（需显式枚举、无通配），无单一 no-tools 开关 → NOT_PROVEN
#   deepseek 官方无 CLI；codewhale 为社区项目，--disallowed-tools 通配未官方背书 → NOT_PROVEN
#   codex    rust-v0.147.0 有 --disable shell_tool + --sandbox read-only，但 read-only≠no-tools → NOT_PROVEN
CLI_SECURITY_CAPABILITIES: dict[str, dict] = {
    "claude":   {"text_only_proven": False, "proof_mode": "NOT_PROVEN", "http_allowed": False},
    "qwen":     {"text_only_proven": False, "proof_mode": "NOT_PROVEN", "http_allowed": False},
    "deepseek": {"text_only_proven": False, "proof_mode": "NOT_PROVEN", "http_allowed": False},
    "codex":    {"text_only_proven": False, "proof_mode": "NOT_PROVEN", "http_allowed": False},
}

_EXECUTION_DISABLED_MESSAGE = "本地 CLI 执行未启用"


def assert_http_cli_authorized(kind: str) -> None:
    """HTTP 可达 CLI 执行门（fail-closed）：任一条件不满足即抛 CliExecutionDisabled。

    三个条件缺一不可：
    1. VR_ENABLE_LOCAL_CLI=1（显式 opt-in）
    2. VR_API_KEY 非空（部署已鉴权；loopback + 无 key 不允许 HTTP → process launch）
    3. CLI_SECURITY_CAPABILITIES[kind]["http_allowed"] 为 True（provider 已证明 no-tools）
    """
    if not VR_ENABLE_LOCAL_CLI or not VR_API_KEY:
        raise CliExecutionDisabled(_EXECUTION_DISABLED_MESSAGE)
    cap = CLI_SECURITY_CAPABILITIES.get(kind)
    if cap is None or not cap.get("http_allowed", False):
        raise CliExecutionDisabled(_EXECUTION_DISABLED_MESSAGE)


def _build_child_env(extra: dict | None) -> dict:
    """子进程环境：显式 allowlist + provider contract 追加；绝不继承完整 os.environ。"""
    env: dict[str, str] = {}
    for key in _CHILD_ENV_ALLOWLIST:
        val = os.environ.get(key)
        if val:
            env[key] = val
    for key, val in (extra or {}).items():
        if val is not None:
            env[key] = val
    return env


def _find_bin(name: str) -> str | None:
    hit = shutil.which(name)
    if hit:
        return hit
    for d in _EXTRA_PATH_DIRS:
        p = Path(d) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def detect_cli(kind: str) -> str | None:
    """返回某订阅 CLI 的可执行路径，未装则 None。"""
    d = _CLI_DEFS.get(kind)
    if not d:
        return None
    for b in d["bins"]:
        found = _find_bin(b)
        if found:
            return found
    return None


def supported_kinds() -> list[str]:
    return list(_CLI_DEFS.keys())


def _check_input_budget(system_prompt: str, user_prompt: str) -> None:
    """组合输入 UTF-8 字节预算：system + user 统一计数，spawn 前 fail-closed 拒绝（不截断）。"""
    total = len(system_prompt.encode("utf-8")) + len(user_prompt.encode("utf-8"))
    if total > CLI_INPUT_LIMIT_BYTES:
        raise CliInputLimit("提示词过长，超出本地 CLI 输入上限")


def _acquire_slot() -> None:
    if not _PROC_SEM.acquire(timeout=CLI_CONCURRENCY_ACQUIRE_TIMEOUT):
        raise CliBusy("本地 CLI 并发已满，请稍后重试")


def _release_slot() -> None:
    _PROC_SEM.release()


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止整个进程树：Windows 用 taskkill /T /F；POSIX 用 killpg。

    绝不只杀父进程留下孤儿 CLI / 工具子进程；proc 已退出时直接返回。
    防御性约束：POSIX 下若子进程未能脱离宿主进程组（start_new_session 失效或
    异常），绝不 killpg 当前进程组（那会误杀宿主 runner），降级为单进程 kill。
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # 用系统原生 taskkill 递归杀树（本调用不继承受限子进程环境）
            subprocess.run(
                ["taskkill", "/pid", str(proc.pid), "/t", "/f"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        else:
            pgid = os.getpgid(proc.pid)
            if pgid == os.getpgrp():
                # 子进程仍在宿主进程组：killpg 会误杀宿主，改用单进程 kill
                proc.kill()
            else:
                os.killpg(pgid, signal.SIGKILL)
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _close_pipes(proc: subprocess.Popen, stdin_closed: bool) -> None:
    # stdin 若已关闭则只处理 stdout（幂等，不依赖 pipe.closed 属性）
    pipes = (proc.stdout,) if stdin_closed else (proc.stdin, proc.stdout)
    for pipe in pipes:
        if pipe is None:
            continue
        close = getattr(pipe, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                pass


def _bounded_put(q: queue.Queue, item, stop_event: threading.Event) -> None:
    """有界队列 put：队列满时定时重试；stop_event 置位即放弃，pump 线程不会死锁。"""
    while not stop_event.is_set():
        try:
            q.put(item, timeout=0.5)
            return
        except queue.Full:
            continue


def _run_cli_impl(kind, system_prompt, user_prompt, *, via_http, cancel_event):
    """CLI 执行核心（生成器）：授权 → 输入预算 → 并发槽 → 进程树 → 有界输出 → 清理。

    yield 纯文本 stdout 块；任何失败抛 CliError 子类并保证进程树终止、槽位释放、临时目录清理。
    """
    if via_http:
        assert_http_cli_authorized(kind)

    d = _CLI_DEFS.get(kind)
    bin_path = detect_cli(kind)
    if not d or not bin_path:
        raise CliUnavailable(
            f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。"
        )

    _check_input_budget(system_prompt, user_prompt)

    combined = f"{system_prompt}\n\n{user_prompt}"
    tmpdir = tempfile.mkdtemp(prefix="vibe-cli-")
    proc = None
    reader_thread = None
    stop_event = threading.Event()
    acquired = False
    stdin_closed = False
    try:
        if d["delivery"] == "system-file":
            sys_file = str(Path(tmpdir) / "system.txt")
            Path(sys_file).write_text(system_prompt, encoding="utf-8")
            args = d["build_args"](sys_file)
            stdin_payload = user_prompt
        elif d["delivery"] == "stdin":
            args = d["build_args"](None)
            stdin_payload = combined
        else:  # arg
            if len(combined.encode("utf-8")) > _MAX_ARG_BYTES:
                raise CliInputLimit("提示词过长，超出本地 CLI 输入上限")
            args = [*d["build_args"](None), combined]
            stdin_payload = None

        _acquire_slot()
        acquired = True

        popen_kwargs: dict = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # stderr 不暴露给客户端
            cwd=tmpdir,
            env=_build_child_env(d.get("env")),
            text=True,
            bufsize=1,
        )
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True  # POSIX：独立进程组，便于 killpg
        proc = subprocess.Popen([bin_path, *args], **popen_kwargs)

        if stdin_payload is not None:
            # deadline 覆盖 stdin delivery：写入放独立线程，主线程用总 wall-clock
            # 截止时间兜底——CLI 不读 stdin 时 write 会阻塞，不能卡死在主线程。
            def _write_stdin():
                try:
                    proc.stdin.write(stdin_payload)
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass

            writer = threading.Thread(
                target=_write_stdin,
                name=f"vibe-cli-{kind}-stdin",
                daemon=True,
            )
            writer.start()
            writer.join(timeout=CLI_TOTAL_DEADLINE_SECONDS)
            stdin_closed = True
        elif proc.stdin is not None:
            proc.stdin.close()
            stdin_closed = True

        q: queue.Queue = queue.Queue(maxsize=CLI_QUEUE_MAXSIZE)

        def _pump():
            try:
                for ln in proc.stdout:
                    if stop_event.is_set():
                        break  # 清理已开始：停止读行，避免 busy-loop 空转
                    _bounded_put(q, ln, stop_event)
                if not stop_event.is_set():
                    _bounded_put(q, None, stop_event)  # EOF 哨兵
            except Exception:
                if not stop_event.is_set():
                    try:
                        _bounded_put(q, _StreamReadFailure(), stop_event)
                    except Exception:
                        pass

        reader_thread = threading.Thread(
            target=_pump,
            name=f"vibe-cli-{kind}-stdout",
            daemon=True,
        )
        reader_thread.start()

        deadline = time.monotonic() + CLI_TOTAL_DEADLINE_SECONDS
        total_out = 0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CliError(f"{kind} 生成已取消")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CliTimeout(f"{kind} 生成超时")
            try:
                poll_interval = 0.05 if cancel_event is not None else 1.0
                line = q.get(timeout=min(remaining, poll_interval))
            except queue.Empty:
                continue
            if line is None:
                break
            if isinstance(line, _StreamReadFailure):
                raise CliError(f"{kind} 输出读取失败")
            total_out += len(line.encode("utf-8"))
            if total_out > CLI_OUTPUT_LIMIT_BYTES:
                raise CliOutputLimit(f"{kind} 输出超过上限")
            yield line

        try:
            rc = proc.wait(timeout=min(10.0, max(0.1, deadline - time.monotonic())))
        except subprocess.TimeoutExpired as e:
            raise CliError(f"{kind} 输出已结束但进程未退出") from e
        if rc != 0:
            raise CliError(f"{kind} 退出码 {rc}")
    finally:
        stop_event.set()  # 通知 pump 停止放入
        if proc is not None:
            _terminate_process_tree(proc)
            _close_pipes(proc, stdin_closed)
        if reader_thread is not None and reader_thread.is_alive():
            reader_thread.join(timeout=10)
        if acquired:
            _release_slot()
        shutil.rmtree(tmpdir, ignore_errors=True)


def run_cli(kind: str, system_prompt: str, user_prompt: str, *, via_http: bool = False) -> str:
    """起 CLI 子进程，一次性作答，返回纯文本 stdout。失败抛 CliError 子类。

    via_http=True 表示调用来自 HTTP 可达路径，须先通过执行门（见 assert_http_cli_authorized）。
    """
    return "".join(
        _run_cli_impl(kind, system_prompt, user_prompt, via_http=via_http, cancel_event=None)
    ).strip()


def run_cli_stream(
    kind: str,
    system_prompt: str,
    user_prompt: str,
    *,
    via_http: bool = False,
    cancel_event=None,
):
    """流式版：起 CLI 子进程，stdout 边出边 yield 纯文本块。失败抛 CliError 子类。

    via_http=True 表示调用来自 HTTP 可达路径，须先通过执行门（见 assert_http_cli_authorized）。
    """
    yield from _run_cli_impl(
        kind,
        system_prompt,
        user_prompt,
        via_http=via_http,
        cancel_event=cancel_event,
    )
