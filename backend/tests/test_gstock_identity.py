"""Exact security identity at the shared API/AI resolver; all replies synthetic."""
import pytest
import gstock


def row(code, market=105, name="Fixture"):
    return {"Code": code, "MktNum": str(market), "Name": name}


@pytest.fixture
def search_reply(monkeypatch):
    calls = []
    def install(rows):
        class Response:
            def json(self):
                return {"QuotationCodeTable": {"Data": rows}}
        def fetch(url, *, params, **kwargs):
            calls.append(params["input"])
            return Response()
        monkeypatch.setattr(gstock.astock, "em_get", fetch)
        return calls
    return install


@pytest.mark.parametrize("query", ["AAP", "gzmt", "不存在"])
def test_nonexact_suggestions_are_not_security_identity(search_reply, query):
    search_reply([row("AAPB"), row("AAPL")])
    assert gstock.resolve_symbol(query) is None


@pytest.mark.parametrize("rows", [[row("AAPB"), row("AAPL")], [row("AAPL"), row("AAPB")]])
def test_exact_code_beats_suggestion_order(search_reply, rows):
    search_reply(rows)
    assert gstock.resolve_symbol(" aapl ")["code"] == "AAPL"


@pytest.mark.parametrize("query", ["700", "0700", "00700"])
def test_hk_zero_padding_does_not_choose_partial_code(search_reply, query):
    search_reply([row("07000",116), row("00700",116), row("000700",177)])
    hit = gstock.resolve_symbol(query)
    assert (hit["code"], hit["market"]) == ("00700", "HK")


@pytest.mark.parametrize("suffix", [".KS", ".KQ", ".KR", ".ks"])
def test_explicit_kr_restricts_market_before_selection(search_reply, suffix):
    search_reply([row("00700",116), row("005930",177)])
    hit = gstock.resolve_symbol("005930" + suffix)
    assert (hit["code"], hit["market"]) == ("005930", "KR")


@pytest.mark.parametrize("query", ["005930.KS", "005930.KQ", "005930.KR", "005930", "600519"])
def test_numeric_or_kr_input_never_falls_back_to_other_security(search_reply, query):
    search_reply([row("00700",116), row("005930",177)])
    if "." in query:
        # Remove the genuine Korean candidate: no match must remain no match.
        search_reply([row("00700",116)])
    assert gstock.resolve_symbol(query) is None


def test_exact_code_precedes_other_security_exact_name(search_reply):
    search_reply([row("BBB",106,"ABC"),row("ABC",105,"Other")])
    assert gstock.resolve_symbol("ABC")["code"] == "ABC"


def test_unique_exact_name_preserved(search_reply):
    search_reply([row("AAA",105,"苹果"),row("BBB",106,"苹果供应商")])
    assert gstock.resolve_symbol("苹果")["code"] == "AAA"


def test_identical_provider_identity_duplicates_collapse(search_reply):
    search_reply([row("ABC",105),row("ABC",105,"Alternate provider label")])
    assert gstock.resolve_symbol("ABC")["secid_prefix"] == 105


@pytest.mark.parametrize("rows,query", [
    ([row("ABC",105),row("ABC",106)],"ABC"),
    ([row("ABC",105),row("ABC",107)],"ABC"),
    ([row("AAA",105,"苹果"),row("BBB",106,"苹果")],"苹果"),
])
def test_distinct_provider_identities_are_ambiguous_not_assumed_aliases(search_reply, rows, query):
    search_reply(rows)
    with pytest.raises(gstock.SearchAmbiguous):
        gstock.resolve_symbol(query)


@pytest.mark.parametrize("bad", [None, [], "row", {}, {"Code":None,"MktNum":105},
    {"Code":123,"MktNum":105}, {"Code":"AAPL","MktNum":True},
    {"Code":"AAPL","MktNum":105.2}, {"Code":"AAPL","MktNum":"105.2"},
    {"Code":"AAPL","MktNum":177}, {"Code":"AAPL","MktNum":116}])
def test_invalid_provider_identity_never_becomes_success(search_reply,bad):
    search_reply([bad])
    with pytest.raises(gstock.SearchUnavailable):
        gstock.resolve_symbol("AAPL")


def test_unrelated_valid_markets_are_not_transport_failures(search_reply):
    search_reply([row("600519",1)])
    assert gstock.resolve_symbol("AAPL") is None


def test_empty_response_stays_no_match(search_reply):
    search_reply([])
    assert gstock.resolve_symbol("AAPL") is None


def test_resolution_rejection_stops_quote_and_financial_calls(search_reply,monkeypatch):
    search_reply([row("AAPB")])
    def forbidden(*args,**kwargs):
        raise AssertionError("Wrong-security downstream request")
    monkeypatch.setattr(gstock,"_push2_stock_get",forbidden)
    monkeypatch.setattr(gstock.astock,"eastmoney_datacenter",forbidden)
    assert gstock.us_hk_stock("AAP") == {}
    assert gstock.hk_cashflow("AAP") == {}


def test_short_hk_empty_query_retries_documented_padded_code(monkeypatch):
    calls = []
    class Response:
        def __init__(self, q): self.q = q
        def json(self): return {"QuotationCodeTable":{"Data": [] if self.q == "700" else [row("00700",116)]}}
    def fetch(url, *, params, **kwargs):
        calls.append(params["input"])
        return Response(params["input"])
    monkeypatch.setattr(gstock.astock,"em_get",fetch)
    assert gstock.resolve_symbol("700")["code"] == "00700"
    assert calls == ["700", "00700"]


