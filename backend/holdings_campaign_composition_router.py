"""Read-only HTTP surface for the canonical Holding→Campaign composition."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import account_event_store
import campaign_service
import holdings_campaign_composition as service
import position_reality_service
import trade_ledger_store


router = APIRouter(prefix="/api", tags=["holdings-campaign-composition"])

_INVALID_QUERY_DETAIL = "持仓-Campaign 组成查询参数无效"
_POSITION_UNAVAILABLE_DETAIL = "持仓事实不可用，无法生成持仓-Campaign 组成"
_ACCOUNT_CORRUPTED_DETAIL = "账户事件数据损坏，已停止读写"
_TRADE_CORRUPTED_DETAIL = "交易流水数据损坏，已停止读写"
_CAMPAIGN_UNAVAILABLE_DETAIL = "Campaign 服务暂不可用"
_INTERNAL_ERROR_DETAIL = "持仓-Campaign 组成暂不可用"


@router.get("/holdings/campaign-composition")
def get_holdings_campaign_composition(request: Request) -> dict:
    if request.query_params:
        raise HTTPException(422, _INVALID_QUERY_DETAIL)
    try:
        result = service.assemble_holdings_campaign_composition()
    except (
        position_reality_service.PositionDerivationError,
        service.HoldingsCampaignCompositionError,
    ):
        raise HTTPException(500, _POSITION_UNAVAILABLE_DETAIL) from None
    except account_event_store.AccountEventCorruptedError:
        raise HTTPException(500, _ACCOUNT_CORRUPTED_DETAIL) from None
    except trade_ledger_store.TradeLedgerCorruptedError:
        raise HTTPException(500, _TRADE_CORRUPTED_DETAIL) from None
    except campaign_service.CampaignServiceError:
        raise HTTPException(500, _CAMPAIGN_UNAVAILABLE_DETAIL) from None
    except Exception:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": result}


__all__ = ["router"]
