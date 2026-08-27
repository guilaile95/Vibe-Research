"""TR1-P2 单证券 Attention Context 离线契约测试。

所有 TrendRadar 与股票元数据均使用 fake，零真实出网、零真实用户数据、零写入。
"""

from __future__ import annotations

import astock
import pytest
import requests

import trendradar_attention_context as attention
import trendradar_gateway as gateway


ENV_ENABLED = {gateway.MCP_URL_ENV: "http://127.0.0.1:3777/mcp"}


def _metadata(_code: str):
    return {
        "mapping_status": "MAPPED",
        "code": "000001",
        "company_name": "平安银行",
        "sector": {"value": "银行", "source": "fixture"},
        "topics": [
            {"term": "数字金融", "source": "fixture"},
            {"term": "银行", "source": "fixture"},
        ],
        "matched_terms": ["平安银行", "银行", "数字金融"],
        "mapping_reasons": [
            {"kind": "security_code", "value": "000001", "source": "fixture"},
            {"kind": "company_name", "value": "平安银行", "source": "fixture"},
            {"kind": "sector", "value": "银行", "source": "fixture"},
        ],
        "mapping_errors": [],
    }


def _factory(_config):
    class FakeTransport:
        def server_info(self):
            return dict(gateway.EXPECTED_SERVER_NAME and {
                "server_name": gateway.EXPECTED_SERVER_NAME,
                "server_version": gateway.EXPECTED_SERVER_VERSION,
                "protocol_version": gateway.EXPECTED_PROTOCOL_VERSION,
            })

        def list_tools(self):
            return [gateway.ToolDescriptor(name="search_news", description="search", input_schema={})]

        def call_tool(self, name, arguments):
            term = arguments["query"]
            return gateway.RawToolResult(
                is_error=False,
                payload_text=(
                    '[{"title":"%s 相关新闻","platform":"微博","rank":3,'
                    '"timestamp":"2026-08-27 09:00:00","first_crawl_time":"2026-08-27 08:00:00",'
                    '"last_crawl_time":"2026-08-27 09:00:00","crawl_count":2}]' % term
                ),
                structured_content=None,
            )

    return FakeTransport()


def test_disabled_is_explicit_and_does_not_load_metadata():
    called = False

    def loader(_code):
        nonlocal called
        called = True
        raise AssertionError("disabled context must not load metadata")

    result = attention.build_attention_context(
        "000001", env={}, metadata_loader=loader
    )
    assert result["status"] == gateway.STATUS_DISABLED
    assert result["security"] == {"code": "000001", "company_name": None}
    assert result["observation"]["items"] == []
    assert result["source_statuses"][0]["status"] == gateway.STATUS_DISABLED
    assert called is False


def test_text_only_search_results_are_normalized_with_provenance():
    result = attention.build_attention_context(
        "000001",
        env=ENV_ENABLED,
        transport_factory=_factory,
        metadata_loader=_metadata,
    )
    assert result["status"] == "OK"
    assert result["security"] == {"code": "000001", "company_name": "平安银行"}
    assert result["mapping"]["sector"]["value"] == "银行"
    assert result["mapping"]["matched_terms"] == ["平安银行", "银行", "数字金融"]
    assert result["observation"]["item_count"] == 3
    assert result["observation"]["items"][0]["title"] == "平安银行 相关新闻"
    assert result["observation"]["items"][0]["matched_terms"] == ["平安银行"]
    assert result["authority_ref"] == attention.ATTENTION_CONTEXT_AUTHORITY_REF
    assert result["usage_boundary"] == attention.USAGE_BOUNDARY
    assert "investment_score" not in str(result).lower()
    assert "buy_sell" not in str(result).lower()


def test_metadata_failure_keeps_exact_code_mapping_and_reports_error():
    def broken_loader(_code):
        return {
            "mapping_status": "EXACT_CODE_ONLY",
            "code": "000001",
            "company_name": None,
            "sector": None,
            "topics": [],
            "matched_terms": ["000001"],
            "mapping_reasons": [{"kind": "security_code", "value": "000001", "source": "fixture"}],
            "mapping_errors": [{"source": "fixture", "error": "metadata unavailable"}],
        }

    result = attention.build_attention_context(
        "000001", env=ENV_ENABLED, transport_factory=_factory, metadata_loader=broken_loader
    )
    assert result["mapping"]["status"] == "EXACT_CODE_ONLY"
    assert result["mapping"]["matched_terms"] == ["000001"]
    assert result["mapping"]["errors"][0]["source"] == "fixture"


