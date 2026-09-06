"""Global AI credential mirror. Not a Native Intel endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import ai_credential_store as store

router = APIRouter(prefix="/api/ai", tags=["ai-credential"])


class CredentialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    baseURL: str = ""
    apiKey: str = Field(default="", repr=False)


@router.put("/credential")
def put_credential(payload: CredentialIn) -> dict[str, Any]:
    try:
        return store.save(payload.model_dump())
    except store.CredentialStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="后台凭据保存失败") from None


@router.get("/credential-status")
def get_credential_status() -> dict[str, Any]:
    return store.status()


@router.delete("/credential")
def delete_credential() -> dict[str, Any]:
    try:
        return store.delete()
    except store.CredentialStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="后台凭据删除失败") from None
