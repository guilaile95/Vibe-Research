"""持仓建议数字来源、中文文案与 limitations 审核。"""

from __future__ import annotations

import math
import re
from typing import Any

from portfolio_advice_errors import PortfolioAdviceValidationError
from portfolio_advice_policy import POLICY, PortfolioAdvicePolicy
from portfolio_advice_schema import append_unique, dedupe_str_list


SELLABLE_LIMITATION = "未提供理论建议卖出数量（非券商可卖数量），执行前请以券商实际可卖数量为准。"
CASH_LIMITATION = (
    "未提供账户总资产与可用现金，买入数量仅按当前持股比例计算；"
    "执行前需要确认可用资金充足。"
)
KLINE_LIMITATION = "未提供历史K线与技术指标，无法计算趋势、支撑位或压力位。"
CATALYST_LIMITATION = "未接入可靠公告、新闻和机构公开信息，不判断消息催化原因。"
ADD_LOT_LIMITATION = "按当前建议比例计算不足一个100股交易单位，暂不生成具体买入数量。"
PRICE_AMOUNT_LIMITATION = "当前价格不可用，无法计算预计所需金额。"
AMOUNT_ESTIMATE_NOTE = "预计金额按当前价格计算，不包含手续费和实际成交价偏差。"
SHARES_LIMITATION = "持股数量不可用，无法计算具体买入数量。"

NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z_])(\d+(?:\.\d+)?)\s*%?")
RISK_WORSEN_RE = re.compile(
    r"风险恶化|继续下跌|跌破|扩大浮亏|市场继续恶化|继续走弱|继续恶化|加速下跌"
)
CANCEL_RISK_ACTION_RE = re.compile(
    r"暂停减仓|取消卖出|停止减仓|取消减仓|停止卖出|暂停卖出|停止风险|取消风险控制"
)
MARKET_IMPACT_RE = re.compile(
    r"减少市场冲击|降低冲击成本|避免大单影响|大单影响价格|保护盘口|分批成交以保护"
)
ADD_BUY_QTY_RE = re.compile(
    r"(?:建议|计划)?(?:买入|加仓|增持|新增|追加)(?:数量)?"
    r"\s*(\d+(?:\.\d+)?)\s*股"
)
ADD_AMOUNT_VERB_RE = re.compile(
    r"(?P<head>投入|预计需要|预计金额|预计所需|所需金额|买入金额|准备|使用|需要|约需|预计投入|买入约|投入约)"
    r"[^0-9¥￥%]{0,8}(?:[¥￥]\s*(?P<num_sym>\d+(?:\.\d+)?)|"
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>万元|元))"
)
ADD_AMOUNT_APPROX_RE = re.compile(
    r"(?P<head>约|大约)\s*[¥￥]?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>万元|元)"
)
ADD_AMOUNT_SYMBOL_RE = re.compile(
    r"(?P<head>投入|预计需要|预计金额|预计所需|买入金额|准备|使用|需要|约需|约|大约)"
    r"[^0-9¥￥%]{0,6}[¥￥]\s*(?P<num>\d+(?:\.\d+)?)(?!\s*万)"
)
PRICE_FACT_PREFIX_RE = re.compile(r"(?:价格|成本|现价|市值|盈亏|报价)\s*$")


def build_tier_pattern(values: frozenset[float]) -> re.Pattern[str]:
    normalized = [
        str(int(value)) if float(value).is_integer() else str(value)
        for value in sorted(values)
    ]
    return re.compile("(?:" + "|".join(map(re.escape, normalized)) + ")")


def build_add_account_ratio_forbidden(
    policy: PortfolioAdvicePolicy = POLICY,
) -> tuple[re.Pattern[str], ...]:
    add_tiers = build_tier_pattern(policy.add_tiers).pattern
    return (
        re.compile(r"账户.{0,12}仓位.{0,16}\d+(?:\.\d+)?\s*%"),
        re.compile(r"将.{0,8}账户仓位.{0,12}(?:提高|增加|上调).{0,8}\d+(?:\.\d+)?\s*%"),
        re.compile(r"总资产.{0,16}\d+(?:\.\d+)?\s*%"),
        re.compile(r"投入总资产.{0,8}\d+(?:\.\d+)?\s*%"),
        re.compile(r"可用现金.{0,16}\d+(?:\.\d+)?\s*%"),
        re.compile(rf"使用资金.{{0,12}}{add_tiers}\s*%"),
        re.compile(rf"账户资金.{{0,12}}{add_tiers}\s*%"),
        re.compile(rf"使用账户.{{0,12}}{add_tiers}\s*%"),
        re.compile(rf"配置.{{0,8}}{add_tiers}\s*%.{{0,12}}账户"),
        re.compile(rf"{add_tiers}\s*%.{{0,8}}(?:的)?(?:账户资产|可用现金|账户资金)"),
    )


