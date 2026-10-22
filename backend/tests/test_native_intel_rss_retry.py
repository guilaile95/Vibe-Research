"""Offline RSS transport retry contracts, using only synthetic feeds and errors."""
from __future__ import annotations

from collections import Counter
from email.message import Message
import errno
import http.client
from io import BytesIO
import logging
import socket
import ssl
from types import SimpleNamespace
import urllib.error
from unittest.mock import Mock

import pytest

import native_intel_service as service
import native_intel_store as store


FEED = b'<rss><channel><item><title>Fixture article</title><link>https://example.test/article</link></item></channel></rss>'
EMPTY = b'<rss><channel /></rss>'
SOURCE = {"source_id": "fixture", "name": "Fixture", "url": "https://example.test/rss", "hint": "macro", "source_type": "rss"}


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


class Response(BytesIO):
    def __init__(self, payload=FEED, headers=None):
        super().__init__(payload)
        self.headers = headers or Message()


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(SOURCE["url"], code, "synthetic failure", headers, BytesIO())


def fetch(**kwargs):
    return service._fetch_source_items(SOURCE, per=6, cutoff=None, redline=[], **kwargs)


@pytest.mark.parametrize("failure", [
    TimeoutError("synthetic timeout"),
    urllib.error.URLError(TimeoutError("synthetic timeout")),
    ConnectionResetError("synthetic reset"),
    urllib.error.URLError(ConnectionAbortedError("synthetic abort")),
    OSError(errno.ETIMEDOUT, "synthetic timeout"),
    urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "temporary DNS")),
    *[http_error(code) for code in (408, 502, 503, 504)],
])
@pytest.mark.parametrize("proxy", [False, True])
def test_transient_failure_retries_once_with_remaining_budget(monkeypatch, caplog, failure, proxy):
    clock = Clock()
    monkeypatch.setattr(service.time, "monotonic", clock)
    timeouts = []

    def open_request(_request, *, timeout):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            clock.now += 4
            raise failure
        return Response()

    direct = Mock(side_effect=open_request)
    proxied = Mock(side_effect=open_request)
    monkeypatch.setattr(service.urllib.request, "urlopen", direct)
    monkeypatch.setattr(service.urllib.request, "build_opener", Mock(return_value=SimpleNamespace(open=proxied)))
    caplog.set_level(logging.INFO, logger="native_intel")
    items, kind, detail = fetch(proxy_url="http://proxy.example.test:8080" if proxy else None)

    assert kind is detail is None
    assert len(items) == 1
    assert timeouts == [service.FETCH_TIMEOUT, service.FETCH_TIMEOUT - 4]
    assert (proxied.call_count, direct.call_count) == ((2, 0) if proxy else (0, 2))
    assert "attempt=1" in caplog.text
    if isinstance(failure, urllib.error.HTTPError):
        assert failure.closed


@pytest.mark.parametrize("payload, count", [(FEED, 1), (EMPTY, 0)])
def test_success_and_legal_empty_need_one_request(monkeypatch, payload, count):
    opener = Mock(return_value=Response(payload))
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    items, kind, detail = fetch()
    assert len(items) == count
    assert kind is detail is None
    assert opener.call_count == 1


@pytest.mark.parametrize("failure", [
    ssl.SSLCertVerificationError("synthetic certificate failure"),
    urllib.error.URLError(ssl.SSLCertVerificationError("synthetic certificate failure")),
    ssl.SSLError("synthetic TLS failure"),
    urllib.error.URLError("unknown network failure"),
    urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, "permanent DNS failure")),
    ConnectionRefusedError(errno.ECONNREFUSED, "refused"),
    ValueError("bad argument"),
    *[http_error(code) for code in (401, 403, 404, 429, 500, 501)],
    http_error(503, "120"),
    http_error(502, ""),
])
def test_non_allowlisted_errors_do_not_retry(monkeypatch, failure):
    opener = Mock(side_effect=failure)
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    items, kind, detail = fetch()
    assert items == []
    assert (kind, detail) == service._classify_error(failure)
    assert opener.call_count == 1


def test_parse_error_does_not_retry(monkeypatch):
    opener = Mock(return_value=Response(b"<rss>"))
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    assert fetch() == ([], store.ERROR_KIND_PARSE, "ParseError")
    assert opener.call_count == 1



