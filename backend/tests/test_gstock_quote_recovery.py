"""A previously successful fallback must not permanently exclude the primary."""
from urllib.parse import urlsplit

import pytest
import gstock


class Response:
    def __init__(self, data):
        self.data = data

    def json(self):
        return {"data": self.data}


@pytest.mark.parametrize("fallback_failure", ["connection", "empty"])
def test_global_indices_recovers_primary_after_fallback_stops_working(monkeypatch, fallback_failure):
    monkeypatch.setattr(gstock, "_gs_host", [0])
    monkeypatch.setattr(gstock, "_INDICES", (gstock._INDICES[0],))
    phase = ["primary-down"]
    calls = []

    def fetch(url, *, params, **kwargs):
        host = urlsplit(url).hostname
        calls.append((host, params.copy()))
        assert params["secid"] == "100.DJIA"
        if phase[0] == "primary-down" and host == gstock._GS_HOSTS[0]:
            raise ConnectionError("fixture primary failure")
        if phase[0] == "fallback-down" and host == gstock._GS_HOSTS[1]:
            if fallback_failure == "connection":
                raise ConnectionError("fixture fallback failure")
            return Response(None)
        return Response({"f43": 4200000, "f59": 2, "f170": 125})

    monkeypatch.setattr(gstock.astock, "em_get", fetch)
    first = gstock.global_indices()
    phase[0] = "fallback-down"
    second = gstock.global_indices()
    assert first == second == [{"key": "dji", "name": "道琼斯", "region": "美股", "price": 42000.0, "change_pct": 1.25}]
    assert [host for host, _ in calls] == [*gstock._GS_HOSTS, *reversed(gstock._GS_HOSTS)]
    calls.clear()
    assert gstock.global_indices() == second
    assert [host for host, _ in calls] == [gstock._GS_HOSTS[0]]


def test_all_hosts_fail_remains_unavailable_and_does_not_return_old_quote(monkeypatch):
    monkeypatch.setattr(gstock, "_gs_host", [1])
    monkeypatch.setattr(gstock, "_INDICES", (gstock._INDICES[0],))
    calls = []

    def fetch(url, **kwargs):
        calls.append(urlsplit(url).hostname)
        raise ConnectionError("fixture failure")

    monkeypatch.setattr(gstock.astock, "em_get", fetch)
    assert gstock.global_indices() == []
    assert calls == list(reversed(gstock._GS_HOSTS))
