"""Explicit recorded research execution lifecycle; comparison is read-only."""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
import experiment_ledger as ledger

router = APIRouter(prefix='/api/research-experiments', tags=['research-experiments'])

class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str
    input: dict


def guarded(fn, response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return fn()
    except LookupError:
        raise HTTPException(404, '实验记录不存在') from None
    except (ValueError, ledger.store.StoreError):
        raise HTTPException(422, '实验记录无法核对；检查输入合同或归档状态，原记录已保留') from None

@router.get('')
def listing(response: Response):
    return guarded(lambda: {'records': ledger.records(), 'limit': ledger.LIMIT}, response)

@router.post('')
def start(body: Start, response: Response):
    return guarded(lambda: ledger.create(body.kind, body.input), response)

@router.post('/{identity}/cancel')
def cancel(identity: str, response: Response):
    return guarded(lambda: ledger.cancel(identity), response)

@router.get('/compare')
def compare(left: str, right: str, response: Response):
    def read():
        with ledger.store.read() as conn:
            return ledger.compare(ledger._find(conn, left), ledger._find(conn, right))
    return guarded(read, response)
