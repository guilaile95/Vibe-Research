"""持仓操作建议结构化结果校验与数量约束（纯函数，不联网、不调模型）。

对 AI 输出的 JSON 进行：
- 动作枚举与固定比例档位校验；
- 条件字段数字来源可追溯校验；
- reduce/sell 失效条件冲突与无依据模板话术拦截；
- 代码重算市值/盈亏/权重（覆盖模型数值）；
- reduce/sell 数量按 100 股向下取整并截断；
- add 按持股比例计算买入股数与预计金额（覆盖模型数值）；
- 数据限制语义归一化去重；
- 忽略并剥离模型额外输出的 t_trade 字段（第一版不支持做 T）。

不信任模型自行计算的数量与盈亏。
"""

from __future__ import annotations

import copy
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from portfolio_advice_prompt import ACCOUNT_ACTIONS, ACTIONS, SCHEMA_VERSION

LOT_SIZE = 100

# 标准化数据限制文案
_SELLABLE_LIMITATION = "未提供可卖数量，执行前需要人工确认实际可卖股数。"
_CASH_LIMITATION = (
    "未提供账户总资产与可用现金，买入数量仅按当前持股比例计算；"
    "执行前需要确认可用资金充足。"
)
_KLINE_LIMITATION = "未提供历史K线与技术指标，无法计算趋势、支撑位或压力位。"
_CATALYST_LIMITATION = "未接入可靠公告、新闻和机构公开信息，不判断消息催化原因。"
_ADD_LOT_LIMITATION = "按当前建议比例计算不足一个100股交易单位，暂不生成具体买入数量。"
_PRICE_AMOUNT_LIMITATION = "当前价格不可用，无法计算预计所需金额。"
_AMOUNT_ESTIMATE_NOTE = "预计金额按当前价格计算，不包含手续费和实际成交价偏差。"
_SHARES_LIMITATION = "持股数量不可用，无法计算具体买入数量。"

_CONFIDENCE = frozenset({"high", "medium", "low"})

# 固定操作比例档位
_ADD_TIERS = frozenset({10.0, 20.0})
_REDUCE_TIERS = frozenset({10.0, 20.0, 30.0})
_SELL_TIER = 100.0
_CONF_MAX = {"low": 10.0, "medium": 20.0, "high": 30.0}

_CONDITION_FIELDS = (
    "trigger_conditions",
    "price_conditions",
    "execution_plan",
    "risk_conditions",
    "invalidation_conditions",
)

# 从条件文本抽取数字（含可选百分号）
_NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z_])(\d+(?:\.\d+)?)\s*%?")

# reduce/sell 失效条件冲突：风险扩大却暂停减仓
_RISK_WORSEN_RE = re.compile(
    r"风险恶化|继续下跌|跌破|扩大浮亏|市场继续恶化|继续走弱|继续恶化|加速下跌"
)
_CANCEL_RISK_ACTION_RE = re.compile(
    r"暂停减仓|取消卖出|停止减仓|取消减仓|停止卖出|暂停卖出|停止风险|取消风险控制"
)

# 无盘口数据时禁止的模板话术
_MARKET_IMPACT_RE = re.compile(
    r"减少市场冲击|降低冲击成本|避免大单影响|大单影响价格|保护盘口|分批成交以保护"
)

# add：明确「新增买入」股数（不含「当前持有 N 股」等事实表述）
_ADD_BUY_QTY_RE = re.compile(
    r"(?:建议|计划)?"
    r"(?:买入|加仓|增持|新增|追加)"
    r"(?:数量)?"
    r"\s*(\d+(?:\.\d+)?)\s*股"
)

# add：明确「新增投入」金额（动词/约 + 元/万元/¥）
# 动词路径：投入/预计需要/… + 金额
# 约数路径：约/大约 + 金额（排除「价格/成本…」前缀）
_ADD_AMOUNT_VERB_RE = re.compile(
    r"(?P<head>投入|预计需要|预计金额|预计所需|所需金额|买入金额|准备|使用|需要|约需|预计投入|买入约|投入约)"
    r"[^0-9¥￥%]{0,8}"
    r"(?:"
    r"[¥￥]\s*(?P<num_sym>\d+(?:\.\d+)?)"
    r"|"
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>万元|元)"
    r")"
)
_ADD_AMOUNT_APPROX_RE = re.compile(
    r"(?P<head>约|大约)"
    r"\s*[¥￥]?\s*"
    r"(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>万元|元)"
)
_ADD_AMOUNT_SYMBOL_RE = re.compile(
    r"(?P<head>投入|预计需要|预计金额|预计所需|买入金额|准备|使用|需要|约需|约|大约)"
    r"[^0-9¥￥%]{0,6}"
    r"[¥￥]\s*"
    r"(?P<num>\d+(?:\.\d+)?)"
    r"(?!\s*万)"
)
_PRICE_FACT_PREFIX_RE = re.compile(r"(?:价格|成本|现价|市值|盈亏|报价)\s*$")