ADD_ACCOUNT_RATIO_FORBIDDEN = build_add_account_ratio_forbidden()
LIMIT_NORMALIZE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"可卖|sellable", re.I), SELLABLE_LIMITATION),
    (
        re.compile(
            r"账户总资产|可用现金|账户仓位|绝对账户|具体买入金额|无法计算账户仓位"
            r"|买入数量仅按当前持股比例"
        ),
        CASH_LIMITATION,
    ),
    (re.compile(r"不足一个\s*100\s*股|不足一个100股交易单位"), ADD_LOT_LIMITATION),
    (re.compile(r"当前价格不可用|无法计算预计所需金额"), PRICE_AMOUNT_LIMITATION),
    (re.compile(r"不包含手续费|实际成交价偏差"), AMOUNT_ESTIMATE_NOTE),
    (re.compile(r"持股数量不可用"), SHARES_LIMITATION),
    (re.compile(r"历史\s*K|技术指标|支撑位|压力位|均线|N\s*日|趋势"), KLINE_LIMITATION),
    (re.compile(r"公告|新闻|机构|催化|龙虎榜"), CATALYST_LIMITATION),
)


def collect_context_numbers(obj: Any, output: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        value = float(obj)
        if math.isfinite(value):
            output.add(value)
            output.add(abs(value))
        return
    if isinstance(obj, str):
        for match in NUM_TOKEN_RE.finditer(obj):
            try:
                output.add(float(match.group(1)))
            except ValueError:
                continue
        return
    if isinstance(obj, dict):
        for value in obj.values():
            collect_context_numbers(value, output)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            collect_context_numbers(value, output)


def number_allowed(number: float, allowed: set[float]) -> bool:
    for candidate in allowed:
        if abs(candidate - number) <= 1e-6:
            return True
        scale = max(abs(candidate), abs(number), 1.0)
        if abs(candidate - number) / scale <= 1e-4:
            return True
    return False


def validate_condition_numbers(
    fields: dict[str, list[str]], *, allowed_numbers: set[float], code: str
) -> None:
    for field, items in fields.items():
        for item in items:
            for match in NUM_TOKEN_RE.finditer(item):
                number = float(match.group(1))
                if not number_allowed(number, allowed_numbers):
                    raise PortfolioAdviceValidationError(
                        f"条件字段含无法追溯的数字 {number}（field={field}, code={code}）：{item[:80]}"
                    )


def join_condition_texts(fields: dict[str, list[str]]) -> str:
    return "\n".join(
        item.strip()
        for items in fields.values()
        for item in items
        if isinstance(item, str) and item.strip()
    )


def strip_add_execution_phrases(text: str) -> str:
    text = ADD_BUY_QTY_RE.sub(" ", text)
    text = ADD_AMOUNT_VERB_RE.sub(" ", text)
    text = ADD_AMOUNT_APPROX_RE.sub(" ", text)
    return ADD_AMOUNT_SYMBOL_RE.sub(" ", text)


def amount_match_to_yuan(match: re.Match[str]) -> tuple[float, bool] | None:
    groups = match.groupdict()
    raw = groups.get("num") or groups.get("num_sym") or groups.get("num2")
    if raw is None:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    yuan = number * 10000.0 if (groups.get("unit") or "") == "万元" else number
    approximate = bool(re.search(r"约|大约|预计|约需", groups.get("head") or ""))
    return yuan, approximate


def iter_add_amount_mentions(text: str) -> list[tuple[float, bool]]:
    hits: list[tuple[float, bool, int, int]] = []

    def consider(match: re.Match[str], *, check_price_prefix: bool) -> None:
        if check_price_prefix and PRICE_FACT_PREFIX_RE.search(
            text[max(0, match.start() - 6) : match.start()]
        ):
            return
        parsed = amount_match_to_yuan(match)
        if parsed is None:
            return
        if any(
            start <= match.start() < end or start < match.end() <= end
            for _, _, start, end in hits
        ):
            return
        hits.append((*parsed, match.start(), match.end()))

    for match in ADD_AMOUNT_VERB_RE.finditer(text):
        consider(match, check_price_prefix=False)
    for match in ADD_AMOUNT_APPROX_RE.finditer(text):
        consider(match, check_price_prefix=True)
    for match in ADD_AMOUNT_SYMBOL_RE.finditer(text):
        consider(match, check_price_prefix=True)
    return [(yuan, approximate) for yuan, approximate, _, _ in hits]


def validate_add_text(
    text: str,
    *,
    execution_quantity: int | None,
    estimated_amount: float | None,
    code: str,
) -> None:
    for pattern in ADD_ACCOUNT_RATIO_FORBIDDEN:
        if pattern.search(text):
            raise PortfolioAdviceValidationError(
                f"add 禁止将比例表述为账户/总资产/可用资金比例（code={code}）"
            )

    quantity_matches = list(ADD_BUY_QTY_RE.finditer(text))
    if execution_quantity is None and quantity_matches:
        raise PortfolioAdviceValidationError(
            f"add 无具体买入数量时不得提出新增买入股数（code={code}）"
        )
    if execution_quantity is not None:
        for match in quantity_matches:
            if abs(float(match.group(1)) - float(execution_quantity)) > 1e-6:
                raise PortfolioAdviceValidationError(
                    f"add 文字买入股数与后端计算不一致（code={code}）："
                    f"期望 {execution_quantity}，文字 {match.group(0)!r}"
                )

    mentions = iter_add_amount_mentions(text)
    if estimated_amount is None and mentions:
        raise PortfolioAdviceValidationError(
            f"add 无预计金额时不得提出具体新增投入金额（code={code}）"
        )
    if estimated_amount is not None:
        for yuan, approximate in mentions:
            tolerance = (
                max(1.0, abs(estimated_amount) * 0.005) if approximate else 0.01
            )
            if abs(yuan - estimated_amount) > tolerance + 1e-9:
                raise PortfolioAdviceValidationError(
                    f"add 文字投入金额与后端计算不一致（code={code}）："
                    f"期望 {estimated_amount}，文字约 {yuan}"
                )


def normalize_limitation_list(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip()
        final = text
        for pattern, standard in LIMIT_NORMALIZE_RULES:
            if pattern.search(text):
                final = standard
                break
        if final not in seen:
            seen.add(final)
            output.append(final)
    return output


def allowed_numbers_for_holding(
    base: set[float],
    facts: dict[str, Any],
    size_pct: float | None,
    quantity: int | None,
    amount: float | None,
) -> set[float]:
    allowed = set(base)
    for value in (size_pct, quantity, amount):
        if value is not None:
            allowed.add(float(value))
    if amount is not None:
        wan = amount / 10000.0
        allowed.update({wan, round(wan, 2), round(wan, 1)})
        tolerance = max(1.0, abs(amount) * 0.005)
        for value in range(
            int(math.floor(amount - tolerance)), int(math.ceil(amount + tolerance)) + 1
        ):
            allowed.add(float(value))
    for key in (
        "shares",
        "cost_price",
        "current_price",
        "market_value",
        "pnl_amount",
        "pnl_pct",
        "holding_weight_pct",
    ):
        value = facts.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            allowed.add(float(value))
    return allowed


def audit_holding_narrative(
    item: dict,
    *,
    allowed_base_numbers: set[float],
) -> dict:
    schema = item["schema"]
    facts = item["facts"]
    execution = item["execution"]
    action = schema["action"]
    code = facts["code"]
    conditions = schema["conditions"]
    quantity = execution["execution_quantity"]
    amount = execution["estimated_amount"]
    allowed = allowed_numbers_for_holding(
        allowed_base_numbers, facts, item["size_pct"], quantity, amount
    )

    if action == "add":
        stripped = {
            field: [strip_add_execution_phrases(text) for text in texts]
            for field, texts in conditions.items()
        }
        validate_condition_numbers(stripped, allowed_numbers=allowed, code=code)
        validate_add_text(
            join_condition_texts(conditions),
            execution_quantity=quantity,
            estimated_amount=amount,
            code=code,
        )
    else:
        validate_condition_numbers(conditions, allowed_numbers=allowed, code=code)

    invalidation = conditions["invalidation_conditions"]
    if action in ("reduce", "sell"):
        text = "；".join(invalidation)
        if RISK_WORSEN_RE.search(text) and CANCEL_RISK_ACTION_RE.search(text):
            raise PortfolioAdviceValidationError(
                f"reduce/sell 失效条件与风险控制冲突（code={code}）："
                "不得在风险恶化/继续下跌时暂停减仓或取消卖出"
            )
    for field, texts in conditions.items():
        for text in texts:
            if MARKET_IMPACT_RE.search(text):
                raise PortfolioAdviceValidationError(
                    f"无流动性/盘口数据时禁止市场冲击类话术（field={field}, code={code}）"
                )

    limitations = list(schema["data_limitations"])
    if action in ("reduce", "sell"):
        append_unique(limitations, SELLABLE_LIMITATION)
    if action == "add":
        append_unique(limitations, CASH_LIMITATION)
        if execution["add_shares_missing"]:
            append_unique(limitations, SHARES_LIMITATION)
        if execution["add_lot_insufficient"]:
            append_unique(limitations, ADD_LOT_LIMITATION)
        if execution["add_price_missing"]:
            append_unique(limitations, PRICE_AMOUNT_LIMITATION)
        if amount is not None:
            append_unique(limitations, AMOUNT_ESTIMATE_NOTE)

    return {
        **facts,
        "action": action,
        "execution_size_pct_of_holding": item["size_pct"],
        "execution_quantity": quantity,
        "estimated_amount": amount,
        **conditions,
        "confidence": schema["confidence"],
        "data_limitations": normalize_limitation_list(limitations),
    }


def normalize_top_level_lists(ai_work: dict, context: dict) -> tuple[list[str], list[str]]:
    from portfolio_advice_schema import as_list, str_list

    limitations = str_list(ai_work.get("data_limitations"))
    for message in as_list(context.get("data_limitations")):
        if isinstance(message, str):
            append_unique(limitations, message.strip())
    append_unique(limitations, SELLABLE_LIMITATION)
    append_unique(limitations, CASH_LIMITATION)

    warnings = str_list(ai_work.get("warnings"))
    for warning in as_list(context.get("warnings")):
        if isinstance(warning, str):
            append_unique(warnings, warning.strip())
    return normalize_limitation_list(limitations), dedupe_str_list(warnings)