def test_malformed_identity_primary_tries_existing_backup(monkeypatch):
    calls = []
    class Response:
        def __init__(self, rows): self.rows=rows
        def json(self): return {"QuotationCodeTable":{"Data":self.rows}}
    def fetch(url, **kwargs):
        calls.append(url)
        return Response([None] if len(calls)==1 else [row("AAPL")])
    monkeypatch.setattr(gstock.astock,"em_get",fetch)
    assert gstock.resolve_symbol("AAPL")["code"] == "AAPL"
    assert calls == list(gstock._SEARCH_ENDPOINTS)


@pytest.mark.parametrize("entry", ["api_stock", "api_cashflow", "ai_stock", "ai_cashflow"])
@pytest.mark.parametrize("scenario,status", [("none",404),("ambiguous",400),("transport",503),("malformed",503)])
def test_public_consumers_never_return_wrong_security_or_provider_details(monkeypatch, entry, scenario, status):
    # API and AI use the actual shared resolver. Fail if it reaches quote/finance.
    import app as app_module
    import ai_tools
    from fastapi.testclient import TestClient
    raw = "ProxyError https://provider.invalid/?token=secret SQL traceback"
    class Response:
        def json(self):
            if scenario == "malformed": return {"QuotationCodeTable":{"Data":[{"Code":None,"MktNum":105}]}}
            rows = [row("AAPB")] if scenario == "none" else [row("ABC",105),row("ABC",106)]
            return {"QuotationCodeTable":{"Data":rows}}
    def fetch(*args,**kwargs):
        if scenario == "transport": raise ConnectionError(raw)
        return Response()
    def forbidden(*args,**kwargs): raise AssertionError("Unexpected downstream provider")
    monkeypatch.setattr(gstock.astock,"em_get",fetch)
    monkeypatch.setattr(gstock,"_push2_stock_get",forbidden)
    monkeypatch.setattr(gstock.astock,"eastmoney_datacenter",forbidden)
    symbol = "AAP" if scenario == "none" else "ABC"
    if entry.startswith("api"):
        route = "/api/global/stock" if entry == "api_stock" else "/api/global/hk/cashflow"
        result = TestClient(app_module.app).get(route,params={"symbol":symbol})
        assert result.status_code == status
        text = result.json()["detail"]
        assert "data" not in result.json()
    else:
        tool = "query_global_stock" if entry == "ai_stock" else "query_hk_cashflow"
        result = ai_tools.exec_tool(tool,{"symbol":symbol})
        assert set(result) == {"error"}
        text = result["error"]
    if scenario == "ambiguous": assert text == gstock.SEARCH_AMBIGUOUS_MESSAGE
    if scenario in ("transport","malformed"): assert text == gstock.SEARCH_UNAVAILABLE_MESSAGE
    for secret in ("ProxyError", "https://", "token=", "secret", "SQL", "traceback"):
        assert secret not in text


@pytest.mark.parametrize("kind", ["ambiguous", "unavailable"])
def test_public_boundaries_sanitize_even_nonstandard_exception_text(monkeypatch,kind):
    import app as app_module
    import ai_tools
    from fastapi.testclient import TestClient
    cls = gstock.SearchAmbiguous if kind == "ambiguous" else gstock.SearchUnavailable
    def fail(*args,**kwargs): raise cls("https://provider.invalid/?token=secret")
    monkeypatch.setattr(gstock,"us_hk_stock",fail)
    response=TestClient(app_module.app).get("/api/global/stock",params={"symbol":"AAPL"})
    assert response.status_code == (400 if kind == "ambiguous" else 503)
    assert "secret" not in response.text
    assert "secret" not in ai_tools.exec_tool("query_global_stock",{"symbol":"AAPL"})["error"]


@pytest.mark.parametrize("query,rows,expected", [
    ("aapl",[row("AAPB"),row("AAPL",105,"Apple")],("AAPL","NASDAQ","105.AAPL","AAPL.O")),
    ("700",[row("07000",116),row("00700",116)],("00700","HK","116.00700","00700.HK")),
    ("005930.KS",[row("00700",116),row("005930",177)],("005930","KR","177.005930",None)),
    ("苹果",[row("AAPB",105,"苹果供应商"),row("AAPL",105,"苹果")],("AAPL","NASDAQ","105.AAPL","AAPL.O")),
])
def test_exact_identity_survives_real_api_and_ai_consumers(search_reply,monkeypatch,query,rows,expected):
    import app as app_module
    import ai_tools
    from fastapi.testclient import TestClient
    search_reply(rows)
    code,market,secid,secucode=expected
    quote_calls,metric_calls=[],[]
    def quote(identity,fields):
        quote_calls.append(identity)
        return {"f57":code,"f58":"Synthetic quote","f43":100,"f59":2}
    def metrics(identity):
        metric_calls.append(identity)
        return None
    monkeypatch.setattr(gstock,"_push2_stock_get",quote)
    monkeypatch.setattr(gstock,"_key_metrics",metrics)
    response=TestClient(app_module.app).get("/api/global/stock",params={"symbol":query})
    assert response.status_code == 200
    api_data=response.json()["data"]
    ai_data=ai_tools.exec_tool("query_global_stock",{"symbol":query})
    assert api_data == ai_data
    assert (api_data["code"],api_data["market"]) == (code,market)
    assert quote_calls == [secid,secid]
    assert metric_calls == ([secucode,secucode] if secucode else [])
