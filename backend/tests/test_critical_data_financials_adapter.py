"""P0-CDA1B — ``cap.security.financials`` capability adapter tests.

覆盖任务书 §30 的 A–AR 必测项。全部使用临时 Fact Lake + synthetic
financial capture（离线构造 canonical publication），不调用 provider、
不产生真实网络请求、不写真实用户数据。
"""

from __future__ import annotations

import json

import pytest

import critical_data_financials_adapter as adapter
from campaign_critical_data_projection import project_campaign_critical_data
from critical_data_dependency_policy import CAP_SECURITY_FINANCIALS
from fact_lake_health import FactLakeHealthAssessment
from fact_lake_store import (
    initialize_fact_lake,
    open_existing_fact_lake,
    payload_sha256,
)
from financial_indicator_shadow import (
    DATASET_CONTRACT_REVISION,
    DATASET_ID,
    FINANCIAL_FIELD_MANIFEST,
    FinancialRawResponseCapture,
    FinancialReplayError,
    FinancialReplayMismatchError,
    FinancialRequestContract,
    NORMALIZER_VERSION,
    build_financial_canonical_fact,
    build_request_fingerprint,
    persist_financial_evidence,
    publish_financial_canonical_fact,
)
import financial_indicator_shadow as shadow
from security_exchange_policy import POLICY_VERSION_V01 as SER_POLICY_VERSION

_ORIGINAL_QUERY = shadow.query_financial_indicators


AS_OF = "2026-06-01T00:00:00.000000Z"
PERIOD = "2026-03-31"
SECURITY = "600519"
SECURITY_SZ = "000001"
SECURITY_BSE = "837023"
CAMPAIGN = "campaign_" + "a" * 32
UPSTREAM_REFS = ["upstream:report-period-resolver:v0.1"]
TS_CODE = "600519.SH"
TS_CODE_SZ = "000001.SZ"
TS_CODE_BSE = "837023.BJ"


def _row(
    *,
    ts_code: str = TS_CODE,
    ann_date: str = "20260430",
    end_date: str = "20260331",
    update_flag: str = "0",
    eps: object = 2.5,
    **overrides,
) -> list[object]:
    values = {
        "ts_code": ts_code,
        "ann_date": ann_date,
        "end_date": end_date,
        "update_flag": update_flag,
        "eps": eps,
        "dt_eps": 2.3,
        "ocfps": None,
        "grossprofit_margin": 91.2,
        "netprofit_margin": 52.1,
        "roe": 8.4,
        "roa": 6.2,
        "debt_to_assets": 19.5,
        "current_ratio": 3.1,
        "assets_turn": 0.13,
        "inv_turn": 0.42,
    }
    values.update(overrides)
    return [values[field] for field in FINANCIAL_FIELD_MANIFEST]


