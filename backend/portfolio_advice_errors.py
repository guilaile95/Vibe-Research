"""持仓建议错误类型与模型失败对外文案分类。"""

from __future__ import annotations


class PortfolioAdviceValidationError(ValueError):
    """结构化结果无法校验时抛出。"""


# 对外 502 文案（固定安全字符串，不回传上游原始 body / 密钥）
MODEL_ERR_GENERIC = "持仓建议模型调用失败"
MODEL_ERR_AUTH = "持仓建议模型鉴权失败，请检查 API Key 或重新登录 CLI"
MODEL_ERR_NETWORK = "持仓建议模型网络调用失败，请检查网络后重试"
MODEL_ERR_CONFIG = "持仓建议模型配置无效，请检查 Base URL 与模型名"
MODEL_ERR_CLI = "未检测到本机 CLI，请先安装并登录，或改用 API 接入"
MODEL_ERR_CLI_RUN = "持仓建议 CLI 调用失败，请确认已登录对应 CLI 后重试"
MODEL_ERR_OUTPUT = "持仓建议模型输出无效"

_PUBLIC_MODEL_MESSAGES = frozenset(
    {
        MODEL_ERR_GENERIC,
        MODEL_ERR_AUTH,
        MODEL_ERR_NETWORK,
        MODEL_ERR_CONFIG,
        MODEL_ERR_CLI,
        MODEL_ERR_CLI_RUN,
        MODEL_ERR_OUTPUT,
    }
)


def _iter_exception_chain(exc: BaseException | None) -> list[BaseException]:
    """收集异常链（含 cause/context），用于安全分类，不向外暴露原文。"""
    out: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        out.append(cur)
        seen.add(id(cur))
        nxt = cur.__cause__ if cur.__cause__ is not None else cur.__context__
        cur = nxt if isinstance(nxt, BaseException) else None
    return out


def public_model_error_detail(exc: BaseException | None) -> str:
    """将模型/CLI 失败映射为固定、可展示的 502 文案（不泄露密钥/路径/上游 body）。

    分类优先级：CLI 未安装 → 鉴权 → 配置 → 网络 → CLI 运行失败 → 通用模型失败。
    """
    if exc is None:
        return MODEL_ERR_GENERIC

    # 已是本服务包装过的公开安全文案：直接复用（按类名判断，避免循环导入）
    if type(exc).__name__ == "PortfolioAdviceModelError":
        msg = str(exc).strip()
        if msg in _PUBLIC_MODEL_MESSAGES:
            return msg

    chain = _iter_exception_chain(exc)
    texts = " ".join(str(x) for x in chain)
    lower = texts.lower()

    # 1) 本机 CLI 未安装 / 不在 PATH
    try:
        import cli_runtime as _cli_runtime  # 局部导入，避免循环依赖噪音

        for x in chain:
            if isinstance(x, _cli_runtime.CliUnavailable):
                raw = str(x).strip()
                # CliUnavailable 文案本身无密钥，可截断后返回
                if raw and "未检测到" in raw:
                    return raw[:200]
                return MODEL_ERR_CLI
    except Exception:  # noqa: BLE001
        pass
    if "未检测到" in texts and ("本机命令" in texts or "cli" in lower):
        raw = next((str(x).strip() for x in chain if "未检测到" in str(x)), "")
        return raw[:200] if raw else MODEL_ERR_CLI

    # 2) 鉴权失败（假 key / 401 / 未登录）
    auth_markers = (
        "authentication",
        "unauthorized",
        "invalid api key",
        "invalid_api_key",
        "api key",
        "not logged",
        "please login",
        "请先登录",
        "重新登录",
    )
    if any(m in lower for m in auth_markers) or "鉴权" in texts:
        return MODEL_ERR_AUTH
    if (
        "http 401" in lower
        or "http 403" in lower
        or "status_code=401" in lower
        or "status_code=403" in lower
        or " 401:" in texts
        or " 403:" in texts
    ):
        return MODEL_ERR_AUTH

    # 3) Base URL / 模型配置类
    if "base url" in lower or "baseurl" in lower.replace(" ", ""):
        return MODEL_ERR_CONFIG

    # 4) 网络 / 超时
    net_markers = (
        "timed out",
        "timeout",
        "time-out",
        "connection",
        "network",
        "name or service not known",
        "failed to resolve",
        "max retries",
        "temporarily unavailable",
        "连接",
        "网络",
    )
    if (
        any(m in lower for m in net_markers)
        or "http 502" in lower
        or "http 503" in lower
        or "http 504" in lower
    ):
        return MODEL_ERR_NETWORK

    # 5) CLI 已检测到但运行失败（退出码等）
    if "退出码" in texts or ("cli" in lower and ("exit" in lower or "returncode" in lower)):
        return MODEL_ERR_CLI_RUN

    return MODEL_ERR_GENERIC