@pytest.mark.parametrize("raw_time, expected", [
    ("2026-10-22T12:34:56Z", "2026-10-22T20:34:56+08:00"),
    ("2026-10-22T12:34:56.123456-04:00", "2026-10-23T00:34:56.123456+08:00"),
    ("", None),
])
def test_retry_preserves_existing_date_and_missing_time_semantics(monkeypatch, raw_time, expected):
    payload = FEED.replace(b"</item>", f"<pubDate>{raw_time}</pubDate></item>".encode())
    opener = Mock(side_effect=[ConnectionResetError(), Response(payload)])
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    items, kind, detail = fetch()
    assert kind is detail is None and len(items) == 1
    assert items[0]["published_at"] == expected
    assert opener.call_count == 2


def test_invalid_request_argument_never_opens_network(monkeypatch):
    opener = Mock()
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    items, kind, detail = service._fetch_source_items(
        {**SOURCE, "url": "not a URL"}, per=6, cutoff=None, redline=[]
    )
    assert items == [] and kind == store.ERROR_KIND_UNKNOWN and detail == "ValueError"
    opener.assert_not_called()

def test_two_failures_keep_final_structured_error_and_safe_attempt_log(monkeypatch, caplog):
    opener = Mock(side_effect=[TimeoutError("first synthetic failure"), ConnectionResetError("https://user:SECRET@proxy.test/feed?token=SECRET")])
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    caplog.set_level(logging.INFO, logger="native_intel")
    assert fetch() == ([], store.ERROR_KIND_NETWORK, "ConnectionResetError")
    assert opener.call_count == 2
    assert "attempt=1" in caplog.text and "attempt=2" in caplog.text
    assert "SECRET" not in caplog.text and "proxy.test" not in caplog.text


def test_exhausted_budget_never_starts_second_request(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(service.time, "monotonic", clock)

    def fail(_request, *, timeout):
        clock.now += timeout
        raise TimeoutError("budget spent")

    opener = Mock(side_effect=fail)
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    assert fetch() == ([], store.ERROR_KIND_TIMEOUT, "TimeoutError")
    assert opener.call_count == 1
    assert clock.now == 100 + service.FETCH_TIMEOUT


def test_read_timeout_retries_with_remaining_budget_and_closes_response(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(service.time, "monotonic", clock)

    class BrokenResponse(Response):
        def read1(self, _size=-1):
            clock.now += 3
            raise TimeoutError("synthetic body timeout")

        read = read1

    first = BrokenResponse()
    opener = Mock(side_effect=[first, Response()])
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    items, kind, detail = fetch()
    assert kind is detail is None and len(items) == 1
    assert first.closed
    assert [call.kwargs["timeout"] for call in opener.call_args_list] == [service.FETCH_TIMEOUT, service.FETCH_TIMEOUT - 3]


def test_retry_after_on_response_prevents_retry_after_read_failure(monkeypatch):
    class BrokenResponse(Response):
        def read1(self, _size=-1):
            raise TimeoutError("synthetic body timeout")

        read = read1

    headers = Message()
    headers["Retry-After"] = "120"
    opener = Mock(return_value=BrokenResponse(headers=headers))
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    assert fetch() == ([], store.ERROR_KIND_TIMEOUT, "TimeoutError")
    assert opener.call_count == 1


def test_slow_body_uses_remaining_socket_budget_and_is_not_success(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(service.time, "monotonic", clock)
    timeouts = []

    class SlowResponse(Response):
        def __init__(self):
            super().__init__()
            self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append)))

        def read1(self, _size=-1):
            remaining = timeouts[-1] if timeouts else service.FETCH_TIMEOUT
            clock.now += min(8, remaining)
            if remaining <= 8:
                raise TimeoutError("synthetic slow body")
            return b"<rss>"

        def read(self, _size=-1):
            clock.now += service.FETCH_TIMEOUT * 2
            return FEED

    response = SlowResponse()

    def open_response(_request, *, timeout):
        clock.now += 4
        return response

    opener = Mock(side_effect=open_response)
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    assert fetch() == ([], store.ERROR_KIND_TIMEOUT, "TimeoutError")
    assert timeouts == [service.FETCH_TIMEOUT - 4, service.FETCH_TIMEOUT - 12]
    assert clock.now == 100 + service.FETCH_TIMEOUT
    assert opener.call_count == 1 and response.closed


