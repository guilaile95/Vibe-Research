"""DCH1 E2E app: keep the first real Critical Data projection stable per preview."""

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping
from typing import Any

import campaign_critical_data_runtime


_project = campaign_critical_data_runtime.project_campaign_critical_data
_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
_lock = threading.Lock()


def _fixed_first_projection(*args: Any, **kwargs: Any) -> dict[str, Any]:
    campaign = kwargs.get("campaign", args[0] if args else None)
    as_of = kwargs.get("as_of", args[1] if len(args) > 1 else None)
    if not isinstance(campaign, Mapping) or not isinstance(as_of, str):
        return _project(*args, **kwargs)
    key = (str(campaign.get("campaign_id", "")), as_of)
    with _lock:
        if key not in _snapshots:
            _snapshots[key] = copy.deepcopy(_project(*args, **kwargs))
        return copy.deepcopy(_snapshots[key])


campaign_critical_data_runtime.project_campaign_critical_data = _fixed_first_projection

from app import app  # noqa: E402  (patch Critical Data before app/runtime import)
