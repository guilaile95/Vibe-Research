"""P0-S1B-A account reality HTTP API（只读）。

服务输出 + 稳定错误映射；计算逻辑不放 router。
未预期内部错误对客户端脱敏（fail closed），不泄漏内部细节。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import account_reality_service as svc

router = APIRouter(prefix="/api", tags=["account-reality"])


@router.get("/account/reality")
async def account_reality():
    try:
        result = svc.get_account_reality()
    except Exception:
        # 客户端脱敏：任何内部错误统一 500，不泄漏 traceback / SQL / 内部路径
        raise HTTPException(status_code=500, detail="内部错误")
    return {"data": result}