def test_metadata_loader_exception_falls_back_without_leaking_detail():
    def broken_loader(_code):
        raise RuntimeError("ProxyError https://secret.example/api?token=abc")

    result = attention.build_attention_context(
        "000001", env=ENV_ENABLED, transport_factory=_factory, metadata_loader=broken_loader
    )
    assert result["mapping"]["status"] == "EXACT_CODE_ONLY"
    assert result["mapping"]["matched_terms"] == ["000001"]
    assert result["mapping"]["errors"] == [
        {"source": "metadata_loader", "error": "数据源暂不可用"}
    ]
    assert "ProxyError" not in str(result)
    assert "secret.example" not in str(result)


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"f12": "000001"},
        {"f12": "000001", "f14": "平安银行", "f3": {"bad": "type"}},
        {"f12": "000001", "f14": "平安银行", "f128": 123},
        {"f12": "000001", "f14": "平安银行", "f3": "NaN"},
        {"f12": "000001", "f14": "平安银行", "f3": "Infinity"},
        {"f12": "000001", "f14": "平安银行", "f3": float("nan")},
    ],
)
def test_concept_blocks_strict_rejects_malformed_rows(monkeypatch, row):
    class BadResponse:
        def json(self):
            return {"data": {"diff": [row]}}

    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: BadResponse())
    with pytest.raises(ValueError):
        astock.concept_blocks("000001", strict=True)


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"conceptId": "C1", "hitCount": 1},
        {"conceptName": "人工智能", "conceptId": "C1", "hitCount": "not-a-number"},
        {"conceptName": "人工智能", "conceptId": {"bad": "type"}, "hitCount": 1},
        {"conceptName": "人工智能", "conceptId": "C1", "hitCount": "Infinity"},
        {"conceptName": "人工智能", "conceptId": "C1", "hitCount": float("nan")},
    ],
)
def test_hot_concepts_strict_rejects_malformed_rows(monkeypatch, row):
    class BadResponse:
        def json(self):
            return {"data": [row]}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: BadResponse())
    with pytest.raises(ValueError):
        astock.hot_concepts("000001", strict=True)


def test_strict_concept_and_hot_concept_accept_valid_rows(monkeypatch):
    class ConceptResponse:
        def json(self):
            return {
                "data": {
                    "diff": [
                        {"f12": "BK001", "f14": "人工智能", "f3": "1.25", "f128": "示例股"}
                    ]
                }
            }

    class HotResponse:
        def json(self):
            return {"data": [{"conceptName": "人工智能", "conceptId": "C1", "hitCount": "2"}]}

    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: ConceptResponse())
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: HotResponse())

    assert astock.concept_blocks("000001", strict=True) == {
        "total": 1,
        "boards": [{"name": "人工智能", "code": "BK001", "change_pct": "1.25", "lead_stock": "示例股"}],
        "concept_tags": ["人工智能"],
    }
    assert astock.hot_concepts("000001", strict=True) == [
        {"concept": "人工智能", "bk": "C1", "hit": "2"}
    ]


def test_strict_false_preserves_empty_fallback_for_malformed_sources(monkeypatch):
    class BadResponse:
        def json(self):
            return {"data": {"diff": [{}]}}

    monkeypatch.setattr(astock, "em_get", lambda *args, **kwargs: BadResponse())
    assert astock.concept_blocks("000001") == {"total": 1, "boards": [{"name": "", "code": "", "change_pct": "", "lead_stock": ""}], "concept_tags": [""]}

    class BadHotResponse:
        def json(self):
            return {"data": None}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: BadHotResponse())
    assert astock.hot_concepts("000001") == []


