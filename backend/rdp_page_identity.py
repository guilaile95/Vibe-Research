"""Fail-closed identity guard for a multi-page current Full Market read.

The first response selects an immutable generation. Every later call must ask
for that generation, not the mutable current manifest. No filesystem access.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date
import re
from typing import Any


class PageIdentityError(ValueError):
    pass


class FullMarketPageIdentity:
    def __init__(self) -> None:
        self.snapshot_id: str | None = None
        self._identity: dict[str, Any] | None = None

    def query(self) -> dict[str, Any]:
        return {} if self.snapshot_id is None else {"snapshot_id": self.snapshot_id}

    def accept(self, envelope: Mapping[str, Any]) -> None:
        snapshot = envelope.get("snapshot_id")
        if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot):
            raise PageIdentityError("missing_or_invalid_snapshot_id")
        identity = {key: deepcopy(envelope.get(key)) for key in (
            "snapshot_id", "as_of", "latest_date", "dataset_id", "provider_id", "adjustment", "provenance",
        )}
        for key in ("as_of", "latest_date"):
            try:
                value = identity[key]
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError as exc:
                raise PageIdentityError("missing_or_invalid_page_date") from exc
        if identity["as_of"] != identity["latest_date"]:
            raise PageIdentityError("inconsistent_page_date")
        if (identity["dataset_id"] != "ashare_daily_unadjusted"
                or identity["provider_id"] != "local_bulk_dump"
                or identity["adjustment"] != "UNADJUSTED"
                or not isinstance(identity["provenance"], Mapping)
                or not identity["provenance"]):
            raise PageIdentityError("invalid_page_provenance")
        if self._identity is not None and identity != self._identity:
            raise PageIdentityError("pagination_identity_changed")
        self.snapshot_id = snapshot
        self._identity = identity
