"""持仓操作建议 AI 编排服务（读取持仓 + 每日复盘 → 上下文 → 模型 → 校验）。

本模块只做编排，不复制 context / prompt / validator 业务规则。
不修改 portfolio.json、不写复盘历史；最终权威建议写入独立 AI 结果表。
第一版不支持做 T。
"""

from __future__ import annotations

import json
from typing import Any, Callable

import ai_result_service
import chat
import daily_review
import decision_evidence_service
import portfolio
import portfolio_advice_context
import portfolio_advice_prompt
import portfolio_advice_validator
import position_reality_service
import signal_ledger_service
from portfolio_advice_account_metrics import attach_account_funding_metrics
from portfolio_advice_cash_constraint import apply_available_cash_constraints
from portfolio_advice_errors import public_model_error_detail
from portfolio_advice_prompt import _normalize_user_request
from portfolio_advice_sellable import apply_sellable_quantity_advisory
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


class PortfolioAdvicePersistError(RuntimeError):
    """建议已生成但 AI result 持久化失败（非客户端参数错误）。"""

    def __init__(self, message: str = "持仓建议结果保存失败", *, stage: str = "persist"):
        super().__init__(message)
        self.stage = stage


# 兼容：历史调用方从 service 导入 public_model_error_detail
__all__ = [
    "PortfolioAdviceUnavailableError",
    "PortfolioAdviceMarketDataError",
    "PortfolioAdviceModelError",
    "PortfolioAdviceModelOutputError",
    "PortfolioAdvicePersistError",
    "prepare_portfolio_advice_messages",
    "generate_portfolio_advice",
    "public_model_error_detail",
]


_EMPTY_HOLDINGS_MSG = "当前没有持仓，无法生成持仓操作建议"
_REVIEW_TRADE_DATE_MSG = "复盘交易日不可用，无法生成可靠的持仓操作建议"
_HOLDINGS_SHAPE_MSG = "持仓数据不完整，无法生成持仓操作建议"
_EMPTY_OUTPUT_MSG = "持仓建议模型未返回有效内容"
_INVALID_JSON_MSG = "持仓建议模型输出不是有效的JSON对象"
_VALIDATOR_FAIL_MSG = "持仓建议模型输出未通过结构和执行约束校验"
_HOLDING_QUOTE_UNAVAILABLE_MSG = "持仓核心行情暂不可用，无法生成可靠的持仓操作建议"
_MARKET_UNAVAILABLE_MSG = "市场核心数据暂不可用，无法生成可靠的持仓操作建议"
_HOLDING_AUTHORITY_UNAVAILABLE_MSG = "持仓权威暂不可用，无法生成可靠的持仓操作建议"


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


def _require_holding_quote_coverage(portfolio_data: dict) -> None:
    holdings = portfolio_data.get("holdings") if isinstance(portfolio_data, dict) else None
    if not isinstance(holdings, list) or len(holdings) == 0:
        raise PortfolioAdviceUnavailableError(_EMPTY_HOLDINGS_MSG)
    for h in holdings:
        if not isinstance(h, dict) or not portfolio._is_valid_price(h.get("price")):
            raise PortfolioAdviceMarketDataError(_HOLDING_QUOTE_UNAVAILABLE_MSG)

def _record_gate_blocked(error_code: str) -> None:
    try:
        import data_health_event_store as _dhes
        _dhes.safe_call(_dhes.record_gate_blocked, error_code)
    except Exception:
        pass


def _record_gate_allowed() -> None:
    try:
        import data_health_event_store as _dhes
        _dhes.safe_call(_dhes.record_gate_allowed)
    except Exception:
        pass


