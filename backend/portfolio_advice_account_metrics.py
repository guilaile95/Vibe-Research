"""持仓建议账户资金指标计算（纯函数，不联网、不调模型、不写文件）。

在 portfolio_advice_validator.validate_portfolio_advice() 返回权威结果后，
追加只读账户资金指标 account_funding 与逐持仓 account_metrics。

本模块不修改已有 action / execution_size_pct_of_holding /
execution_quantity / estimated_amount 等建议字段。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import account_reality_service


def attach_account_funding_metrics(
    result: dict,
    portfolio_data: dict,
    account_reality: dict | None = None,
) -> dict:
    """在 validator 权威结果后，追加只读账户资金指标。

    Parameters
    ----------
    result
        ``validate_portfolio_advice`` 的权威结果 dict（会被本函数就地修改并返回）。
    portfolio_data
        当前持仓数据（来自 ``portfolio.get_portfolio()``），用于获取最新价格。

    Returns
    -------
    dict
        注入了 ``account_funding`` 顶层字段与各持仓 ``account_metrics`` 的结果。
        原 action / execution_size_pct_of_holding / execution_quantity /
        estimated_amount 绝不被触碰。
    """
    res = result
    reality = (
        account_reality
        if account_reality is not None
        else account_reality_service.get_account_reality()
    )
    cash = reality.get("cash") if isinstance(reality, dict) else None
    cash_fact = cash.get("current_fact") if isinstance(cash, dict) else None
    total_assets = reality.get("account_total_assets") if isinstance(reality, dict) else None
    total_fact = (
        total_assets.get("current_fact") if isinstance(total_assets, dict) else None
    )
    authority = reality.get("account_authority") if isinstance(reality, dict) else None

    holdings_data = portfolio_data.get("holdings", []) if isinstance(portfolio_data, dict) else []
    holding_price_map: dict[str, Any] = {}
    holding_shares_map: dict[str, Any] = {}
    for h in holdings_data:
        if isinstance(h, dict) and "code" in h:
            holding_price_map[h["code"]] = h.get("price")
            holding_shares_map[h["code"]] = h.get("shares")

    total_holdings = len(res.get("holdings", []))
    valid_holdings = 0
    tracked_stock_mv_sum = Decimal("0")

    configured = (
        isinstance(cash_fact, dict)
        and cash_fact.get("value") is not None
        and isinstance(total_fact, dict)
        and total_fact.get("value") is not None
    )
    canonical = reality.get("canonical") is True
    canonical_reason_codes = list(reality.get("canonical_reason_codes") or [])
    if configured:
        total_assets_dec = Decimal(str(total_fact["value"]))
        cash_dec = Decimal(str(cash_fact["value"]))
        cash_pct_dec = (cash_dec / total_assets_dec * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        available_cash_pct = float(cash_pct_dec)
        total_assets_val = total_fact["value"]
        available_cash_val = cash_fact["value"]
        updated_at_val = cash_fact.get("updated_at")
    else:
        available_cash_pct = None
        total_assets_val = None
        available_cash_val = None
        updated_at_val = None

    new_holdings = []
    for h in res.get("holdings", []):
        h_copy = dict(h)
        code = h_copy.get("code")
        shares = h_copy.get("shares")
        px = holding_price_map.get(code, h_copy.get("current_price"))

        price_valid = (
            not isinstance(px, bool)
            and isinstance(px, (int, float))
            and px > 0
            and px == px
            and px not in (float("inf"), float("-inf"))
        )
        pf_shares = holding_shares_map.get(code, shares)
        shares_valid = (
            not isinstance(shares, bool)
            and isinstance(shares, (int, float))
            and shares > 0
            and shares == shares
            and shares not in (float("inf"), float("-inf"))
            and not isinstance(pf_shares, bool)
            and isinstance(pf_shares, (int, float))
            and pf_shares > 0
            and pf_shares == pf_shares
            and pf_shares not in (float("inf"), float("-inf"))
        )

        if price_valid and shares_valid:
            valid_holdings += 1
            mv_dec = (Decimal(str(shares)) * Decimal(str(px))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            tracked_stock_mv_sum += mv_dec
            mv_val = float(mv_dec)
            if configured:
                acct_weight_dec = (mv_dec / total_assets_dec * Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                acct_weight_val = float(acct_weight_dec)
            else:
                acct_weight_val = None
            h_copy["account_metrics"] = {
                "market_value": mv_val,
                "account_weight_pct": acct_weight_val,
            }
        else:
            h_copy["account_metrics"] = {
                "market_value": None,
                "account_weight_pct": None,
            }
        new_holdings.append(h_copy)

    res["holdings"] = new_holdings
    complete = total_holdings > 0 and valid_holdings == total_holdings

    if configured:
        if complete:
            tracked_mv_val = float(
                tracked_stock_mv_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            tracked_weight_dec = (
                tracked_stock_mv_sum / total_assets_dec * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tracked_weight_val = float(tracked_weight_dec)
        else:
            tracked_mv_val = None
            tracked_weight_val = None

        res["account_funding"] = {
            "configured": True,
            "canonical": canonical,
            "status": "valid" if canonical else "partial",
            "reason_code": (
                None
                if canonical
                else canonical_reason_codes[0]
                if canonical_reason_codes
                else "ACCOUNT_REALITY_NOT_CANONICAL"
            ),
            "canonical_reason_codes": canonical_reason_codes,
            "authority_state": authority.get("state") if isinstance(authority, dict) else None,
            "confirmation_id": cash_fact.get("confirmation_id"),
            "effective_at": cash_fact.get("effective_at"),
            "recorded_at": cash_fact.get("recorded_at"),
            "total_assets": total_assets_val,
            "available_cash": available_cash_val,
            "available_cash_pct": available_cash_pct,
            "updated_at": updated_at_val,
            "tracked_stock_market_value": tracked_mv_val,
            "tracked_stock_weight_pct": tracked_weight_val,
            "quote_coverage": {
                "valid_holdings": valid_holdings,
                "total_holdings": total_holdings,
                "complete": complete,
            },
        }
    else:
        current_status = cash_fact.get("status") if isinstance(cash_fact, dict) else None
        corrupted = current_status == "CORRUPTED"
        unavailable = "ACCOUNT_REALITY_UNAVAILABLE" in canonical_reason_codes
        res["account_funding"] = {
            "configured": False,
            "canonical": False,
            "status": "corrupted" if corrupted else "partial" if unavailable else "not_configured",
            "reason_code": (
                cash_fact.get("reason_code")
                if isinstance(cash_fact, dict) and cash_fact.get("reason_code")
                else canonical_reason_codes[0]
                if canonical_reason_codes
                else None
            ),
            "canonical_reason_codes": canonical_reason_codes,
            "authority_state": authority.get("state") if isinstance(authority, dict) else None,
            "confirmation_id": None,
            "effective_at": None,
            "recorded_at": None,
            "total_assets": None,
            "available_cash": None,
            "available_cash_pct": None,
            "updated_at": None,
            "tracked_stock_market_value": None,
            "tracked_stock_weight_pct": None,
            "quote_coverage": {
                "valid_holdings": valid_holdings,
                "total_holdings": total_holdings,
                "complete": complete,
            },
        }

    data_limitations = list(res.get("data_limitations", []))
    if res["account_funding"]["status"] == "corrupted":
        data_limitations.append("账户资金配置文件读取失败或损坏，未计算账户级仓位指标")
    if configured and not canonical:
        data_limitations.append("账户事实未达到 canonical，新增风险操作不形成可执行数量")
    if configured and not complete:
        data_limitations.append("部分持仓行情不可用，已跟踪持仓占总资产比例未计算")
    res["data_limitations"] = data_limitations

    return res
