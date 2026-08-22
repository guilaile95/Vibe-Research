"""持仓建议账户资金指标计算（纯函数，不联网、不调模型、不写文件）。

在 portfolio_advice_validator.validate_portfolio_advice() 返回权威结果后，
追加只读账户资金指标 account_funding 与逐持仓 account_metrics。

本模块不修改已有 action / execution_size_pct_of_holding /
execution_quantity / estimated_amount 等建议字段。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import account_profile


def attach_account_funding_metrics(result: dict, portfolio_data: dict) -> dict:
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
    st = account_profile.get_account_profile_status()

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

    is_valid = (st["status"] == "valid" and st["data"] is not None)
    if is_valid:
        total_assets_dec = Decimal(str(st["data"]["total_assets"]))
        cash_dec = Decimal(str(st["data"]["available_cash"]))
        cash_pct_dec = (cash_dec / total_assets_dec * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        available_cash_pct = float(cash_pct_dec)
        total_assets_val = st["data"]["total_assets"]
        available_cash_val = st["data"]["available_cash"]
        updated_at_val = st["data"]["updated_at"]
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
            if is_valid:
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

    if is_valid:
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
            "status": "valid",
            "reason_code": None,
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
        res["account_funding"] = {
            "configured": False,
            "status": st["status"],
            "reason_code": st.get("reason_code"),
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
    if st["status"] == "corrupted":
        data_limitations.append("账户资金配置文件读取失败或损坏，未计算账户级仓位指标")
    if is_valid and not complete:
        data_limitations.append("部分持仓行情不可用，已跟踪持仓占总资产比例未计算")
    res["data_limitations"] = data_limitations

    return res