def _record_gate_failure(error_code: str = "SOURCE_UNAVAILABLE") -> None:
    try:
        import data_health_event_store as _dhes
        _dhes.safe_call(_dhes.record_gate_failure, error_code)
    except Exception:
        pass


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

    try:
        try:
            authority_state, derived_positions = position_reality_service.read_holding_authority()
            if authority_state == "CANONICAL":
                portfolio_data = portfolio.get_portfolio(derived_positions=derived_positions)
            else:
                portfolio_data = portfolio.get_portfolio()
        except position_reality_service.HoldingAuthorityReadError as exc:
            _record_gate_blocked("HOLDING_AUTHORITY_UNAVAILABLE")
            raise PortfolioAdviceMarketDataError(_HOLDING_AUTHORITY_UNAVAILABLE_MSG) from exc
        if not isinstance(portfolio_data, dict):
            _record_gate_blocked("NO_HOLDINGS")
            raise PortfolioAdviceUnavailableError(_EMPTY_HOLDINGS_MSG)
        try:
            _require_holdings(portfolio_data)
        except PortfolioAdviceUnavailableError:
            _record_gate_blocked("NO_HOLDINGS")
            raise
        try:
            _require_holding_quote_coverage(portfolio_data)
        except PortfolioAdviceMarketDataError:
            _record_gate_blocked("HOLDING_QUOTES_UNAVAILABLE")
            raise
        except PortfolioAdviceUnavailableError:
            _record_gate_blocked("NO_HOLDINGS")
            raise
        # 规范化 shares 为 int（add_holding 可能留下 float），避免 fingerprint 误杀
        holdings = portfolio_data.get("holdings") or []
        if isinstance(holdings, list):
            for h in holdings:
                if not isinstance(h, dict):
                    continue
                sh = h.get("shares")
                if isinstance(sh, float) and not isinstance(sh, bool) and sh == int(sh) and sh > 0:
                    h["shares"] = int(sh)
        try:
            input_fingerprint = ai_result_service.compute_portfolio_fingerprint(
                portfolio_data["holdings"]
            )
        except ai_result_service.AiResultValidationError as exc:
            _record_gate_failure("SOURCE_UNAVAILABLE")
            raise PortfolioAdviceUnavailableError(_HOLDINGS_SHAPE_MSG) from exc

        review = daily_review.generate_daily_review()
        if _market_breadth_unavailable(review):
            _record_gate_blocked("MARKET_BREADTH_UNAVAILABLE")
            raise PortfolioAdviceMarketDataError(_MARKET_UNAVAILABLE_MSG)
        # 保存路径要求 YYYY-MM-DD trade_date；缺失则在调用模型前失败关闭
        td = review.get("trade_date") if isinstance(review, dict) else None
        if not isinstance(td, str) or not td.strip():
            _record_gate_blocked("REVIEW_TRADE_DATE_UNAVAILABLE")
            raise PortfolioAdviceMarketDataError(_REVIEW_TRADE_DATE_MSG)

        try:
            context = portfolio_advice_context.build_portfolio_advice_context(
                portfolio_data,
                review,
            )
            context_json = _context_to_json(context)
            messages = portfolio_advice_prompt.build_portfolio_advice_messages(
                context_json,
                user_request=request,
            )
        except (TypeError, ValueError) as exc:
            # 上下文/提示构建失败：对外文案保持业务不可用，健康事件记为 Gate 运行失败
            _record_gate_failure("SOURCE_UNAVAILABLE")
            raise PortfolioAdviceMarketDataError(_MARKET_UNAVAILABLE_MSG) from exc
        _record_gate_allowed()
        return {
            "portfolio": portfolio_data,
            "input_fingerprint": input_fingerprint,
            "daily_review": review,
            "context": context,
            "context_json": context_json,
            "messages": messages,
        }
    except (PortfolioAdviceUnavailableError, PortfolioAdviceMarketDataError):
        raise
    except Exception:
        # Gate 运行失败（非业务阻断）
        _record_gate_failure("SOURCE_UNAVAILABLE")
        raise



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
                # 流内 error：用分类器生成安全公开文案，不回传可能含密钥的原文
                raise PortfolioAdviceModelError(
                    public_model_error_detail(RuntimeError(em[:200]))
                )
            elif etype == "done":
                break
    except PortfolioAdviceModelError:
        raise
    except Exception as exc:  # noqa: BLE001
        # 保留 __cause__ 供 public_model_error_detail 分类；对外 message 已是安全文案
        raise PortfolioAdviceModelError(public_model_error_detail(exc)) from exc
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
        raise PortfolioAdviceModelError(public_model_error_detail(exc)) from exc

    if raw_text is None:
        raise PortfolioAdviceModelOutputError(_EMPTY_OUTPUT_MSG)
    if not isinstance(raw_text, str):
        raise PortfolioAdviceModelOutputError(_INVALID_JSON_MSG)

    ai_result = _parse_model_json(raw_text)

    try:
        validated = portfolio_advice_validator.validate_portfolio_advice(
            ai_result,
            context,
        )
        authoritative = attach_account_funding_metrics(validated, prepared["portfolio"])
        authoritative = apply_available_cash_constraints(authoritative)
        authoritative = apply_sellable_quantity_advisory(
            authoritative,
            prepared["portfolio"],
        )
    except PortfolioAdviceValidationError as exc:
        raise PortfolioAdviceModelOutputError(_VALIDATOR_FAIL_MSG) from exc
    except PortfolioAdviceModelOutputError:
        raise
    except Exception as exc:  # noqa: BLE001
        # 非预期异常也包装为输出错误，避免泄漏内部细节
        raise PortfolioAdviceModelOutputError(_VALIDATOR_FAIL_MSG) from exc

    try:
        ai_result_service.save_portfolio_advice(
            prepared["portfolio"],
            prepared["daily_review"],
            authoritative,
            cfg,
            input_fingerprint=prepared["input_fingerprint"],
        )
    except ai_result_service.AiResultValidationError as exc:
        raise PortfolioAdvicePersistError(
            "持仓建议结果保存失败", stage="save_validation"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise PortfolioAdvicePersistError(
            "持仓建议结果保存失败", stage="save"
        ) from exc

    try:
        decision_evidence_service.archive_decision_evidence(
            authoritative,
            context_data=prepared.get("context"),
        )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("Archive decision evidence failed: %s", exc)

    try:
        signal_ledger_service.archive_signal_ledger(
            authoritative,
            context_data=prepared.get("context"),
        )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("Archive signal ledger failed: %s", exc)

    return authoritative

