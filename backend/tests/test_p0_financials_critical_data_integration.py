"""P0-CDA1B — financials capability → CCD1 integration smoke.

证明 MEDIUM strategy 下 DDA1 required set 中的
``cap.security.financials`` 可以由 adapter 评估并直接喂给 CCD1。
只读、临时 lake、无 provider 调用。
"""

from __future__ import annotations

import critical_data_financials_adapter as adapter
from campaign_critical_data_projection import project_campaign_critical_data
from critical_data_dependency_policy import (
    CAP_SECURITY_DISCLOSURES,
    CAP_SECURITY_FINANCIALS,
    POLICY_AUTHORITY_REF_V01,
    POLICY_VERSION_V01,
    resolve_strategy_dependencies,
)
from fact_lake_store import initialize_fact_lake, open_existing_fact_lake
from security_exchange_policy import POLICY_VERSION_V01 as SER_POLICY_VERSION
from tests.test_critical_data_financials_adapter import (
    AS_OF,
    CAMPAIGN,
    PERIOD,
    SECURITY,
    UPSTREAM_REFS,
    _publish,
)


def test_medium_financials_usable_when_evidence_is_healthy(tmp_path):
    lake = initialize_fact_lake(tmp_path / "lake")
    _publish(lake)
    readonly = open_existing_fact_lake(lake.root, readonly=True)

    definition = resolve_strategy_dependencies(
        security_code=SECURITY,
        strategy="MEDIUM",
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        policy_version=POLICY_VERSION_V01,
    )
    assert definition["dependency_set_state"] == "RESOLVED"
    assert CAP_SECURITY_FINANCIALS in definition["required_dependency_ids"]

    results = []
    for dependency_id in definition["required_dependency_ids"]:
        if dependency_id == CAP_SECURITY_FINANCIALS:
            result = adapter.evaluate_financials_capability(
                lake=readonly,
                security_code=SECURITY,
                campaign_id=CAMPAIGN,
                as_of=AS_OF,
                report_period_state="RESOLVED",
                report_period=PERIOD,
                report_period_authority_refs=UPSTREAM_REFS,
                security_exchange_policy_version=SER_POLICY_VERSION,
                adapter_policy_version=adapter.ADAPTER_POLICY_VERSION,
            )
            assert result["state"] == "USABLE"
            results.append(adapter.to_ccd_dependency_result(result))
        else:
            # price_reference / disclosures 无本 slice adapter → 显式 NOT_EVALUATED
            results.append(
                {
                    "dependency_id": dependency_id,
                    "state": "NOT_EVALUATED",
                    "as_of": AS_OF,
                    "authority_refs": [],
                }
            )

    projected = project_campaign_critical_data(
        security_code=SECURITY,
        strategy="MEDIUM",
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        dependency_set_state=definition["dependency_set_state"],
        dependency_set_authority_refs=definition[
            "dependency_set_authority_refs"
        ],
        required_dependency_ids=definition["required_dependency_ids"],
        dependency_results=results,
    )
    # financials USABLE 但 disclosures NOT_EVALUATED → 整体诚实 UNKNOWN
    assert projected["critical_data_state"] == "UNKNOWN"
    assert projected["critical_data_evaluation"] == "NOT_EVALUATED"
    assert POLICY_AUTHORITY_REF_V01 in projected["authority_refs"]
