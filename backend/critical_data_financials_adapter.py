"""P0-CDA1B — ``cap.security.financials`` critical-data capability adapter.

对 ``Security + Campaign + as_of``，在上游已显式给出所需 ``report_period``
的前提下，回答：当前 Fact Lake 中是否存在一条可被正式接受的 canonical
financial indicator publication？

链条（全部复用 stable authorities，只读、零写入）：

    explicit report_period_state / report_period / authority refs
      → SER1 exchange routing（SSE/SZSE alias；BSE NOT_PROVEN）
      → Q1 canonical publication selection（ALL / PUBLICATION_ID pin）
      → FETCH receipt visibility gate（observation.fetched_at <= as_of）
      → verify_financial_normalization_replay（MATCH 才继续）
      → H2 collect + H1 assess（canonical_admissibility == USABLE 才继续）
      → exact publication query（selection="publication"，as_of=None）
      → payload 契约 + versions metric presence

本模块明确不拥有：
- report period 选择（UPSTREAM_EXPLICIT_ONLY；CDA1B_SELECTS_REPORT_PERIOD = NO）
- provider revision / local-latest / PIT authority（全部 NO）
- financial 分析、评分、估值、盈利质量判断

不产生 BLOCKED / STALE；不调用 provider；不写 Fact Lake。
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import financial_indicator_shadow as shadow
from critical_data_dependency_policy import CAP_SECURITY_FINANCIALS
from data_contracts import TemporalSemantics
from fact_lake_health import SCHEMA_VERSION as HEALTH_SCHEMA_VERSION
from fact_lake_health import assess_publication_health
from fact_lake_health_adapter import (
    HealthCollectionRequest,
    collect_fact_lake_health_evidence,
    HealthEvidenceCollectionError,
)
from fact_lake_publication_selection import (
    PublicationSelectionAmbiguousError,
    PublicationSelectionError,
    PublicationSelectionMode,
    PublicationSelectionNotFoundError,
    PublicationSelectionPitError,
    PublicationSelectionRequest,
    SELECTION_SCHEMA_VERSION,
    select_canonical_publications,
)
from fact_lake_store import FactLake
from security_exchange_policy import (
    POLICY_AUTHORITY_REF_V01,
    POLICY_VERSION_V01 as SER_POLICY_VERSION_V01,
    resolve_security_exchange,
)


DEPENDENCY_ID = CAP_SECURITY_FINANCIALS
ADAPTER_POLICY_VERSION = "critical_data.financials.v0.1"
ADAPTER_AUTHORITY_REF = "critical_data:financials:v0.1"
PROVIDER_ALIAS_AUTHORITY_REF = (
    "critical_data_adapter:fina_indicator_exchange_alias:v0.1"
)
SELECTION_AUTHORITY_REF = f"selection:{SELECTION_SCHEMA_VERSION}"
DATASET_AUTHORITY_REF = (
    f"dataset:{shadow.DATASET_ID}:{shadow.DATASET_CONTRACT_REVISION}"
)
NORMALIZER_AUTHORITY_REF = f"normalizer:{shadow.NORMALIZER_VERSION}"
ARTIFACT_AUTHORITY_REF = f"artifact:{shadow.ARTIFACT_SCHEMA_VERSION}"
HEALTH_COLLECTION_AUTHORITY_REF = "health-collection:fact-lake-health-adapter:v0.1"
HEALTH_AUTHORITY_REF = f"health:{HEALTH_SCHEMA_VERSION}"
REPLAY_AUTHORITY_REF = f"replay:{shadow.DATASET_ID}:{shadow.NORMALIZER_VERSION}"

REPORT_PERIOD_STATES = ("RESOLVED", "UNKNOWN", "NOT_EVALUATED", "ERROR")
EXCHANGE_ALIASES_V01 = {"SSE": ".SH", "SZSE": ".SZ"}

_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


class FinancialsCapabilityError(RuntimeError):
    """输入或 authority 契约非法（调用方错误，fail closed → raise）。"""


def _require_nonempty_text(value: Any, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise FinancialsCapabilityError(f"{field} must be canonical text")
    return value


def _require_security_code(value: Any) -> str:
    value = _require_nonempty_text(value, "security_code")
    if re.fullmatch(r"[0-9]{6}", value) is None:
        raise FinancialsCapabilityError(
            "security_code must be six ASCII digits"
        )
    return value


def _require_campaign_id(value: Any) -> str:
    value = _require_nonempty_text(value, "campaign_id")
    if _CAMPAIGN_ID_RE.fullmatch(value) is None:
        raise FinancialsCapabilityError("campaign_id is invalid")
    return value


def _require_utc_as_of(value: Any) -> str:
    value = _require_nonempty_text(value, "as_of")
    if _UTC_ZERO_OFFSET_RE.fullmatch(value) is None:
        raise FinancialsCapabilityError(
            "as_of must be zero-offset UTC (Z or +00:00)"
        )
    return value


def _parse_utc_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialsCapabilityError("not a parseable UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise FinancialsCapabilityError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _require_canonical_report_period(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise FinancialsCapabilityError("report_period must be YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise FinancialsCapabilityError("report_period is not a valid date") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise FinancialsCapabilityError("report_period must be canonical")
    return value


def _result(
    *,
    state: str,
    security_code: str,
    campaign_id: str,
    as_of: str,
    report_period_state: str,
    report_period: str | None,
    refs: Sequence[str],
    reason_codes: Sequence[str],
    publication_id: str | None = None,
    source_observation_id: str | None = None,
    explainability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "dependency_id": DEPENDENCY_ID,
        "state": state,
        "security_code": security_code,
        "campaign_id": campaign_id,
        "as_of": as_of,
        "report_period_state": report_period_state,
        "report_period": report_period,
        "publication_id": publication_id,
        "source_observation_id": source_observation_id,
        "authority_refs": list(dict.fromkeys(refs)),
        "reason_codes": list(reason_codes),
        "explainability": dict(explainability or {}),
    }


def _simple_reason(reason: str) -> dict[str, Any]:
    return {"what": reason, "basis": "deterministic capability evaluation"}


def _dedup(refs: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(refs))


def _finite_metric_value(value: Any) -> bool:
    if type(value) is bool:
        return False
    if type(value) not in (int, float):
        return False
    return math.isfinite(float(value))


def _has_finite_metric(canonical_payload: Mapping[str, Any]) -> bool:
    versions = canonical_payload.get("versions")
    if not isinstance(versions, list):
        return False
    for row in versions:
        if not isinstance(row, Mapping):
            continue
        for field in shadow.METRIC_FIELDS:
            if field in row and _finite_metric_value(row[field]):
                return True
    return False


def evaluate_financials_capability(
    *,
    lake: FactLake,
    security_code: str,
    campaign_id: str,
    as_of: str,
    report_period_state: str,
    report_period: str | None,
    report_period_authority_refs: Sequence[str],
    security_exchange_policy_version: str,
    adapter_policy_version: str,
    publication_id: str | None = None,
) -> dict[str, Any]:
    """评估 ``cap.security.financials``（只读、零写入、fail closed）。"""
    if not isinstance(lake, FactLake) or not lake.readonly:
        raise FinancialsCapabilityError(
            "financials capability requires a readonly Fact Lake"
        )
    security_code = _require_security_code(security_code)
    campaign_id = _require_campaign_id(campaign_id)
    as_of = _require_utc_as_of(as_of)
    _parse_utc_instant(as_of)

    adapter_policy_version = _require_nonempty_text(
        adapter_policy_version, "adapter_policy_version"
    )
    if adapter_policy_version != ADAPTER_POLICY_VERSION:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state=report_period_state,
            report_period=report_period,
            refs=(),
            reason_codes=["ADAPTER_POLICY_VERSION_NOT_AVAILABLE"],
            explainability=_simple_reason(
                "adapter policy version is not available"
            ),
        )

    if report_period_state not in REPORT_PERIOD_STATES:
        raise FinancialsCapabilityError(
            f"report_period_state must be one of {REPORT_PERIOD_STATES}"
        )
    if report_period_state != "RESOLVED":
        state_map = {
            "UNKNOWN": "UNKNOWN",
            "NOT_EVALUATED": "NOT_EVALUATED",
            "ERROR": "ERROR",
        }
        return _result(
            state=state_map[report_period_state],
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state=report_period_state,
            report_period=None,
            refs=(),
            reason_codes=[f"REPORT_PERIOD_{report_period_state}"],
            explainability=_simple_reason(
                f"report_period_state={report_period_state}"
            ),
        )

    # RESOLVED：report_period 必须 canonical，且必须有上游 authority refs
    period = _require_canonical_report_period(report_period)
    upstream_refs = [
        _require_nonempty_text(ref, "report_period_authority_refs[]")
        for ref in report_period_authority_refs
    ]
    if not upstream_refs:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=(),
            reason_codes=["REPORT_PERIOD_AUTHORITY_NOT_PROVEN"],
            explainability=_simple_reason(
                "RESOLVED report_period requires non-empty upstream "
                "authority refs; naked report_period never proves "
                "applicability"
            ),
        )

    refs: list[str] = [ADAPTER_AUTHORITY_REF, *upstream_refs]
    reasons: list[str] = []

    # SER1 exchange routing
    ser = resolve_security_exchange(
        security_code=security_code,
        policy_version=security_exchange_policy_version,
    )
    if ser["exchange_resolution_state"] == "NOT_EVALUATED":
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["SECURITY_EXCHANGE_POLICY_NOT_AVAILABLE"],
            explainability=_simple_reason(
                "security exchange policy version is not available"
            ),
        )
    if ser["exchange_resolution_state"] != "RESOLVED":
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["SECURITY_EXCHANGE_NOT_RESOLVED"],
            explainability=_simple_reason(
                "canonical exchange routing is not resolved"
            ),
        )
    exchange = ser["exchange"]
    refs.extend([ser["authority_ref"], *ser["source_refs"]])
    if exchange not in EXCHANGE_ALIASES_V01:
        # BSE 六位代码 → Tushare .BJ provider alias 未证明
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["BSE_PROVIDER_ALIAS_NOT_PROVEN"],
            explainability=_simple_reason(
                "BSE provider alias is not proven under v0.1"
            ),
        )
    alias = f"{security_code}{EXCHANGE_ALIASES_V01[exchange]}"
    refs.append(PROVIDER_ALIAS_AUTHORITY_REF)

    # Canonical coordinate（不扫描、不推断 report_period）
    canonical_key = f"{shadow.DATASET_ID}:{alias}:{period}"
    candidates = lake.list_canonical_publications(
        dataset_id=shadow.DATASET_ID,
        primary_temporal_field=TemporalSemantics.REPORT_PERIOD,
        primary_temporal_value=period,
    )
    if publication_id is not None:
        publication_id = _require_nonempty_text(publication_id, "publication_id")
    mode = (
        PublicationSelectionMode.PUBLICATION_ID
        if publication_id is not None
        else PublicationSelectionMode.ALL
    )
    request = PublicationSelectionRequest(
        dataset_id=shadow.DATASET_ID,
        canonical_key=canonical_key,
        primary_temporal_field=TemporalSemantics.REPORT_PERIOD,
        primary_temporal_value=period,
        mode=mode,
        publication_id=publication_id,
    )
    try:
        selection = select_canonical_publications(
            shadow.FINANCIAL_DATASET_SPEC,
            request,
            tuple(candidates),
        )
    except PublicationSelectionNotFoundError:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["PUBLICATION_NOT_FOUND"],
            explainability=_simple_reason(
                "pinned publication is absent; no local-latest fallback"
            ),
        )
    except PublicationSelectionAmbiguousError:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["FINANCIAL_REVISION_SELECTION_NOT_PROVEN"],
            explainability=_simple_reason(
                "multiple committed candidates without an explicit "
                "publication pin; local-latest is never financial authority"
            ),
        )
    except PublicationSelectionPitError as exc:
        raise FinancialsCapabilityError(
            "Q1 PIT selection is unsupported for this dataset"
        ) from exc
    except PublicationSelectionError as exc:
        raise FinancialsCapabilityError("Q1 selection contract failed") from exc

    selected_ids = selection.selected_publication_ids
    if len(selected_ids) != 1:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["FINANCIAL_REVISION_SELECTION_NOT_PROVEN"],
            explainability=_simple_reason(
                "exactly one committed candidate is required"
            ),
        )
    selected_id = selected_ids[0]
    refs.append(SELECTION_AUTHORITY_REF)

    publication = next(
        (p for p in candidates if p.publication_id == selected_id),
        None,
    )
    if publication is None:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["SELECTED_PUBLICATION_MISSING"],
            explainability=_simple_reason(
                "selected publication is missing from candidate set"
            ),
        )
    if (
        publication.dataset_contract_revision
        != shadow.DATASET_CONTRACT_REVISION
        or publication.normalizer_version != shadow.NORMALIZER_VERSION
    ):
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["PUBLICATION_CONTRACT_DRIFT"],
            explainability=_simple_reason(
                "publication dataset contract or normalizer version drifted"
            ),
        )
    refs.append(
        f"publication:{selected_id}:vintage:{publication.vintage_sequence}"
    )
    source_observation_id = publication.source_observation_id

    # FETCH receipt visibility gate（fetched_at <= as_of；非 PIT 声明）
    stored = lake.get_observation(source_observation_id)
    if stored is None:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["SOURCE_OBSERVATION_MISSING"],
            explainability=_simple_reason(
                "selected publication source observation is absent"
            ),
        )
    observation = stored.observation
    fetched_at = observation.fetched_at
    try:
        receipt_visible = _parse_utc_instant(fetched_at) <= _parse_utc_instant(
            as_of
        )
    except FinancialsCapabilityError:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["OBSERVATION_FETCHED_AT_CORRUPTED"],
            explainability=_simple_reason(
                "observation fetched_at is not a valid UTC timestamp"
            ),
        )
    if not receipt_visible:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["FETCH_RECEIPT_NOT_VISIBLE"],
            explainability=_simple_reason(
                "observation fetched_at is after as_of; future fetch is not "
                "as-of-visible evidence"
            ),
        )
    refs.append(f"observation:{source_observation_id}")

    # Replay（MATCH 才继续；mismatch/corruption → ERROR；unsupported → NOT_EVALUATED）
    try:
        replay = shadow.verify_financial_normalization_replay(
            lake, source_observation_id
        )
    except shadow.FinancialReplayUnsupportedError:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["REPLAY_UNSUPPORTED"],
            explainability=_simple_reason(
                "financial replay semantics are unsupported"
            ),
        )
    except shadow.FinancialReplayMismatchError:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["REPLAY_MISMATCH"],
            explainability=_simple_reason(
                "financial normalization replay disagrees with evidence"
            ),
        )
    except shadow.FinancialReplayError:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["REPLAY_CORRUPTED"],
            explainability=_simple_reason(
                "financial replay evidence is corrupted"
            ),
        )
    if replay.status != "MATCH":
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["REPLAY_NORMALIZATION_ABSENT"],
            explainability=_simple_reason(
                "stored normalization is absent; replay cannot be verified"
            ),
        )
    refs.append(REPLAY_AUTHORITY_REF)

    # H2 collect + H1 assess（canonical_admissibility == USABLE 才继续）
    try:
        evidence = collect_fact_lake_health_evidence(
            lake=lake,
            dataset_spec=shadow.FINANCIAL_DATASET_SPEC,
            request=HealthCollectionRequest(
                publication_id=selected_id,
                expected_primary_temporal_value=period,
            ),
        )
    except HealthEvidenceCollectionError:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["HEALTH_EVIDENCE_UNAVAILABLE"],
            explainability=_simple_reason(
                "fact lake health evidence collection failed"
            ),
        )
    refs.append(HEALTH_COLLECTION_AUTHORITY_REF)
    # H2 v0.1 无跨数据集通用 replay 公共权威（replay_state=NOT_RUN）；
    # 本 adapter 已用 dataset-specific replay authority 独立验证 MATCH，
    # 显式把 replay 维度回填为 MATCH 后再交给 H1 评估（与 #116 一致）。
    assessment = assess_publication_health(
        dataset_spec=shadow.FINANCIAL_DATASET_SPEC,
        evidence=replace(evidence, replay_state="MATCH"),
    )
    admissibility = assessment.canonical_admissibility
    if admissibility == "USABLE":
        refs.append(HEALTH_AUTHORITY_REF)
    elif admissibility == "BLOCKED":
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["HEALTH_BLOCKED"],
            explainability=_simple_reason(
                "canonical admissibility is BLOCKED"
            ),
        )
    else:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["HEALTH_INSUFFICIENT_PROOF"],
            explainability=_simple_reason(
                "canonical admissibility is not USABLE (warning/insufficient)"
            ),
        )

    # Exact publication query（selection="publication"，绝不带 as_of）
    queried = shadow.query_financial_indicators(
        lake,
        alias,
        period,
        selection="publication",
        publication_id=selected_id,
        as_of=None,
    )
    if not queried:
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["PUBLICATION_QUERY_EMPTY"],
            explainability=_simple_reason(
                "exact publication query returned no result"
            ),
        )
    if len(queried) != 1:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["PUBLICATION_QUERY_AMBIGUOUS"],
            explainability=_simple_reason(
                "exact publication query returned multiple results"
            ),
        )
    payload = queried[0]

    # Payload 契约验证（identity / versions / metric presence）
    if payload.get("dataset_id") != shadow.DATASET_ID:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["DATASET_ID_MISMATCH"],
            explainability=_simple_reason("canonical dataset id drifted"),
        )
    refs.append(DATASET_AUTHORITY_REF)
    if (
        payload.get("ts_code") != alias
        or payload.get("canonical_payload", {}).get("ts_code") != alias
    ):
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["TS_CODE_MISMATCH"],
            explainability=_simple_reason("canonical ts_code drifted"),
        )
    if (
        payload.get("report_period") != period
        or payload.get("canonical_payload", {}).get("report_period") != period
    ):
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["REPORT_PERIOD_MISMATCH"],
            explainability=_simple_reason("canonical report_period drifted"),
        )
    if (
        payload.get("publication_id") != selected_id
        or payload.get("source_observation_id") != source_observation_id
    ):
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["PUBLICATION_IDENTITY_MISMATCH"],
            explainability=_simple_reason(
                "publication or source observation identity drifted"
            ),
        )
    if (
        payload.get("normalizer_version") != shadow.NORMALIZER_VERSION
        or payload.get("dataset_contract_revision")
        != shadow.DATASET_CONTRACT_REVISION
        or payload.get("revision_semantics") != "restatable"
    ):
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["PUBLICATION_VERSION_CONTRACT_DRIFT"],
            explainability=_simple_reason(
                "normalizer / contract revision / revision semantics drifted"
            ),
        )
    refs.extend([NORMALIZER_AUTHORITY_REF, ARTIFACT_AUTHORITY_REF])

    canonical_payload = payload["canonical_payload"]
    if not isinstance(canonical_payload, Mapping):
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["CANONICAL_PAYLOAD_INVALID"],
            explainability=_simple_reason("canonical payload is not a mapping"),
        )
    versions = canonical_payload.get("versions")
    if not isinstance(versions, list) or not versions:
        return _result(
            state="ERROR",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["VERSIONS_EMPTY"],
            explainability=_simple_reason(
                "canonical financial payload has no versions"
            ),
        )
    if not _has_finite_metric(canonical_payload):
        return _result(
            state="NOT_EVALUATED",
            security_code=security_code,
            campaign_id=campaign_id,
            as_of=as_of,
            report_period_state="RESOLVED",
            report_period=period,
            refs=refs,
            reason_codes=["FINANCIAL_METRICS_NOT_AVAILABLE"],
            explainability=_simple_reason(
                "no canonical finite metric value in any version; "
                "analytical completeness is not this adapter's authority"
            ),
        )

    return _result(
        state="USABLE",
        security_code=security_code,
        campaign_id=campaign_id,
        as_of=as_of,
        report_period_state="RESOLVED",
        report_period=period,
        refs=_dedup(refs),
        reason_codes=[],
        publication_id=selected_id,
        source_observation_id=source_observation_id,
        explainability={
            "what": (
                f"canonical financial publication {selected_id} for "
                f"{alias} report_period {period} is usable evidence"
            ),
            "basis": "explicit report period + canonical publication + "
            "receipt visibility + replay MATCH + health USABLE",
            "selection_mode": mode.value,
        },
    )


def to_ccd_dependency_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """转换为 CCD1 接受的 dependency result（精确四字段 shape）。"""
    return {
        "dependency_id": result["dependency_id"],
        "state": result["state"],
        "as_of": result["as_of"],
        "authority_refs": list(result["authority_refs"]),
    }


__all__ = [
    "ADAPTER_POLICY_VERSION",
    "DEPENDENCY_ID",
    "FinancialsCapabilityError",
    "evaluate_financials_capability",
    "to_ccd_dependency_result",
]