def test_entity_mapping_reports_malformed_strict_topic_source_failures(monkeypatch):
    monkeypatch.setattr(
        attention.astock,
        "tencent_quote",
        lambda _codes: {"000001": {"name": "平安银行"}},
    )
    monkeypatch.setattr(
        attention.astock,
        "individual_info",
        lambda _code: {"行业": "银行"},
    )

    class BadResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    monkeypatch.setattr(
        attention.astock,
        "em_get",
        lambda *args, **kwargs: BadResponse({"data": {"error": "bad"}}),
    )

    import requests

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: BadResponse({"data": "not-a-list"}),
    )

    mapping = attention._entity_mapping("000001")
    assert mapping["topics"] == []
    assert {item["source"] for item in mapping["mapping_errors"]} == {
        "astock.concept_blocks",
        "astock.hot_concepts",
    }
    assert all(item["error"] == "数据源暂不可用" for item in mapping["mapping_errors"])


def test_entity_mapping_reports_malformed_strict_rows(monkeypatch):
    monkeypatch.setattr(
        attention.astock,
        "tencent_quote",
        lambda _codes: {"000001": {"name": "平安银行"}},
    )
    monkeypatch.setattr(
        attention.astock,
        "individual_info",
        lambda _code: {"行业": "银行"},
    )

    class BadResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    monkeypatch.setattr(
        attention.astock,
        "em_get",
        lambda *args, **kwargs: BadResponse({"data": {"diff": [{}]}}),
    )

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: BadResponse({"data": [{"conceptId": "C1"}]}),
    )

    mapping = attention._entity_mapping("000001")
    assert mapping["topics"] == []
    assert {item["source"] for item in mapping["mapping_errors"]} == {
        "astock.concept_blocks",
        "astock.hot_concepts",
    }
    assert all(item["error"] == "数据源暂不可用" for item in mapping["mapping_errors"])
    assert "ProxyError" not in str(mapping)


def test_entity_mapping_reports_strict_topic_source_failures(monkeypatch):
    monkeypatch.setattr(
        attention.astock,
        "tencent_quote",
        lambda _codes: {"000001": {"name": "平安银行"}},
    )
    monkeypatch.setattr(
        attention.astock,
        "individual_info",
        lambda _code: {"行业": "银行"},
    )

    def broken_blocks(_code, *, strict=False):
        assert strict is True
        raise RuntimeError("ProxyError https://secret.example/blocks")

    def broken_hot(_code, *, strict=False):
        assert strict is True
        raise RuntimeError("connection to https://secret.example/hot failed")

    monkeypatch.setattr(attention.astock, "concept_blocks", broken_blocks)
    monkeypatch.setattr(attention.astock, "hot_concepts", broken_hot)

    mapping = attention._entity_mapping("000001")
    assert mapping["mapping_status"] == "MAPPED"
    assert mapping["topics"] == []
    assert mapping["matched_terms"] == ["平安银行", "银行"]
    assert {item["source"] for item in mapping["mapping_errors"]} == {
        "astock.concept_blocks",
        "astock.hot_concepts",
    }
    assert all(item["error"] == "数据源暂不可用" for item in mapping["mapping_errors"])
    assert "ProxyError" not in str(mapping)
    assert "secret.example" not in str(mapping)


def test_partial_failure_is_not_fabricated_as_empty_success():
    calls = []

    def fake_call(name, arguments, env=None, transport_factory=None):
        calls.append((name, arguments))
        if arguments["query"] == "银行":
            return {
                "status": gateway.STATUS_UNAVAILABLE,
                "error": "ProxyError https://secret.example/mcp",
                "upstream": gateway.upstream_identity(),
                "retrieved_at": "2026-08-27T00:00:00Z",
            }
        return {
            "status": gateway.STATUS_OK,
            "upstream": gateway.upstream_identity(),
            "retrieved_at": "2026-08-27T00:00:00Z",
            "result": [{"title": f"{arguments['query']} 观察", "rank": 1}],
        }

    original = attention.console.call_read_tool
    try:
        attention.console.call_read_tool = fake_call  # type: ignore[assignment]
        result = attention.build_attention_context(
            "000001", env=ENV_ENABLED, metadata_loader=_metadata
        )
    finally:
        attention.console.call_read_tool = original  # type: ignore[assignment]

    assert len(calls) == 3
    assert result["status"] == "PARTIAL"
    failed = next(item for item in result["source_statuses"] if item["term"] == "银行")
    assert failed["status"] == gateway.STATUS_UNAVAILABLE
    assert failed["error"] == gateway.safe_public_error(gateway.STATUS_UNAVAILABLE)
    assert "ProxyError" not in str(result)
    assert "secret.example" not in str(result)
    assert result["observation"]["item_count"] == 2


