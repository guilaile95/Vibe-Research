"""Read a seal-quality projection from an explicitly configured existing archive.

No archive creation, ingestion, provider refresh, inferred date or new authority.
Only existing public FactLake readers and the frozen publication/replay contracts
may select the input. Local publication order is not point-in-time source truth.
"""
from __future__ import annotations

from datetime import date
import os
import re
from typing import Any

from data_contracts import TemporalSemantics
from fact_lake_publication_selection import (
    PublicationSelectionMode, PublicationSelectionRequest, select_canonical_publications,
)
from fact_lake_store import (
    FactLakeBusyError, FactLakeNotInitializedError, FactLakeSchemaVersionError,
    open_existing_fact_lake_snapshot,
)
import limit_up_shadow as shadow
from short_term_seal_quality import build_seal_quality_observation

SCHEMA_VERSION = "short-term-seal-quality-archive-v0.1"
_MESSAGES = {
    "ARCHIVE_BUSY": "归档正在变化，暂时无法取得稳定只读证据；请稍后重试。",
    "ARCHIVE_NOT_CONNECTED": "封板质量归档证据未连接；不会自动启用采集或请求行情。",
    "ARCHIVE_NOT_INITIALIZED": "配置的归档尚不存在或未初始化；本次只读查询不会创建它。",
    "ARCHIVE_OBSERVATION_MISSING": "这个交易日没有已发布的涨停池归档；不会用其他日期代替。",
    "ARCHIVE_VERSION_UNSUPPORTED": "归档版本当前不受支持；未修改或自动迁移数据。",
    "ARCHIVE_VALIDATION_FAILED": "归档身份或完整性校验未通过，封板质量结果已隐藏。",
}


def validate_trade_date(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("trade_date 必须为 YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("trade_date 不是有效日期") from None
    return value


def _empty(trade_date: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "trade_date": trade_date,
        "status": "unavailable", "reason_codes": [code], "message": _MESSAGES[code],
        "selection": None, "archive_identity": None, "projection": None,
        "archive_only": True, "ingestion_enabled": False,
    }


def query_seal_quality(trade_date: str) -> dict[str, Any]:
    """Read exact-date committed archive evidence; return only safe public data."""
    trade_date = validate_trade_date(trade_date)
    root = os.environ.get("VR_FACT_LAKE_ROOT", "").strip()
    if not root:
        return _empty(trade_date, "ARCHIVE_NOT_CONNECTED")
    try:
        lake = open_existing_fact_lake_snapshot(root)
        def finish(result):
            lake.assert_unchanged()
            return result

        candidates = lake.list_canonical_publications(
            dataset_id=shadow.DATASET_ID, primary_temporal_field=TemporalSemantics.TRADE_DATE,
            primary_temporal_value=trade_date,
        )
        selection = select_canonical_publications(
            shadow.LIMIT_UP_DATASET_SPEC,
            PublicationSelectionRequest(
                dataset_id=shadow.DATASET_ID, canonical_key=f"{shadow.DATASET_ID}:{trade_date}",
                primary_temporal_field=TemporalSemantics.TRADE_DATE, primary_temporal_value=trade_date,
                mode=PublicationSelectionMode.LOCAL_LATEST,
            ),
            candidates,
        )
        ids = selection.selected_publication_ids
        if not ids:
            return finish(_empty(trade_date, "ARCHIVE_OBSERVATION_MISSING"))
        publication = next(item for item in candidates if item.publication_id == ids[0])
        if (
            publication.dataset_contract_revision != shadow.DATASET_CONTRACT_REVISION
            or publication.normalizer_version != shadow.NORMALIZER_VERSION
            or publication.artifact_schema_version != shadow.ARTIFACT_SCHEMA_VERSION
        ):
            return finish(_empty(trade_date, "ARCHIVE_VERSION_UNSUPPORTED"))
        verification = shadow.verify_normalization_replay(lake, publication.source_observation_id)
        replay = verification.replay
        observation = replay.observation.observation
        if (
            verification.status != "MATCH" or not replay.canonical_admissible
            or observation.observation_id != publication.source_observation_id
            or observation.dataset_id != publication.dataset_id
            or observation.trade_date != trade_date
            or publication.fact.trade_date != trade_date
            or observation.normalizer_version != publication.normalizer_version
            or observation.source_payload_hash != publication.raw_payload_hash
            or tuple(publication.fact.source_observation_ids) != (observation.observation_id,)
            or publication.fact.canonical_payload != replay.normalized_payload
        ):
            return finish(_empty(trade_date, "ARCHIVE_VALIDATION_FAILED"))
        # All metadata comes from the verified persisted receipt, never the URL.
        payload = lake.read_payload(observation.observation_id)
        projection = build_seal_quality_observation(
            payload, requested_trade_date=observation.trade_date,
            http_status=observation.payload["response"]["http_status"], observed_at=observation.fetched_at,
        )
        if (
            f"sha256:{projection['raw_payload_sha256']}" != publication.raw_payload_hash
            or projection["source_trade_date"] != trade_date
        ):
            return finish(_empty(trade_date, "ARCHIVE_VALIDATION_FAILED"))
        lake.assert_unchanged()
        return {
            "schema_version": SCHEMA_VERSION, "trade_date": trade_date,
            "status": projection["status"], "reason_codes": projection["reason_codes"],
            "message": "已读取所选本地发布绑定的归档观测；不是实时行情、收盘定稿或可成交性证明。",
            "selection": selection.to_dict(),
            "archive_identity": {
                "publication_id": publication.publication_id,
                "source_observation_id": observation.observation_id,
                "raw_payload_hash": publication.raw_payload_hash,
                "captured_at": observation.fetched_at,
            },
            "projection": projection, "archive_only": True, "ingestion_enabled": False,
        }
    except FactLakeBusyError:
        return _empty(trade_date, "ARCHIVE_BUSY")
    except FactLakeNotInitializedError:
        return _empty(trade_date, "ARCHIVE_NOT_INITIALIZED")
    except (FactLakeSchemaVersionError, shadow.LimitUpReplayUnsupportedError):
        return _empty(trade_date, "ARCHIVE_VERSION_UNSUPPORTED")
    except Exception:
        # Paths, payloads, provider exception text and traceback never cross HTTP.
        return _empty(trade_date, "ARCHIVE_VALIDATION_FAILED")
