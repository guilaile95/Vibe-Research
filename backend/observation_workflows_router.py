"""Read-only observations plus explicit private task actions; no live activation."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

import next_day_verification
import observation_workflow_store as store
import observation_workflows as obs
import observation_reminders as reminders
from observation_workflow_preview import preview

router = APIRouter(prefix='/api/observation-workflows', tags=['observation-workflows'])

class EmptyAction(BaseModel):
    model_config = ConfigDict(extra='forbid')


def execute(request, action):
    if request.query_params:
        raise HTTPException(422, '不支持额外参数或调用方时间戳')
    try:
        return {'data': action()}
    except obs.ObservationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (store.StoreError, next_day_verification.JournalError):
        raise HTTPException(503, '本地观察或验证归档不可用，请稍后重读') from None
    except Exception:
        raise HTTPException(503, '观察任务不可用，未启用外部发送') from None


@router.get('/preview')
def synthetic_preview(request: Request):
    return execute(request, preview)


@router.get('/{day}')
def read(day: str, request: Request):
    return execute(request, lambda: obs.view(day))


@router.post('/{day}/tasks/{kind}/run')
def run(day: str, kind: str, body: EmptyAction, request: Request):
    # No producer URL, token, recipients, timestamp or raw provider data admitted.
    return execute(request, lambda: reminders.run_local_task(day, kind))


@router.post('/{day}/tasks/{kind}/acknowledge')
def acknowledge(day: str, kind: str, body: EmptyAction, request: Request):
    return execute(request, lambda: reminders.acknowledge(day, kind))