def test_metadata_loader_errors_are_sanitized_at_public_boundary():
    def noisy_loader(_code):
        return {
            **_metadata("000001"),
            "mapping_errors": [
                {"source": "ProxyError https://secret.example/path", "error": "raw detail"},
                {"source": {"not": "text"}, "error": "another detail"},
            ],
        }

    def fake_call(name, arguments, env=None, transport_factory=None):
        return {
            "status": gateway.STATUS_OK,
            "upstream": gateway.upstream_identity(),
            "retrieved_at": "2026-08-27T00:00:00Z",
            "result": [],
        }

    original = attention.console.call_read_tool
    try:
        attention.console.call_read_tool = fake_call  # type: ignore[assignment]
        result = attention.build_attention_context(
            "000001", env=ENV_ENABLED, metadata_loader=noisy_loader
        )
    finally:
        attention.console.call_read_tool = original  # type: ignore[assignment]

    assert result["mapping"]["errors"] == [
        {"source": "metadata_loader", "error": "数据源暂不可用"},
        {"source": "metadata_loader", "error": "数据源暂不可用"},
    ]
    assert "ProxyError" not in str(result)
    assert "secret.example" not in str(result)
    assert "raw detail" not in str(result)


def test_observation_numbers_are_finite_and_timeline_is_whitelisted(monkeypatch):
    def fake_call(name, arguments, env=None, transport_factory=None):
        return {
            "status": gateway.STATUS_OK,
            "upstream": gateway.upstream_identity(),
            "retrieved_at": "2026-08-27T00:00:00Z",
            "result": [
                {
                    "title": "公开观察",
                    "rank": float("nan"),
                    "hotness_score": "1e308",
                    "crawl_count": "1e308",
                    "rank_timeline": [
                        {
                            "crawl_time": "2026-08-27 09:00:00",
                            "rank": 3,
                            "off_list": False,
                            "error": "ProxyError https://secret.example",
                        },
                        {"error": "ProxyError https://secret.example"},
                        {"crawl_time": "2026-08-27 09:30:00", "rank": "NaN"},
                    ],
                }
            ],
        }

    original = attention.console.call_read_tool
    try:
        attention.console.call_read_tool = fake_call  # type: ignore[assignment]
        result = attention.build_attention_context(
            "000001", env=ENV_ENABLED, metadata_loader=_metadata
        )
    finally:
        attention.console.call_read_tool = original  # type: ignore[assignment]

    assert result["status"] == gateway.STATUS_OK
    item = result["observation"]["items"][0]
    assert item["rank"] is None
    assert item["hotness_score"] is None
    assert item["crawl_count"] is None
    assert item["rank_timeline"] == [
        {"crawl_time": "2026-08-27 09:00:00", "rank": 3, "off_list": False}
    ]
    assert "ProxyError" not in str(result)
    assert "secret.example" not in str(result)


def test_unsupported_result_shape_is_contract_mismatch():
    def fake_call(name, arguments, env=None, transport_factory=None):
        return {
            "status": gateway.STATUS_OK,
            "upstream": gateway.upstream_identity(),
            "retrieved_at": "2026-08-27T00:00:00Z",
            "result_text": "not json",
        }

    original = attention.console.call_read_tool
    try:
        attention.console.call_read_tool = fake_call  # type: ignore[assignment]
        result = attention.build_attention_context(
            "000001", env=ENV_ENABLED, metadata_loader=_metadata
        )
    finally:
        attention.console.call_read_tool = original  # type: ignore[assignment]

    assert result["status"] == gateway.STATUS_CONTRACT_MISMATCH
    assert all(item["status"] == gateway.STATUS_CONTRACT_MISMATCH for item in result["source_statuses"])
    assert result["observation"]["items"] == []
