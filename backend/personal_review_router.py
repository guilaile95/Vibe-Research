"""Explicit local user surface; deliberately absent from model tool registries."""
from fastapi import APIRouter, HTTPException, Request
import personal_review as review
import personal_review_price_basis as basis

router = APIRouter(prefix="/api/personal-review", tags=["personal-review"])


def _call(request, action):
    if request.query_params:
        raise HTTPException(422, "不支持额外参数或调用方时间戳")
    try:
        return {"data": action()}
    except (review.ReviewError, basis.BasisError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        # Never expose private database paths or raw upstream errors.
        raise HTTPException(503, "个人复查数据不可安全读取或保存") from exc


@router.get("")
def read(request: Request):
    return _call(request, review.view)


@router.put("/assessments/{trade_id}")
def assessment(trade_id: str, body: review.Assessment, request: Request):
    return _call(request, lambda: review.save("assessment", trade_id, body))


@router.put("/patterns/{pattern_id}")
def pattern(pattern_id: str, body: review.Pattern, request: Request):
    return _call(request, lambda: review.save("pattern", pattern_id, body))


@router.get("/episodes/{episode_id}/excursion")
def excursion(episode_id: str, request: Request):
    def run():
        episode = next((e for e in review.view()["closed_episodes"] if e["episode_id"] == episode_id), None)
        if episode is None:
            raise review.ReviewError("轮次已改变或不存在，请重新加载")
        return review.excursion(episode)
    return _call(request, run)


@router.post("/price-basis/preview")
def preview_basis(body: basis.CaptureRequest, request: Request):
    return _call(request, lambda: basis.qualify(body.raw_json)[2])


@router.post("/price-basis/archive")
def archive_basis(body: basis.CaptureRequest, request: Request):
    return _call(request, lambda: basis.archive(body.raw_json))


@router.get("/price-basis/receipts/{digest}")
def basis_receipt(digest: str, request: Request):
    return _call(request, lambda: basis.receipt(digest))