# add：禁止把比例解释为账户/总资产/可用资金比例
_ADD_ACCOUNT_RATIO_FORBIDDEN: list[re.Pattern[str]] = [
    re.compile(r"账户.{0,12}仓位.{0,16}\d+(?:\.\d+)?\s*%"),
    re.compile(r"将.{0,8}账户仓位.{0,12}(?:提高|增加|上调).{0,8}\d+(?:\.\d+)?\s*%"),
    re.compile(r"总资产.{0,16}\d+(?:\.\d+)?\s*%"),
    re.compile(r"投入总资产.{0,8}\d+(?:\.\d+)?\s*%"),
    re.compile(r"可用现金.{0,16}\d+(?:\.\d+)?\s*%"),
    re.compile(r"使用资金.{0,12}(?:10|20)\s*%"),
    re.compile(r"账户资金.{0,12}(?:10|20)\s*%"),
    re.compile(r"使用账户.{0,12}(?:10|20)\s*%"),
    re.compile(r"配置.{0,8}(?:10|20)\s*%.{0,12}账户"),
    re.compile(r"(?:10|20)\s*%.{0,8}(?:的)?(?:账户资产|可用现金|账户资金)"),
]

# 数据限制语义归一（按顺序匹配，首次命中归类）
_LIMIT_NORMALIZE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"可卖|sellable", re.I), _SELLABLE_LIMITATION),
    (
        re.compile(
            r"账户总资产|可用现金|账户仓位|绝对账户|具体买入金额|无法计算账户仓位"
            r"|买入数量仅按当前持股比例"
        ),
        _CASH_LIMITATION,
    ),
    (re.compile(r"不足一个\s*100\s*股|不足一个100股交易单位"), _ADD_LOT_LIMITATION),
    (re.compile(r"当前价格不可用|无法计算预计所需金额"), _PRICE_AMOUNT_LIMITATION),
    (re.compile(r"不包含手续费|实际成交价偏差"), _AMOUNT_ESTIMATE_NOTE),
    (re.compile(r"持股数量不可用"), _SHARES_LIMITATION),
    (
        re.compile(r"历史\s*K|技术指标|支撑位|压力位|均线|N\s*日|趋势"),
        _KLINE_LIMITATION,
    ),
    (
        re.compile(r"公告|新闻|机构|催化|龙虎榜"),
        _CATALYST_LIMITATION,
    ),
]


class PortfolioAdviceValidationError(ValueError):
    """结构化结果无法校验时抛出。"""


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


def _num_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            return None
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    n = _num_or_none(value)
    return default if n is None else n


def _round2(v: float) -> float:
    return round(v, 2)


def _str_list(value: Any) -> list[str]:
    out: list[str] = []
    for it in _as_list(value):
        if isinstance(it, str) and it.strip():
            out.append(it.strip())
        elif it is not None and not isinstance(it, str):
            s = str(it).strip()
            if s:
                out.append(s)
    return _dedupe_str_list(out)


def _dedupe_str_list(items: list[str]) -> list[str]:
    """稳定去重：完全相同文案只保留首次出现。"""
    out: list[str] = []
    seen: set[str] = set()
    for s in items:
        if not isinstance(s, str):
            continue
        t = s.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _append_unique(lst: list[str], msg: str) -> None:
    if msg and msg not in lst:
        lst.append(msg)


