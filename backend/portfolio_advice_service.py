"""持仓操作建议 AI 编排服务（读取持仓 + 每日复盘 → 上下文 → 模型 → 校验）。

本模块只做编排，不复制 context / prompt / validator 业务规则。
不修改 portfolio.json、不写历史、不提供 HTTP API。
第一版不支持做 T。
"""

from __future__ import annotations

import json
from typing import Any, Callable

import chat
import daily_review
import portfolio
import portfolio_advice_context
import portfolio_advice_prompt
import portfolio_advice_validator
from portfolio_advice_validator import PortfolioAdviceValidationError

ModelRunner = Callable[[Any, list[dict[str, str]]], str]


class PortfolioAdviceUnavailableError(ValueError):
    """无有效持仓等业务前置条件不满足。"""


class PortfolioAdviceMarketDataError(RuntimeError):
    """市场核心数据（如广度）不可用，拒绝生成持仓建议。"""


class PortfolioAdviceModelError(RuntimeError):
    """模型调用或流式协议失败。"""


class PortfolioAdviceModelOutputError(ValueError):
    """模型输出无法解析或未通过结构/执行约束校验。"""


_EMPTY_HOLDINGS_MSG = "当前没有持仓，无法生成持仓操作建议"
_EMPTY_OUTPUT_MSG = "持仓建议模型未返回有效内容"
_INVALID_JSON_MSG = "持仓建议模型输出不是有效的JSON对象"
_VALIDATOR_FAIL_MSG = "持仓建议模型输出未通过结构和执行约束校验"
_MARKET_UNAVAILABLE_MSG = "市场核心数据暂不可用，无法生成可靠的持仓操作建议"


def _normalize_user_request(user_request: Any) -> str | None:
    if user_request is None:
        return None
    if not isinstance(user_request, str):
        raise TypeError("user_request 必须是字符串或None")
    stripped = user_request.strip()
    return stripped if stripped else None


def _require_holdings(portfolio_data: dict) -> None:
    holdings = portfolio_data.get("holdings") if isinstance(portfolio_data, dict) else None
    if not isinstance(holdings, list) or len(holdings) == 0:
        raise PortfolioAdviceUnavailableError(_EMPTY_HOLDINGS_MSG)


def _context_to_json(context: dict) -> str:
    """与 render_portfolio_advice_context 相同序列化约定（不二次调用 builder）。"""
    return json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )


def _market_breadth_unavailable(review: dict) -> bool:
    """市场广度组件是否不可用（失败关闭用）。"""
    if not isinstance(review, dict):
        return True
    health = review.get("data_health") if isinstance(review.get("data_health"), dict) else {}
    comps = health.get("components") if isinstance(health.get("components"), dict) else {}
    if comps.get("breadth") == "unavailable":
        return True
    me = review.get("market_environment") if isinstance(review.get("market_environment"), dict) else {}
    breadth = me.get("breadth") if isinstance(me.get("breadth"), dict) else {}
    if breadth.get("status") == "unavailable":
        return True
    return False


def prepare_portfolio_advice_messages(
    user_request: str | None = None,
) -> dict:
    """读取持仓与每日复盘，构建上下文与模型 messages（不调用模型）。

    Returns
    -------
    dict
        ``portfolio`` / ``daily_review`` / ``context`` / ``context_json`` / ``messages``
        仅供后端内部编排与测试使用。

    Raises
    ------
    PortfolioAdviceMarketDataError
        市场广度 unavailable 时，不构建 messages、不调用模型。
    """
    request = _normalize_user_request(user_request)

    portfolio_data = portfolio.get_portfolio()
    if not isinstance(portfolio_data, dict):
        raise PortfolioAdviceUnavailableError(_EMPTY_HOLDINGS_MSG)
    _require_holdings(portfolio_data)

    review = daily_review.generate_daily_review()
    if _market_breadth_unavailable(review):
        raise PortfolioAdviceMarketDataError(_MARKET_UNAVAILABLE_MSG)

    context = portfolio_advice_context.build_portfolio_advice_context(
        portfolio_data,
        review,
    )
    context_json = _context_to_json(context)
    messages = portfolio_advice_prompt.build_portfolio_advice_messages(
        context_json,
        user_request=request,
    )
    return {
        "portfolio": portfolio_data,
        "daily_review": review,
        "context": context,
        "context_json": context_json,
        "messages": messages,
    }


def _strip_single_fence(stripped: str) -> str | None:
    """若整段为单层完整 Markdown 代码块，返回内部正文；否则返回 None。

    仅识别开头整行 ```` / ````json / ````JSON` 且结尾为 ````。
    无法完整剥离时返回 None，由调用方按纯 JSON 或失败处理。
    """
    if not stripped.startswith("```"):
        return None
    # 必须以 ``` 结尾（strip 后），且中间至少有内容分隔
    if stripped == "```" or not stripped.endswith("```"):
        return None
    first_nl = stripped.find("\n")
    if first_nl < 0:
        # 单行 ```...``` 不允许（非「整行 fence」约定）
        return None
    first_line = stripped[:first_nl]
    # first_line 只能是 ``` 或 ```json / ```JSON（大小写）
    lang = first_line[3:].strip()
    if lang and lang.lower() != "json":
        return None
    # 去掉开头 fence 行与结尾 ```
    inner_with_close = stripped[first_nl + 1 :]
    # 结尾的 ``` 必须独占尾部（允许其前空白）
    close_idx = inner_with_close.rfind("```")
    if close_idx < 0:
        return None
    # 结尾 ``` 之后不得再有非空白
    after = inner_with_close[close_idx + 3 :]
    if after.strip():
        return None
    # 结尾 ``` 之前若还有内容后的尾随空白可保留给 strip
    # 但 close 必须是最后一个 fence；中间不应再出现未配对逻辑——
    # 约定：最后三个反引号为关闭符，其前全部为 body。
    body = inner_with_close[:close_idx]
    return body