def test_baseexception_interrupt_is_not_swallowed_or_retried(monkeypatch):
    opener = Mock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    with pytest.raises(KeyboardInterrupt):
        fetch()
    assert opener.call_count == 1


def test_run_fetch_retries_transport_only_preserves_history_and_empty_state(tmp_path, monkeypatch):
    sources = [{**SOURCE, "source_id": name, "name": name, "url": f"https://example.test/{name}"} for name in ("recovered", "failed", "empty")]
    registry = {"sources": sources, "registry_version": "fixture", "redline": [], "recent_days": 7, "per_source": 6}
    path = str(tmp_path / "intel.sqlite3")
    store.upsert_sources(sources, path)
    store.start_run("history", "test", 1, path)
    store.upsert_observation("history", "failed", {"item_key": "history", "title": "Historical fixture", "title_key": "historical fixture", "url": "https://example.test/old", "canonical_url": "https://example.test/old", "summary": "", "hint": "macro", "published_at": None, "published_ts": 0}, observed_at=service.utc_now_iso(), has_real_rank=False, db_path=path)
    before = store.export_state(path)
    attempts = Counter()

    def open_request(request, *, timeout):
        name = request.full_url.rsplit("/", 1)[-1]
        attempts[name] += 1
        if name == "failed" or (name == "recovered" and attempts[name] == 1):
            raise ConnectionResetError("synthetic temporary reset")
        return Response(EMPTY if name == "empty" else FEED)

    monkeypatch.setattr(service.urllib.request, "urlopen", open_request)
    result = service.run_fetch("test", path, registry=registry, sources_override=sources)
    after = store.export_state(path)
    assert attempts == {"recovered": 2, "failed": 2, "empty": 1}
    assert result["status"] == store.RUN_STATUS_PARTIAL
    assert result["source_failed"] == 1 and result["source_ok"] == 2
    assert result["item_seen"] == result["item_new"] == 1
    assert len(after["items"]) == len(after["observations"]) == 2
    assert before["items"][0] in after["items"]
    assert before["observations"][0] in after["observations"]
    with store._connect(path) as conn:
        states = {row["source_id"]: (row["status"], row["error_kind"]) for row in conn.execute("SELECT * FROM intel_source_runs WHERE run_id = ?", (result["run_id"],))}
    assert states == {"recovered": (store.SOURCE_RUN_OK, None), "failed": (store.SOURCE_RUN_FAILED, store.ERROR_KIND_NETWORK), "empty": (store.SOURCE_RUN_EMPTY, None)}



def http_response(headers, body):
    """Exercise the real stdlib HTTPResponse framing without opening a socket."""
    wire = b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n" + body
    response = http.client.HTTPResponse(SimpleNamespace(makefile=lambda _mode: BytesIO(wire)))
    response.begin()
    return response


@pytest.mark.parametrize("payload", [EMPTY, FEED])
def test_http_response_truncated_content_length_keeps_original_failure(monkeypatch, payload):
    response = http_response(f"Content-Length: {len(payload) + 100}\r\n".encode(), payload)
    opener = Mock(return_value=response)
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    assert fetch() == ([], store.ERROR_KIND_UNKNOWN, "IncompleteRead")
    assert opener.call_count == 1
    assert response.isclosed()


@pytest.mark.parametrize("transfer", ["fixed", "chunked", "close"])
@pytest.mark.parametrize("payload, count", [(EMPTY, 0), (FEED, 1)])
def test_http_response_complete_framing_remains_accepted(monkeypatch, transfer, payload, count):
    if transfer == "fixed":
        headers, body = f"Content-Length: {len(payload)}\r\n".encode(), payload
    elif transfer == "chunked":
        headers = b"Transfer-Encoding: chunked\r\n"
        body = f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n"
    else:
        headers, body = b"Connection: close\r\n", payload
    opener = Mock(return_value=http_response(headers, body))
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    items, kind, detail = fetch()
    assert kind is detail is None and len(items) == count
    assert opener.call_count == 1


def test_http_response_truncated_chunked_body_keeps_original_failure(monkeypatch):
    body = f"{len(EMPTY):x}\r\n".encode() + EMPTY + b"\r\n"
    opener = Mock(return_value=http_response(b"Transfer-Encoding: chunked\r\n", body))
    monkeypatch.setattr(service.urllib.request, "urlopen", opener)
    assert fetch() == ([], store.ERROR_KIND_UNKNOWN, "IncompleteRead")
    assert opener.call_count == 1