def floor_to_lot(quantity: float, lot: int = LOT_SIZE) -> int:
    """向下取整到交易单位（默认 100 股）。负数归零。"""
    if lot <= 0:
        raise ValueError("lot 必须为正整数")
    if quantity is None:
        return 0
    q = float(quantity)
    if q <= 0:
        return 0
    return int(q // lot) * lot


def compute_execution_quantity(
    shares: float,
    size_pct: float | None,
    *,
    lot: int = LOT_SIZE,
) -> int | None:
    """reduce/sell：shares × pct/100 后向下取整到 lot，且不超过 shares。"""
    if size_pct is None:
        return None
    pct = float(size_pct)
    if pct < 0:
        pct = 0.0
    if pct > 100:
        pct = 100.0
    raw = float(shares) * pct / 100.0
    qty = floor_to_lot(raw, lot=lot)
    if qty > float(shares):
        qty = floor_to_lot(float(shares), lot=lot)
    return qty


def compute_add_execution_quantity(
    shares: float | None,
    size_pct: float | None,
    *,
    lot: int = LOT_SIZE,
) -> int | None:
    """add：相对当前持股增加 pct% 后向下取整到 lot；不足一个 lot 返回 None。"""
    if size_pct is None or shares is None:
        return None
    sh = float(shares)
    if sh <= 0 or not math.isfinite(sh):
        return None
    pct = float(size_pct)
    if pct <= 0 or not math.isfinite(pct):
        return None
    raw = sh * pct / 100.0
    qty = floor_to_lot(raw, lot=lot)
    if qty < lot:
        return None
    return qty


def compute_estimated_amount(
    quantity: int | None,
    current_price: float | None,
) -> float | None:
    """execution_quantity × current_price，Decimal 精确到分（四舍五入）。"""
    if quantity is None or quantity <= 0:
        return None
    if current_price is None:
        return None
    try:
        price = Decimal(str(current_price))
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None
    amount = (Decimal(int(quantity)) * price).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(amount)


def _normalize_pct(value: Any) -> float | None:
    if value is None:
        return None
    n = _num_or_none(value)
    if n is None:
        raise PortfolioAdviceValidationError(
            f"execution_size_pct_of_holding 非法：{value!r}"
        )
    if n < 0 or n > 100:
        raise PortfolioAdviceValidationError(
            f"execution_size_pct_of_holding 必须在 0—100，收到：{n}"
        )
    return float(n)


def _context_holdings_index(context: dict) -> dict[str, dict]:
    holdings = _as_list(context.get("holdings"))
    idx: dict[str, dict] = {}
    for h in holdings:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code") or "").strip()
        if code:
            idx[code] = h
    return idx


def _recompute_fact_fields(ctx_h: dict) -> dict[str, Any]:
    """从上下文持仓行提取/重算权威事实字段。"""
    shares = _safe_float(ctx_h.get("shares"), 0.0)
    cost = _safe_float(ctx_h.get("cost_price"), 0.0)
    price = _safe_float(ctx_h.get("current_price"), 0.0)
    mv = _round2(price * shares)
    cost_v = cost * shares
    pnl = _round2(mv - cost_v)
    pnl_pct = _round2(pnl / cost_v * 100) if cost_v else 0.0
    weight = _num_or_none(ctx_h.get("holding_weight_pct"))
    if weight is None:
        weight = 0.0
    return {
        "code": str(ctx_h.get("code") or "").strip(),
        "name": str(ctx_h.get("name") or ctx_h.get("code") or ""),
        "shares": shares,
        "cost_price": cost,
        "current_price": price,
        "market_value": mv,
        "pnl_amount": pnl,
        "pnl_pct": pnl_pct,
        "holding_weight_pct": float(weight),
    }


def _market_status_from_context(context: dict) -> str:
    mc = _as_dict(context.get("market_context"))
    rm = _as_dict(mc.get("review_metadata"))
    st = rm.get("status")
    if isinstance(st, str) and st:
        return st
    me = _as_dict(context.get("market_evidence"))
    st2 = me.get("review_status")
    if isinstance(st2, str) and st2:
        return st2
    return ""


def _market_is_partial(context: dict) -> bool:
    return _market_status_from_context(context) == "partial"


def _collect_context_numbers(obj: Any, out: set[float]) -> None:
    """递归收集 context 中的数值，供条件字段追溯。"""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        if math.isfinite(v):
            out.add(v)
            out.add(abs(v))
        return
    if isinstance(obj, str):
        for m in _NUM_TOKEN_RE.finditer(obj):
            try:
                out.add(float(m.group(1)))
            except ValueError:
                continue
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_context_numbers(v, out)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_context_numbers(v, out)


def _number_allowed(num: float, allowed: set[float]) -> bool:
    for a in allowed:
        if abs(a - num) <= 1e-6:
            return True
        # 百分比/小数的相对容差
        scale = max(abs(a), abs(num), 1.0)
        if abs(a - num) / scale <= 1e-4:
            return True
    return False


def _extract_numbers_from_text(text: str) -> list[float]:
    nums: list[float] = []
    for m in _NUM_TOKEN_RE.finditer(text):
        try:
            nums.append(float(m.group(1)))
        except ValueError:
            continue
    return nums


def _validate_condition_numbers(
    fields: dict[str, list[str]],
    *,
    allowed_numbers: set[float],
    code: str,
) -> None:
    """条件字段中的数字必须可在 allowed_numbers 中追溯。"""
    for field, items in fields.items():
        for item in items:
            for num in _extract_numbers_from_text(item):
                if not _number_allowed(num, allowed_numbers):
                    raise PortfolioAdviceValidationError(
                        f"条件字段含无法追溯的数字 {num}（field={field}, code={code}）：{item[:80]}"
                    )


def _validate_reduce_sell_invalidation(action: str, invalidation: list[str], code: str) -> None:
    if action not in ("reduce", "sell"):
        return
    text = "；".join(invalidation)
    if not text:
        return
    if _RISK_WORSEN_RE.search(text) and _CANCEL_RISK_ACTION_RE.search(text):
        raise PortfolioAdviceValidationError(
            f"reduce/sell 失效条件与风险控制冲突（code={code}）："
            "不得在风险恶化/继续下跌时暂停减仓或取消卖出"
        )


def _validate_no_market_impact_template(fields: dict[str, list[str]], code: str) -> None:
    for field, items in fields.items():
        for item in items:
            if _MARKET_IMPACT_RE.search(item):
                raise PortfolioAdviceValidationError(
                    f"无流动性/盘口数据时禁止市场冲击类话术（field={field}, code={code}）"
                )


def _join_condition_texts(fields: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for key in _CONDITION_FIELDS:
        for item in fields.get(key) or []:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
    return "\n".join(parts)


def _strip_add_execution_phrases(text: str) -> str:
    """去掉 add 买卖数量/金额短语，避免与事实数字混入通用数字追溯。"""
    t = _ADD_BUY_QTY_RE.sub(" ", text)
    t = _ADD_AMOUNT_VERB_RE.sub(" ", t)
    t = _ADD_AMOUNT_APPROX_RE.sub(" ", t)
    t = _ADD_AMOUNT_SYMBOL_RE.sub(" ", t)
    return t


def _amount_match_to_yuan(m: re.Match[str]) -> tuple[float, bool] | None:
    gd = m.groupdict()
    raw = gd.get("num") or gd.get("num_sym") or gd.get("num2")
    if raw is None:
        return None
    try:
        num = float(raw)
    except ValueError:
        return None
    unit = gd.get("unit") or ""
    yuan = num * 10000.0 if unit == "万元" else num
    head = gd.get("head") or ""
    approx = bool(re.search(r"约|大约|预计|约需", head))
    return yuan, approx


def _iter_add_amount_mentions(text: str) -> list[tuple[float, bool]]:
    """返回 (金额元, 是否近似表达) 列表。"""
    hits: list[tuple[float, bool, int, int]] = []

    def _consider(m: re.Match[str], *, check_price_prefix: bool) -> None:
        if check_price_prefix:
            prefix = text[max(0, m.start() - 6) : m.start()]
            if _PRICE_FACT_PREFIX_RE.search(prefix):
                return
        parsed = _amount_match_to_yuan(m)
        if parsed is None:
            return
        yuan, approx = parsed
        # 跳过重叠
        if any(s <= m.start() < e or s < m.end() <= e for _, _, s, e in hits):
            return
        hits.append((yuan, approx, m.start(), m.end()))

    for m in _ADD_AMOUNT_VERB_RE.finditer(text):
        _consider(m, check_price_prefix=False)
    for m in _ADD_AMOUNT_APPROX_RE.finditer(text):
        _consider(m, check_price_prefix=True)
    for m in _ADD_AMOUNT_SYMBOL_RE.finditer(text):
        _consider(m, check_price_prefix=True)

    return [(y, a) for y, a, _, _ in hits]


def _amount_tolerance(estimated: float, approx: bool) -> float:
    if approx:
        return max(1.0, abs(estimated) * 0.005)
    return 0.01


def _validate_add_buy_qty_text(
    text: str,
    *,
    execution_quantity: int | None,
    code: str,
) -> None:
    matches = list(_ADD_BUY_QTY_RE.finditer(text))
    if execution_quantity is None:
        if matches:
            raise PortfolioAdviceValidationError(
                f"add 无具体买入数量时不得提出新增买入股数（code={code}）"
            )
        return
    target = float(execution_quantity)
    for m in matches:
        try:
            n = float(m.group(1))
        except ValueError:
            continue
        if abs(n - target) > 1e-6:
            raise PortfolioAdviceValidationError(
                f"add 文字买入股数与后端计算不一致（code={code}）："
                f"期望 {execution_quantity}，文字 {m.group(0)!r}"
            )


def _validate_add_amount_text(
    text: str,
    *,
    estimated_amount: float | None,
    code: str,
) -> None:
    mentions = _iter_add_amount_mentions(text)
    if estimated_amount is None:
        if mentions:
            raise PortfolioAdviceValidationError(
                f"add 无预计金额时不得提出具体新增投入金额（code={code}）"
            )
        return
    for yuan, approx in mentions:
        tol = _amount_tolerance(float(estimated_amount), approx)
        if abs(yuan - float(estimated_amount)) > tol + 1e-9:
            raise PortfolioAdviceValidationError(
                f"add 文字投入金额与后端计算不一致（code={code}）："
                f"期望 {estimated_amount}，文字约 {yuan}"
            )


def _validate_add_account_ratio_language(text: str, code: str) -> None:
    for pat in _ADD_ACCOUNT_RATIO_FORBIDDEN:
        if pat.search(text):
            raise PortfolioAdviceValidationError(
                f"add 禁止将比例表述为账户/总资产/可用资金比例（code={code}）"
            )


def _normalize_limitation_list(items: list[str]) -> list[str]:
    """已知四类限制语义归一，再按类别稳定去重；未知文案原样去重保留。"""
    seen_std: set[str] = set()
    out: list[str] = []
    for raw in items:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        mapped: str | None = None
        for pat, std in _LIMIT_NORMALIZE_RULES:
            if pat.search(s):
                mapped = std
                break
        final = mapped if mapped is not None else s
        if final in seen_std:
            continue
        seen_std.add(final)
        out.append(final)
    return out


def _validate_size_tier(
    action: str,
    size_pct: float | None,
    *,
    confidence: str,
    market_partial: bool,
    code: str,
) -> float | None:
    """校验并返回规范后的操作比例。"""
    if action in ("hold", "watch", "avoid"):
        return None

    if action == "sell":
        # 固定 100；模型填 null 也规范为 100
        return _SELL_TIER

    if size_pct is None:
        if action in ("add", "reduce"):
            raise PortfolioAdviceValidationError(
                f"{action} 必须给出档位比例（code={code}）"
            )
        return None

    # 归一到整数比较档位（允许 20.0）
    tier = float(size_pct)
    if action == "add":
        allowed = set(_ADD_TIERS)
        if market_partial:
            allowed = {10.0}
        if tier not in allowed:
            raise PortfolioAdviceValidationError(
                f"add 比例仅允许 {sorted(int(x) for x in allowed)}，收到 {tier}（code={code}）"
            )
    elif action == "reduce":
        allowed = set(_REDUCE_TIERS)
        if market_partial:
            allowed = {10.0, 20.0}
        if tier not in allowed:
            raise PortfolioAdviceValidationError(
                f"reduce 比例仅允许 {sorted(int(x) for x in allowed)}，收到 {tier}（code={code}）"
            )
    else:
        return tier

    conf = confidence if confidence in _CONF_MAX else "low"
    cap = _CONF_MAX[conf]
    if market_partial and action == "add":
        cap = min(cap, 10.0)
    if market_partial and action == "reduce":
        cap = min(cap, 20.0)
    if tier > cap:
        raise PortfolioAdviceValidationError(
            f"{action} 比例 {tier} 超过置信度 {conf} 上限 {int(cap)}（code={code}）"
        )
    return tier


def _validate_one_holding(
    ai_h: dict,
    ctx_h: dict,
    *,
    context: dict,
    allowed_base_numbers: set[float],
) -> dict[str, Any]:
    facts = _recompute_fact_fields(ctx_h)
    action = ai_h.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise PortfolioAdviceValidationError(
            f"非法 action：{action!r}（code={facts['code']}）"
        )

    conf = ai_h.get("confidence")
    if conf not in _CONFIDENCE:
        conf = "low"

    market_partial = _market_is_partial(context)
    raw_pct = ai_h.get("execution_size_pct_of_holding")

    # 持股/价格是否可用于 add 计算（与展示用 facts 解耦：0/缺失视为不可用）
    shares_for_add = _num_or_none(ctx_h.get("shares"))
    price_for_add = _num_or_none(ctx_h.get("current_price"))
    if shares_for_add is not None and shares_for_add <= 0:
        shares_for_add = None
    if price_for_add is not None and price_for_add <= 0:
        price_for_add = None

    size_pct: float | None
    qty: int | None
    estimated_amount: float | None = None
    add_shares_missing = False
    add_price_missing = False
    add_lot_insufficient = False

    if action in ("hold", "watch", "avoid"):
        # 强制清空
        size_pct = None
        qty = None
        estimated_amount = None
    elif action == "sell":
        # 固定 100；非法非空非 100 拒绝
        if raw_pct is not None:
            n = _normalize_pct(raw_pct)
            if n is not None and abs(n - _SELL_TIER) > 1e-6:
                raise PortfolioAdviceValidationError(
                    f"sell 比例必须为 100，收到 {n}（code={facts['code']}）"
                )
        size_pct = _SELL_TIER
        qty = compute_execution_quantity(facts["shares"], size_pct)
        if qty is not None and qty > facts["shares"]:
            qty = floor_to_lot(facts["shares"])
        estimated_amount = None
    elif action == "reduce":
        if raw_pct is None:
            raise PortfolioAdviceValidationError(
                f"reduce 必须给出档位比例 10/20/30（code={facts['code']}）"
            )
        n = _normalize_pct(raw_pct)
        size_pct = _validate_size_tier(
            action,
            n,
            confidence=conf,
            market_partial=market_partial,
            code=facts["code"],
        )
        qty = compute_execution_quantity(facts["shares"], size_pct)
        if qty is not None and qty > facts["shares"]:
            qty = floor_to_lot(facts["shares"])
        estimated_amount = None
    elif action == "add":
        if raw_pct is None:
            raise PortfolioAdviceValidationError(
                f"add 必须给出档位比例 10/20（code={facts['code']}）"
            )
        n = _normalize_pct(raw_pct)
        size_pct = _validate_size_tier(
            action,
            n,
            confidence=conf,
            market_partial=market_partial,
            code=facts["code"],
        )
        # 模型结构化 quantity / amount 一律丢弃，后端重算覆盖
        if shares_for_add is None:
            qty = None
            estimated_amount = None
            add_shares_missing = True
        else:
            qty = compute_add_execution_quantity(shares_for_add, size_pct)
            if qty is None:
                # 有持股但不足一个交易单位
                add_lot_insufficient = True
                estimated_amount = None
            else:
                if price_for_add is None:
                    estimated_amount = None
                    add_price_missing = True
                else:
                    estimated_amount = compute_estimated_amount(qty, price_for_add)
                    if estimated_amount is None:
                        add_price_missing = True
    else:
        size_pct = None
        qty = None
        estimated_amount = None

    trigger = _str_list(ai_h.get("trigger_conditions"))
    price_c = _str_list(ai_h.get("price_conditions"))
    plan = _str_list(ai_h.get("execution_plan"))
    risk = _str_list(ai_h.get("risk_conditions"))
    invalidation = _str_list(ai_h.get("invalidation_conditions"))

    cond_fields = {
        "trigger_conditions": trigger,
        "price_conditions": price_c,
        "execution_plan": plan,
        "risk_conditions": risk,
        "invalidation_conditions": invalidation,
    }

    # 数字白名单：context + 本条比例/股数/预计金额
    allowed = set(allowed_base_numbers)
    if size_pct is not None:
        allowed.add(float(size_pct))
    if qty is not None:
        allowed.add(float(qty))
    if estimated_amount is not None:
        allowed.add(float(estimated_amount))
        wan = float(estimated_amount) / 10000.0
        allowed.add(wan)
        allowed.add(round(wan, 2))
        allowed.add(round(wan, 1))
        # 近似金额容差内的整元也可出现在文字中
        tol = max(1.0, abs(float(estimated_amount)) * 0.005)
        lo = int(math.floor(float(estimated_amount) - tol))
        hi = int(math.ceil(float(estimated_amount) + tol))
        for i in range(lo, hi + 1):
            allowed.add(float(i))
    # 持仓事实再加一遍
    for k in (
        "shares",
        "cost_price",
        "current_price",
        "market_value",
        "pnl_amount",
        "pnl_pct",
        "holding_weight_pct",
    ):
        v = facts.get(k)
        if isinstance(v, (int, float)) and math.isfinite(float(v)):
            allowed.add(float(v))

    # add：买卖数量/金额由专用规则校验；从通用数字追溯中剥离对应短语
    if action == "add":
        stripped_fields = {
            k: [_strip_add_execution_phrases(it) for it in items]
            for k, items in cond_fields.items()
        }
        _validate_condition_numbers(
            stripped_fields, allowed_numbers=allowed, code=facts["code"]
        )
        joined = _join_condition_texts(cond_fields)
        # 先拦账户比例语义，再校验股数/金额，避免「20%」被金额规则误吞
        _validate_add_account_ratio_language(joined, facts["code"])
        _validate_add_buy_qty_text(
            joined, execution_quantity=qty, code=facts["code"]
        )
        _validate_add_amount_text(
            joined, estimated_amount=estimated_amount, code=facts["code"]
        )
    else:
        _validate_condition_numbers(
            cond_fields, allowed_numbers=allowed, code=facts["code"]
        )
    _validate_reduce_sell_invalidation(action, invalidation, facts["code"])
    _validate_no_market_impact_template(cond_fields, facts["code"])

    limitations = _str_list(ai_h.get("data_limitations"))
    if action in ("reduce", "sell"):
        _append_unique(limitations, _SELLABLE_LIMITATION)
    if action == "add":
        _append_unique(limitations, _CASH_LIMITATION)
        if add_shares_missing:
            _append_unique(limitations, _SHARES_LIMITATION)
        if add_lot_insufficient:
            _append_unique(limitations, _ADD_LOT_LIMITATION)
        if add_price_missing:
            _append_unique(limitations, _PRICE_AMOUNT_LIMITATION)
        if estimated_amount is not None:
            _append_unique(limitations, _AMOUNT_ESTIMATE_NOTE)
    limitations = _normalize_limitation_list(limitations)

    return {
        **facts,
        "action": action,
        "execution_size_pct_of_holding": size_pct,
        "execution_quantity": qty,
        "estimated_amount": estimated_amount,
        "trigger_conditions": trigger,
        "price_conditions": price_c,
        "execution_plan": plan,
        "risk_conditions": risk,
        "invalidation_conditions": invalidation,
        "confidence": conf,
        "data_limitations": limitations,
    }


def _portfolio_summary_from_context(context: dict) -> dict[str, Any]:
    s = _as_dict(context.get("portfolio_summary"))
    holdings = _as_list(context.get("holdings"))
    if holdings:
        tmv = _round2(sum(_safe_float(h.get("market_value")) for h in holdings if isinstance(h, dict)))
        tcost = _round2(
            sum(
                _safe_float(h.get("cost_price")) * _safe_float(h.get("shares"))
                for h in holdings
                if isinstance(h, dict)
            )
        )
        tpnl = _round2(tmv - tcost)
        tpnl_pct = _round2(tpnl / tcost * 100) if tcost else 0.0
        return {
            "holding_count": len([h for h in holdings if isinstance(h, dict) and h.get("code")]),
            "market_value": tmv,
            "cost": tcost,
            "pnl": tpnl,
            "pnl_pct": tpnl_pct,
        }
    return {
        "holding_count": int(_safe_float(s.get("holding_count"), 0)),
        "market_value": _round2(_safe_float(s.get("market_value"), 0)),
        "cost": _round2(_safe_float(s.get("cost"), 0)),
        "pnl": _round2(_safe_float(s.get("pnl"), 0)),
        "pnl_pct": _round2(_safe_float(s.get("pnl_pct"), 0)),
    }


def _validate_account_action(raw: Any) -> dict[str, str]:
    d = _as_dict(raw)
    action = d.get("action")
    if action not in ACCOUNT_ACTIONS:
        action = "hold"
        reason = str(d.get("reason") or "账户动作非法，已回落为 hold").strip()
        conf = "low"
    else:
        reason = str(d.get("reason") or "").strip()
        conf = d.get("confidence") if d.get("confidence") in _CONFIDENCE else "low"
    return {"action": action, "reason": reason, "confidence": conf}


def validate_portfolio_advice(
    ai_result: dict,
    context: dict,
    *,
    generated_at: str | None = None,
) -> dict:
    """校验并约束 AI 持仓建议结果。

    Parameters
    ----------
    ai_result
        模型输出的结构化 dict（已解析 JSON）。
    context
        ``build_portfolio_advice_context`` 的输出；作为事实权威源。
    generated_at
        可选覆盖时间戳；默认取 ai_result 或空字符串。

    Returns
    -------
    规范化后的权威结果 dict（schema_version=portfolio-advice-v0.1）。
    结果中绝不包含 t_trade 字段。
    """
    if not isinstance(ai_result, dict):
        raise PortfolioAdviceValidationError("ai_result 必须是字典")
    if not isinstance(context, dict):
        raise PortfolioAdviceValidationError("context 必须是字典")

    ai_work = copy.deepcopy(ai_result)

    allowed_base: set[float] = set()
    _collect_context_numbers(context, allowed_base)
    # 档位本身允许出现在条件/计划中
    allowed_base.update(_ADD_TIERS)
    allowed_base.update(_REDUCE_TIERS)
    allowed_base.add(_SELL_TIER)
    allowed_base.add(0.0)
    allowed_base.add(float(LOT_SIZE))

    ctx_index = _context_holdings_index(context)
    ai_holdings_raw = _as_list(ai_work.get("holdings"))
    ai_by_code: dict[str, dict] = {}
    for h in ai_holdings_raw:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code") or "").strip()
        if code:
            ai_by_code[code] = h

    validated_holdings: list[dict] = []
    for code, ctx_h in ctx_index.items():
        ai_h = ai_by_code.get(code)
        if ai_h is None:
            ai_h = {
                "code": code,
                "action": "watch",
                "confidence": "low",
                "trigger_conditions": ["模型未返回该持仓建议"],
                "price_conditions": [],
                "execution_plan": ["暂不操作，等待补全建议"],
                "risk_conditions": ["建议不完整"],
                "invalidation_conditions": ["获得完整建议后重新评估"],
                "data_limitations": ["模型未覆盖该持仓"],
            }
        validated_holdings.append(
            _validate_one_holding(
                ai_h,
                ctx_h,
                context=context,
                allowed_base_numbers=allowed_base,
            )
        )

    summary = _portfolio_summary_from_context(context)
    account_action = _validate_account_action(ai_work.get("account_action"))

    top_limitations = _str_list(ai_work.get("data_limitations"))
    for msg in _as_list(context.get("data_limitations")):
        if isinstance(msg, str):
            _append_unique(top_limitations, msg.strip())
    _append_unique(top_limitations, _SELLABLE_LIMITATION)
    _append_unique(top_limitations, _CASH_LIMITATION)
    # 若 context 声明无历史K/催化，归一时也会收口
    top_limitations = _normalize_limitation_list(top_limitations)

    warnings = _str_list(ai_work.get("warnings"))
    for w in _as_list(context.get("warnings")):
        if isinstance(w, str):
            _append_unique(warnings, w.strip())
    warnings = _dedupe_str_list(warnings)

    market_status = ai_work.get("market_status")
    if not isinstance(market_status, str) or not market_status.strip():
        market_status = _market_status_from_context(context)

    ts = generated_at
    if ts is None:
        ts = ai_work.get("generated_at")
    if not isinstance(ts, str):
        ts = ""

    trade_date: str | None = None
    meta = _as_dict(context.get("portfolio_meta"))
    raw_td = meta.get("trade_date")
    if isinstance(raw_td, str) and raw_td.strip():
        trade_date = raw_td.strip()
    else:
        me = _as_dict(context.get("market_evidence"))
        raw_td = me.get("trade_date")
        if isinstance(raw_td, str) and raw_td.strip():
            trade_date = raw_td.strip()
        else:
            mc = _as_dict(context.get("market_context"))
            rm = _as_dict(mc.get("review_metadata"))
            raw_td = rm.get("trade_date")
            if isinstance(raw_td, str) and raw_td.strip():
                trade_date = raw_td.strip()

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": ts,
        "trade_date": trade_date,
        "market_status": market_status,
        "portfolio_summary": summary,
        "account_action": account_action,
        "holdings": validated_holdings,
        "warnings": warnings,
        "data_limitations": top_limitations,
    }