def _parse_model_json(text: Any) -> dict:
    """严格解析模型完整文本为 JSON 对象。

    允许：纯 JSON；单层 ``` / ```json / ```JSON 代码块。
    拒绝：前后说明文字、数组顶层、单引号、截断、多对象等。
    """
    if text is None:
        raise PortfolioAdviceModelOutputError(_EMPTY_OUTPUT_MSG)
    if not isinstance(text, str):
        raise PortfolioAdviceModelOutputError(_INVALID_JSON_MSG)

    stripped = text.strip()
    if not stripped:
        raise PortfolioAdviceModelOutputError(_EMPTY_OUTPUT_MSG)

    body: str
    if stripped.startswith("```"):
        inner = _strip_single_fence(stripped)
        if inner is None:
            raise PortfolioAdviceModelOutputError(_INVALID_JSON_MSG)
        body = inner.strip()
        if not body:
            raise PortfolioAdviceModelOutputError(_EMPTY_OUTPUT_MSG)
    else:
        body = stripped

    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise PortfolioAdviceModelOutputError(_INVALID_JSON_MSG) from None

    if not isinstance(obj, dict):
        raise PortfolioAdviceModelOutputError(_INVALID_JSON_MSG)
    return obj


def _safe_error_message(exc: BaseException, *, fallback: str) -> str:
    """生成不含密钥/路径等敏感信息的短错误说明。"""
    name = type(exc).__name__
    raw = str(exc) if exc is not None else ""
    # 粗略过滤常见敏感片段
    lower = raw.lower()
    if any(
        k in lower
        for k in (
            "api-key",
            "apikey",
            "api_key",
            "authorization",
            "bearer ",
            "sk-",
        )
    ):
        return f"{fallback}（{name}）"
    # 截断，避免把大段持仓/请求塞进异常
    msg = raw.replace("\n", " ").strip()
    if len(msg) > 200:
        msg = msg[:200] + "…"
    if not msg:
        return f"{fallback}（{name}）"
    return f"{fallback}：{msg}"


def _default_model_runner(cfg: Any, messages: list[dict[str, str]]) -> str:
    """复用 chat.stream_messages(use_tools=False) 收集完整文本。"""
    parts: list[str] = []
    try:
        for event in chat.stream_messages(cfg, messages, use_tools=False):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "delta":
                # 按事件顺序原样拼接，不 trim、不去重
                piece = event.get("text")
                if piece is None:
                    continue
                if not isinstance(piece, str):
                    piece = str(piece)
                parts.append(piece)
            elif etype == "tool":
                # use_tools=False 正常不应出现；忽略展示内容，不执行工具
                continue
            elif etype == "error":
                em = event.get("message")
                if not isinstance(em, str) or not em.strip():
                    em = "模型流返回错误"
                # 不再拼接已收到的半截 JSON
                raise PortfolioAdviceModelError(em[:200])
            elif etype == "done":
                break
    except PortfolioAdviceModelError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PortfolioAdviceModelError(
            _safe_error_message(exc, fallback="持仓建议模型调用失败")
        ) from exc
    return "".join(parts)


def generate_portfolio_advice(
    cfg: Any,
    user_request: str | None = None,
    *,
    model_runner: ModelRunner | None = None,
) -> dict:
    """生成经 validator 约束后的权威持仓操作建议。

    Parameters
    ----------
    cfg
        现有 LLM 配置（与 chat.stream_messages 一致）。
    user_request
        可选用户重点说明；规范化后传入 prompt。
    model_runner
        可选 ``(cfg, messages) -> str``，离线测试注入；默认走 stream_messages。

    Returns
    -------
    dict
        ``validate_portfolio_advice`` 的权威结果（无 t_trade）。
    """
    prepared = prepare_portfolio_advice_messages(user_request)
    messages = prepared["messages"]
    context = prepared["context"]

    runner = model_runner if model_runner is not None else _default_model_runner

    try:
        raw_text = runner(cfg, messages)
    except PortfolioAdviceModelError:
        raise
    except PortfolioAdviceModelOutputError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PortfolioAdviceModelError(
            _safe_error_message(exc, fallback="持仓建议模型调用失败")
        ) from exc

    if raw_text is None:
        raise PortfolioAdviceModelOutputError(_EMPTY_OUTPUT_MSG)
    if not isinstance(raw_text, str):
        raise PortfolioAdviceModelOutputError(_INVALID_JSON_MSG)

    ai_result = _parse_model_json(raw_text)

    try:
        return portfolio_advice_validator.validate_portfolio_advice(
            ai_result,
            context,
        )
    except PortfolioAdviceValidationError as exc:
        raise PortfolioAdviceModelOutputError(_VALIDATOR_FAIL_MSG) from exc
    except PortfolioAdviceModelOutputError:
        raise
    except Exception as exc:  # noqa: BLE001
        # 非预期异常也包装为输出错误，避免泄漏内部细节
        raise PortfolioAdviceModelOutputError(_VALIDATOR_FAIL_MSG) from exc
