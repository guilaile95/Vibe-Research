"""P0-CDA1A integration: DDA1 -> real price adapter -> CCD1.

The fixture publishes one synthetic-but-contract-valid ``ds_tushare_daily``
observation through the real Fact Lake path.  The capability result itself is
therefore produced by CDA1A; it is not hand-written as ``USABLE``.
"""

from __future__ import annotations

import json

from campaign_critical_data_projection import project_campaign_critical_data
from critical_data_dependency_policy import (
    POLICY_VERSION_V01 as DDA_POLICY_VERSION,
    resolve_strategy_dependencies,
)
from critical_data_price_reference_adapter import (
    evaluate_price_reference_capability,
)
from fact_lake_store import (
    initialize_fact_lake,
    open_existing_fact_lake,
    payload_sha256,
)
from security_exchange_policy import POLICY_VERSION_V01 as SER_POLICY_VERSION
from tushare_daily_shadow import (
    DAILY_FIELD_MANIFEST,
    TushareDailyRawResponseCapture,
    TushareDailyRequestContract,
    build_provider_observation,
    build_request_fingerprint,
    build_tushare_daily_canonical_fact,
    persist_tushare_daily_evidence,
    publish_tushare_daily_canonical_fact,
)


SECURITY_CODE = "600519"
TRADE_DATE = "2026-07-30"
AS_OF = "2026-07-30T08:30:00Z"  # 16:30 Asia/Shanghai: session completed.
CAMPAIGN_A = "campaign_" + "a" * 32
CAMPAIGN_B = "campaign_" + "b" * 32


def _raw_daily_payload() -> bytes:
    values = {
        "ts_code": "600519.SH",
        "trade_date": "20260730",
        "open": 1780.0,
        "high": 1810.0,
        "low": 1775.0,
        "close": 1800.0,
        "pre_close": 1773.4,
        "change": 26.6,
        "pct_chg": 1.5,
        "vol": 35000.0,
        "amount": 6280000.0,
    }
    return json.dumps(
        {
            "code": 0,
            "msg": "synthetic",
            "data": {
                "fields": list(DAILY_FIELD_MANIFEST),
                "items": [[values[field] for field in DAILY_FIELD_MANIFEST]],
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _published_readonly_lake(tmp_path):
    root = tmp_path / "fact-lake"
    writable = initialize_fact_lake(root)
    raw = _raw_daily_payload()
    contract = TushareDailyRequestContract(TRADE_DATE)
    capture = TushareDailyRawResponseCapture(
        capture_event_id="capture-" + "1" * 32,
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at="2026-07-30T08:00:00.000000Z",
    )
    observation, normalization = persist_tushare_daily_evidence(
        writable,
        capture,
    )
    # The helper is deliberately unused as a shortcut: asserting the candidate
    # identity before admission makes the fixture's route explicit.
    assert build_provider_observation(capture) == observation.observation
    fact = build_tushare_daily_canonical_fact(
        observation.observation,
        normalization,
    )
    publication = publish_tushare_daily_canonical_fact(writable, fact)
    return open_existing_fact_lake(root, readonly=True), publication.publication_id


def _definition(*, strategy: str, campaign_id: str):
    return resolve_strategy_dependencies(
        security_code=SECURITY_CODE,
        strategy=strategy,
        campaign_id=campaign_id,
        as_of=AS_OF,
        policy_version=DDA_POLICY_VERSION,
    )


def _price_result(lake, *, campaign_id: str, publication_id: str):
    return evaluate_price_reference_capability(
        lake=lake,
        security_code=SECURITY_CODE,
        campaign_id=campaign_id,
        as_of=AS_OF,
        security_exchange_policy_version=SER_POLICY_VERSION,
        publication_id=publication_id,
    )


def _project(definition, *, price_result):
    results = []
    for dependency_id in definition["required_dependency_ids"]:
        if dependency_id == "cap.security.price_reference":
            results.append(price_result)
        else:
            results.append(
                {
                    "dependency_id": dependency_id,
                    "state": "NOT_EVALUATED",
                    "as_of": AS_OF,
                    "authority_refs": [],
                }
            )
    return project_campaign_critical_data(
        security_code=definition["security_code"],
        strategy=definition["strategy"],
        campaign_id=definition["campaign_id"],
        as_of=definition["as_of"],
        dependency_set_state=definition["dependency_set_state"],
        dependency_set_authority_refs=(
            definition["dependency_set_authority_refs"]
        ),
        required_dependency_ids=definition["required_dependency_ids"],
        dependency_results=results,
    )


def test_swing_real_price_usable_does_not_create_false_campaign_clean(tmp_path):
    lake, publication_id = _published_readonly_lake(tmp_path)
    definition = _definition(strategy="SWING", campaign_id=CAMPAIGN_A)
    price = _price_result(
        lake,
        campaign_id=CAMPAIGN_A,
        publication_id=publication_id,
    )
    critical = _project(definition, price_result=price)

    assert price["state"] == "USABLE"
    assert definition["required_dependency_ids"] == [
        "cap.security.price_reference",
        "cap.context.market_sector",
        "cap.security.disclosures",
    ]
    assert [item["state"] for item in critical["dependency_results"]] == [
        "USABLE",
        "NOT_EVALUATED",
        "NOT_EVALUATED",
    ]
    assert critical["critical_data_state"] == "UNKNOWN"
    assert critical["critical_data_evaluation"] == "NOT_EVALUATED"


def test_medium_real_price_usable_is_not_overall_usable(tmp_path):
    lake, publication_id = _published_readonly_lake(tmp_path)
    definition = _definition(strategy="MEDIUM", campaign_id=CAMPAIGN_A)
    price = _price_result(
        lake,
        campaign_id=CAMPAIGN_A,
        publication_id=publication_id,
    )
    critical = _project(definition, price_result=price)

    assert price["state"] == "USABLE"
    assert definition["required_dependency_ids"] == [
        "cap.security.price_reference",
        "cap.security.disclosures",
        "cap.security.financials",
    ]
    assert critical["critical_data_state"] != "USABLE"
    assert critical["critical_data_state"] == "UNKNOWN"
    assert critical["critical_data_evaluation"] == "NOT_EVALUATED"


def test_same_security_multiple_campaigns_keep_evaluation_context_separate(
    tmp_path,
):
    lake, publication_id = _published_readonly_lake(tmp_path)
    definition_a = _definition(strategy="SWING", campaign_id=CAMPAIGN_A)
    definition_b = _definition(strategy="MEDIUM", campaign_id=CAMPAIGN_B)
    price_a = _price_result(
        lake,
        campaign_id=CAMPAIGN_A,
        publication_id=publication_id,
    )
    price_b = _price_result(
        lake,
        campaign_id=CAMPAIGN_B,
        publication_id=publication_id,
    )

    # Both calls may cite the same immutable evidence, but must return detached
    # values and remain bound to their own DDA/CCD campaign context.
    assert price_a == price_b
    assert price_a is not price_b
    assert price_a["authority_refs"] is not price_b["authority_refs"]
    critical_a = _project(definition_a, price_result=price_a)
    critical_b = _project(definition_b, price_result=price_b)
    assert critical_a["campaign_id"] == CAMPAIGN_A
    assert critical_b["campaign_id"] == CAMPAIGN_B
    assert critical_a["strategy"] == "SWING"
    assert critical_b["strategy"] == "MEDIUM"
    assert critical_a["required_dependency_ids"] != (
        critical_b["required_dependency_ids"]
    )
    assert critical_a["critical_data_state"] == "UNKNOWN"
    assert critical_b["critical_data_state"] == "UNKNOWN"
