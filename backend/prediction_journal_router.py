"""Explicit manual journal; no automatic outcome resolution."""
from fastapi import APIRouter, HTTPException, Response
import prediction_journal as journal

router = APIRouter(prefix='/api/prediction-journal', tags=['personal-review'])


def guarded(fn, response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return fn()
    except journal.Conflict:
        raise HTTPException(409, '记录已变化或预测已锁定，请重新读取核对') from None
    except LookupError:
        raise HTTPException(404, '预测记录不存在') from None
    except (ValueError, journal.store.StoreError):
        raise HTTPException(422, '预测记录无法核对；检查时间、输入及归档，原记录已保留') from None


@router.get('')
def listing(response: Response, as_of: str | None = None):
    return guarded(lambda: journal.listing(as_of), response)


@router.post('')
def create(body: journal.Forecast, response: Response):
    return guarded(lambda: journal.create(body), response)


@router.post('/{identity}/resolutions')
def resolve(identity: str, body: journal.Resolution, response: Response):
    return guarded(lambda: journal.resolve(identity, body), response)
