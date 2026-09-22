"""本机后端启动快照；只读，不查询账户、行情、凭据或 AI sidecar。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Response

_SOURCE_DIRECTORY = Path(__file__).resolve().parent.parent


def _git_snapshot(source_directory: Path) -> tuple[str | None, str]:
    try:
        # 不让源码归档误认外层仓库为本服务版本；.git 文件也支持 Git worktree。
        if not (source_directory / ".git").exists():
            return None, "unknown"
        result = subprocess.run(
            [
                "git", "--no-optional-locks", "-C", str(source_directory),
                "status", "--porcelain=v2", "--branch", "--untracked-files=normal",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return None, "unknown"
        lines = result.stdout.splitlines()
        sha = next((line.removeprefix("# branch.oid ") for line in lines if line.startswith("# branch.oid ")), "")
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha):
            return None, "unknown"
        modified = any(line and not line.startswith("# ") for line in lines)
        return sha, "modified" if modified else "clean"
    except (OSError, subprocess.SubprocessError):
        # Git 不在 PATH、无权限、超时等均不影响服务启动，也不回传 stderr。
        return None, "unknown"


def create_router(version: str) -> APIRouter:
    """在 app 导入时采集一次；请求期间不读 Git，避免报告后来切换的 HEAD。"""
    sha, source_state = _git_snapshot(_SOURCE_DIRECTORY)
    try:
        working_directory = str(Path.cwd())
    except OSError:
        working_directory = None
    # 明确字段白名单；不返回环境变量、Git 输出/远端、进程参数或错误详情。
    snapshot = {
        "service": "vibe-research-api",
        "version": version,
        "git_sha": sha,
        "source_state": source_state,
        "source_directory": str(_SOURCE_DIRECTORY),
        "working_directory": working_directory,
    }
    router = APIRouter(prefix="/api", tags=["runtime-info"])

    @router.get("/runtime-info")
    def runtime_info(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {"data": snapshot}

    return router