def _raw(
    rows: list[list[object]] | None = None,
    *,
    fields: tuple[str, ...] = FINANCIAL_FIELD_MANIFEST,
) -> bytes:
    return json.dumps(
        {
            "code": 0,
            "msg": "synthetic",
            "data": {
                "fields": list(fields),
                "items": [_row()] if rows is None else rows,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _capture(
    raw: bytes,
    *,
    ts_code: str = TS_CODE,
    report_period: str = PERIOD,
    event: int = 1,
    fetched_at: str = "2026-05-01T08:00:00.000000Z",
) -> FinancialRawResponseCapture:
    contract = FinancialRequestContract(ts_code, report_period)
    return FinancialRawResponseCapture(
        capture_event_id=f"capture-{event:032x}",
        contract=contract,
        raw_bytes=raw,
        request_fingerprint=build_request_fingerprint(contract),
        source_payload_hash=payload_sha256(raw),
        http_status=200,
        content_type="application/json; charset=utf-8",
        fetched_at=fetched_at,
    )


def _publish(
    lake,
    *,
    ts_code: str = TS_CODE,
    report_period: str = PERIOD,
    event: int = 1,
    fetched_at: str = "2026-05-01T08:00:00.000000Z",
    rows: list[list[object]] | None = None,
):
    raw = _raw(rows if rows is not None else [_row(ts_code=ts_code)])
    observation, normalization = persist_financial_evidence(
        lake,
        _capture(
            raw,
            ts_code=ts_code,
            report_period=report_period,
            event=event,
            fetched_at=fetched_at,
        ),
    )
    fact = build_financial_canonical_fact(
        observation.observation, normalization
    )
    publication = publish_financial_canonical_fact(lake, fact)
    return publication


@pytest.fixture
def lake(tmp_path):
    return initialize_fact_lake(tmp_path / "lake")


def _evaluate(lake, **overrides) -> dict:
    kwargs = {
        "lake": lake,
        "security_code": SECURITY,
        "campaign_id": CAMPAIGN,
        "as_of": AS_OF,
        "report_period_state": "RESOLVED",
        "report_period": PERIOD,
        "report_period_authority_refs": UPSTREAM_REFS,
        "security_exchange_policy_version": SER_POLICY_VERSION,
        "adapter_policy_version": adapter.ADAPTER_POLICY_VERSION,
    }
    kwargs.update(overrides)
    return adapter.evaluate_financials_capability(**kwargs)


def _readonly(lake):
    return open_existing_fact_lake(lake.root, readonly=True)


class TestUsablePath:
    def test_a_sse_resolved_healthy_publication_usable(self, lake):
        _publish(lake)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "USABLE"
        assert result["dependency_id"] == CAP_SECURITY_FINANCIALS
        assert result["publication_id"]
        assert result["source_observation_id"]
        assert result["reason_codes"] == []
        assert result["as_of"] == AS_OF

    def test_b_szse_equivalent_usable(self, lake):
        _publish(lake, ts_code=TS_CODE_SZ)
        result = _evaluate(
            _readonly(lake), security_code=SECURITY_SZ
        )
        assert result["state"] == "USABLE"
        assert result["publication_id"]

    def test_k_one_publication_is_eligible(self, lake):
        publication = _publish(lake)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "USABLE"
        assert result["publication_id"] == publication.publication_id

    def test_q_receipt_before_as_of_eligible(self, lake):
        _publish(lake, fetched_at="2026-01-01T00:00:00.000000Z")
        assert _evaluate(_readonly(lake))["state"] == "USABLE"

    def test_s_replay_match_is_eligible(self, lake):
        _publish(lake)
        assert _evaluate(_readonly(lake))["state"] == "USABLE"

    def test_v_health_usable_is_eligible(self, lake):
        _publish(lake)
        assert _evaluate(_readonly(lake))["state"] == "USABLE"

    def test_ae_at_least_one_finite_metric_is_eligible(self, lake):
        _publish(lake)
        assert _evaluate(_readonly(lake))["state"] == "USABLE"

    def test_af_multiple_versions_inside_publication_no_winner(self, lake):
        rows = [
            _row(ann_date="20260430", update_flag="0", eps=2.5),
            _row(ann_date="20260510", update_flag="1", eps=2.6),
        ]
        _publish(lake, rows=rows)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "USABLE"

    def test_ag_no_update_flag_winner_inference(self, lake):
        rows = [
            _row(update_flag="0", eps=2.5),
            _row(update_flag="1", eps=2.7),
        ]
        _publish(lake, rows=rows)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "USABLE"

    def test_ah_no_ann_date_winner_inference(self, lake):
        rows = [
            _row(ann_date="20260430", eps=2.5),
            _row(ann_date="20260520", eps=2.8),
        ]
        _publish(lake, rows=rows)
        assert _evaluate(_readonly(lake))["state"] == "USABLE"

    def test_m_multiple_publications_with_exact_pin_selects_only_that(
        self, lake
    ):
        first = _publish(lake, event=1, rows=[_row(eps=2.5)])
        _publish(lake, event=2, rows=[_row(eps=2.6)])
        result = _evaluate(
            _readonly(lake), publication_id=first.publication_id
        )
        assert result["state"] == "USABLE"
        assert result["publication_id"] == first.publication_id


class TestNotEvaluated:
    def test_c_bse_provider_alias_not_proven(self, lake):
        _publish(lake, ts_code=TS_CODE_BSE)
        result = _evaluate(
            _readonly(lake), security_code=SECURITY_BSE
        )
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == ["BSE_PROVIDER_ALIAS_NOT_PROVEN"]

    def test_d_unknown_ser_policy_not_evaluated(self, lake):
        _publish(lake)
        result = _evaluate(
            _readonly(lake),
            security_exchange_policy_version="security_exchange_policy.v9",
        )
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == [
            "SECURITY_EXCHANGE_POLICY_NOT_AVAILABLE"
        ]

    def test_e_report_period_unknown_maps_unknown(self, lake):
        result = _evaluate(
            _readonly(lake),
            report_period_state="UNKNOWN",
            report_period=None,
            report_period_authority_refs=[],
        )
        assert result["state"] == "UNKNOWN"

    def test_f_report_period_not_evaluated(self, lake):
        result = _evaluate(
            _readonly(lake),
            report_period_state="NOT_EVALUATED",
            report_period=None,
            report_period_authority_refs=[],
        )
        assert result["state"] == "NOT_EVALUATED"

    def test_g_report_period_error_maps_error(self, lake):
        result = _evaluate(
            _readonly(lake),
            report_period_state="ERROR",
            report_period=None,
            report_period_authority_refs=[],
        )
        assert result["state"] == "ERROR"

    def test_h_resolved_without_authority_refs_never_usable(self, lake):
        _publish(lake)
        result = _evaluate(_readonly(lake), report_period_authority_refs=[])
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == ["REPORT_PERIOD_AUTHORITY_NOT_PROVEN"]

    def test_j_zero_publication_not_evaluated(self, lake):
        result = _evaluate(_readonly(lake))
        assert result["state"] == "NOT_EVALUATED"

    def test_l_multiple_publications_without_pin_not_evaluated(self, lake):
        _publish(lake, event=1, rows=[_row(eps=2.5)])
        _publish(lake, event=2, rows=[_row(eps=2.6)])
        result = _evaluate(_readonly(lake))
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == [
            "FINANCIAL_REVISION_SELECTION_NOT_PROVEN"
        ]

    def test_n_bad_publication_pin_no_fallback(self, lake):
        _publish(lake)
        result = _evaluate(
            _readonly(lake),
            publication_id="publication-does-not-exist",
        )
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == ["PUBLICATION_NOT_FOUND"]

    def test_p_future_fetched_at_not_evaluated(self, lake):
        _publish(lake, fetched_at="2026-07-01T00:00:00.000000Z")
        result = _evaluate(_readonly(lake))
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == ["FETCH_RECEIPT_NOT_VISIBLE"]

    def test_ad_all_metrics_null_not_evaluated(self, lake):
        all_null = {
            "eps": None,
            "dt_eps": None,
            "ocfps": None,
            "grossprofit_margin": None,
            "netprofit_margin": None,
            "roe": None,
            "roa": None,
            "debt_to_assets": None,
            "current_ratio": None,
            "assets_turn": None,
            "inv_turn": None,
        }
        _publish(lake, rows=[_row(**all_null)])
        result = _evaluate(_readonly(lake))
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == ["FINANCIAL_METRICS_NOT_AVAILABLE"]

    def test_aj_unknown_adapter_policy_not_evaluated(self, lake):
        _publish(lake)
        result = _evaluate(
            _readonly(lake),
            adapter_policy_version="critical_data.financials.v9",
        )
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == [
            "ADAPTER_POLICY_VERSION_NOT_AVAILABLE"
        ]

    def test_ak_no_implicit_policy_fallback(self, lake):
        _publish(lake)
        result = _evaluate(
            _readonly(lake),
            adapter_policy_version="critical_data.financials.v9",
        )
        assert adapter.ADAPTER_AUTHORITY_REF not in result["authority_refs"]
        assert result["publication_id"] is None
        assert result["source_observation_id"] is None

    def test_x_health_warning_not_evaluated(self, lake, monkeypatch):
        _publish(lake)
        readonly = _readonly(lake)

        def fake_assess(*, dataset_spec, evidence):
            return FactLakeHealthAssessment(
                dataset_id=DATASET_ID,
                canonical_key="ds_financial_indicator:600519.SH:2026-03-31",
                publication_id="publication-x",
                publication_visibility="COMMITTED",
                storage_integrity="OK",
                reproducibility="OK",
                semantic_quality="OK",
                freshness="UNKNOWN",
                reconciliation="OK",
                canonical_admissibility="USABLE_WITH_WARNING",
                reason_codes=("FRESHNESS_UNKNOWN",),
            )

        monkeypatch.setattr(
            adapter, "assess_publication_health", fake_assess
        )
        result = _evaluate(readonly)
        assert result["state"] == "NOT_EVALUATED"
        assert result["reason_codes"] == ["HEALTH_INSUFFICIENT_PROOF"]


class TestErrorPaths:
    def test_t_replay_mismatch_error(self, lake, monkeypatch):
        _publish(lake)

        def broken(*_args, **_kwargs):
            raise FinancialReplayMismatchError("mismatch")

        monkeypatch.setattr(
            shadow, "verify_financial_normalization_replay", broken
        )
        result = _evaluate(_readonly(lake))
        assert result["state"] == "ERROR"
        assert result["reason_codes"] == ["REPLAY_MISMATCH"]

    def test_u_replay_corrupted_error(self, lake, monkeypatch):
        _publish(lake)

        def broken(*_args, **_kwargs):
            raise FinancialReplayError("corrupted")

        monkeypatch.setattr(
            shadow, "verify_financial_normalization_replay", broken
        )
        result = _evaluate(_readonly(lake))
        assert result["state"] == "ERROR"
        assert result["reason_codes"] == ["REPLAY_CORRUPTED"]

    def test_w_health_blocked_error(self, lake, monkeypatch):
        _publish(lake)

        def fake_assess(*, dataset_spec, evidence):
            return FactLakeHealthAssessment(
                dataset_id=DATASET_ID,
                canonical_key="ds_financial_indicator:600519.SH:2026-03-31",
                publication_id="publication-x",
                publication_visibility="COMMITTED",
                storage_integrity="FAILED",
                reproducibility="OK",
                semantic_quality="OK",
                freshness="UNKNOWN",
                reconciliation="OK",
                canonical_admissibility="BLOCKED",
                reason_codes=("STORAGE_INTEGRITY_FAILED",),
            )

        monkeypatch.setattr(
            adapter, "assess_publication_health", fake_assess
        )
        result = _evaluate(_readonly(lake))
        assert result["state"] == "ERROR"
        assert result["reason_codes"] == ["HEALTH_BLOCKED"]

    @pytest.mark.parametrize(
        "mutation,code",
        [
            ({"dataset_id": "ds_other"}, "DATASET_ID_MISMATCH"),
            ({"ts_code": "000001.SZ"}, "TS_CODE_MISMATCH"),
            ({"report_period": "2025-12-31"}, "REPORT_PERIOD_MISMATCH"),
            (
                {"publication_id": "publication-other"},
                "PUBLICATION_IDENTITY_MISMATCH",
            ),
            (
                {"normalizer_version": "ds-financial-indicator-normalizer-v9"},
                "PUBLICATION_VERSION_CONTRACT_DRIFT",
            ),
        ],
    )
    def test_payload_contract_drift_errors(
        self, lake, monkeypatch, mutation, code
    ):
        publication = _publish(lake)

        def fake_query(*args, **kwargs):
            real = _ORIGINAL_QUERY(*args, **kwargs)
            payload = dict(real[0])
            payload.update(mutation)
            return (payload,)

        monkeypatch.setattr(shadow, "query_financial_indicators", fake_query)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "ERROR"
        assert code in result["reason_codes"]
        assert publication.publication_id

    def test_ac_versions_empty_error(self, lake, monkeypatch):
        _publish(lake)

        def fake_query(*args, **kwargs):
            real = _ORIGINAL_QUERY(*args, **kwargs)
            payload = dict(real[0])
            canonical = dict(payload["canonical_payload"])
            canonical["versions"] = []
            payload["canonical_payload"] = canonical
            return (payload,)

        monkeypatch.setattr(shadow, "query_financial_indicators", fake_query)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "ERROR"
        assert result["reason_codes"] == ["VERSIONS_EMPTY"]


class TestInputFailClosed:
    def test_i_malformed_report_period_raises(self, lake):
        with pytest.raises(adapter.FinancialsCapabilityError):
            _evaluate(_readonly(lake), report_period="2026/03/31")
        with pytest.raises(adapter.FinancialsCapabilityError):
            _evaluate(_readonly(lake), report_period="2026-13-40")
        with pytest.raises(adapter.FinancialsCapabilityError):
            _evaluate(_readonly(lake), report_period="")

    def test_al_writable_lake_rejected(self, lake):
        with pytest.raises(adapter.FinancialsCapabilityError):
            _evaluate(lake)

    def test_unknown_report_period_state_raises(self, lake):
        with pytest.raises(adapter.FinancialsCapabilityError):
            _evaluate(_readonly(lake), report_period_state="MAYBE")


class TestIntegrity:
    def test_o_local_latest_never_used(self, lake, monkeypatch):
        _publish(lake)
        calls = []
        original = shadow.query_financial_indicators

        def spy(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return _ORIGINAL_QUERY(*args, **kwargs)

        monkeypatch.setattr(shadow, "query_financial_indicators", spy)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "USABLE"
        assert calls
        for call in calls:
            assert call["kwargs"]["selection"] == "publication"
            assert call["kwargs"]["as_of"] is None

    def test_r_no_pit_as_of_query(self, lake, monkeypatch):
        _publish(lake)
        calls = []

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return _ORIGINAL_QUERY(*args, **kwargs)

        monkeypatch.setattr(shadow, "query_financial_indicators", spy)
        assert _evaluate(_readonly(lake))["state"] == "USABLE"
        assert calls and all(call["as_of"] is None for call in calls)

    def test_am_no_provider_call(self, lake, monkeypatch):
        _publish(lake)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("provider call forbidden")

        monkeypatch.setattr(
            shadow, "run_financial_indicator_shadow", forbidden
        )
        assert _evaluate(_readonly(lake))["state"] == "USABLE"

    def test_an_no_fact_lake_writes(self, lake, monkeypatch):
        _publish(lake)
        readonly = _readonly(lake)
        for method in (
            "store_observation",
            "store_normalization",
            "stage_canonical_publication",
            "commit_canonical_publication",
            "append_reconciliation",
        ):
            monkeypatch.setattr(
                readonly, method, lambda *a, **k: pytest.fail(f"{method} called")
            )
        assert _evaluate(readonly)["state"] == "USABLE"

    def test_ao_ap_aq_deterministic_repeatable_refs(self, lake):
        _publish(lake)
        readonly = _readonly(lake)
        first = _evaluate(readonly)
        second = _evaluate(readonly)
        assert first == second
        assert first["authority_refs"] == second["authority_refs"]
        assert adapter.ADAPTER_AUTHORITY_REF in first["authority_refs"]
        refs = first["authority_refs"]
        assert refs[0] == adapter.ADAPTER_AUTHORITY_REF
        assert all(ref in refs for ref in UPSTREAM_REFS)
        assert UPSTREAM_REFS == refs[1 : 1 + len(UPSTREAM_REFS)]
        assert (
            "security_exchange_policy:v0.1" in first["authority_refs"]
        )
        assert adapter.SELECTION_AUTHORITY_REF in first["authority_refs"]
        assert adapter.DATASET_AUTHORITY_REF in first["authority_refs"]
        assert adapter.NORMALIZER_AUTHORITY_REF in first["authority_refs"]
        assert adapter.HEALTH_COLLECTION_AUTHORITY_REF in first["authority_refs"]
        assert adapter.HEALTH_AUTHORITY_REF in first["authority_refs"]
        assert adapter.REPLAY_AUTHORITY_REF in first["authority_refs"]

    def test_ar_ccd_shape_compatibility(self, lake):
        _publish(lake)
        result = _evaluate(_readonly(lake))
        assert result["state"] == "USABLE"
        ccd_result = adapter.to_ccd_dependency_result(result)
        projected = project_campaign_critical_data(
            security_code=SECURITY,
            strategy="MEDIUM",
            campaign_id=CAMPAIGN,
            as_of=AS_OF,
            dependency_set_state="RESOLVED",
            dependency_set_authority_refs=[
                "dda:strategy_dependency_policy:v0.1"
            ],
            required_dependency_ids=[CAP_SECURITY_FINANCIALS],
            dependency_results=[ccd_result],
        )
        assert projected["critical_data_state"] == "USABLE"
        assert projected["critical_data_evaluation"] == "EVALUATED"
