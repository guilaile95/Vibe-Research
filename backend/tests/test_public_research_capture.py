"""Mocked public HTTP through the real producer/archive/readback; never live IO."""
import hashlib
import json
from pathlib import Path
import socket

import httpx
import pytest

from fact_lake_store import initialize_fact_lake, FactLakeNotInitializedError
import public_research_capture as capture
import public_research_contract as C
import public_research_extended_service as service
from extended_public_fixtures import raw, CUTOFF

SUBJECT = 'A:600000@' + CUTOFF


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('no actual network in manual capture acceptance')
    for name in ('connect', 'connect_ex'):
        monkeypatch.setattr(socket.socket, name, deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks): self.chunks = chunks; self.closed = False
    def __iter__(self): yield from self.chunks
    def close(self): self.closed = True


def factory_for(body, *, status=200, headers=None):
    calls = []; streams = []; options = []
    def handler(request):
        calls.append(request)
        stream = Stream([body]); streams.append(stream)
        return httpx.Response(status, headers=headers, stream=stream)
    def factory(**kwargs):
        options.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    return factory, calls, streams, options


def test_default_plan_does_not_open_archive_or_construct_http_client(tmp_path):
    target = tmp_path / 'absent'
    def forbidden(**kwargs): pytest.fail('plan constructed a network client')
    result = capture.capture_once(capture.SOURCE, SUBJECT, str(target), client_factory=forbidden)
    assert result['mode'] == 'PLAN_ONLY' and result['model_calls'] == 0
    assert result['schedule_enabled'] is False and not target.exists()


@pytest.mark.parametrize('source,subject', [('unknown', SUBJECT), ('global_quote_ref', 'US:AAPL@'+CUTOFF),
    ('cn_quote_ref', 'A:600000@2026-02-30'), ('cn_quote_ref', 'A:600000?token=x@'+CUTOFF),
    ('cn_quote_ref', 'US:AAPL@'+CUTOFF), ('cn_quote_ref', 'A:600000@2099-01-01')])
def test_identity_rejected_before_archive_or_transport(tmp_path, source, subject):
    with pytest.raises(ValueError):
        capture.capture_once(source, subject, str(tmp_path/'absent'), execute=True,
                             client_factory=lambda **kw: pytest.fail('unexpected client'))
    assert not (tmp_path/'absent').exists()


def test_no_implicit_archive_or_initialization(tmp_path):
    with pytest.raises(capture.CaptureError, match='ABSOLUTE'):
        capture.plan(capture.SOURCE, SUBJECT, 'relative')
    with pytest.raises(FactLakeNotInitializedError):
        capture.capture_once(capture.SOURCE, SUBJECT, str(tmp_path/'absent'), execute=True,
                             client_factory=lambda **kw: pytest.fail('unexpected client'))
    assert not (tmp_path/'absent').exists()


def test_one_request_exact_bytes_real_archive_and_existing_reader(tmp_path, monkeypatch):
    root = tmp_path/'isolated-lake'; lake = initialize_fact_lake(root)
    outside = tmp_path/'private-canary'; outside.write_bytes(b'untouched')
    body = raw(capture.SOURCE, SUBJECT)
    factory, calls, streams, options = factory_for(body)
    result = capture.capture_once(capture.SOURCE, SUBJECT, str(root), execute=True, client_factory=factory)
    assert result['mode'] == 'CAPTURED' and result['status'] == 'partial'
    assert result['model_calls'] == 0 and result['point_in_time_claim'] == 'NONE'
    receipt = result['receipt']; assert receipt['fixture'] is False
    assert lake.read_payload(receipt['observation_id']) == body
    assert receipt['raw_payload_hash'] == 'sha256:' + hashlib.sha256(body).hexdigest()
    assert len(calls) == 1 and calls[0].method == 'GET'
    assert str(calls[0].url) == C.request_spec(capture.SOURCE, SUBJECT)
    assert not any(h in calls[0].headers for h in ('authorization', 'cookie'))
    assert options == [dict(timeout=5.0, follow_redirects=False, trust_env=False, verify=True)]
    assert streams[0].closed and outside.read_bytes() == b'untouched'
    monkeypatch.setenv('VR_FACT_LAKE_ROOT', str(root))
    before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    blocks, error = service.load_blocks([(capture.SOURCE, SUBJECT)])
    assert error is None and len(blocks) == 1 and blocks[0]['rows']
    assert blocks[0]['evidence']['raw_payload_hash'] == receipt['raw_payload_hash']
    assert blocks[0]['requested_as_of'] == CUTOFF
    assert before == {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('status,body', [(503,b'provider unavailable'), (200,b'malformed raw quote')])
def test_source_failure_preserved_as_unavailable_not_empty_success(tmp_path, status, body):
    root=tmp_path/'lake';lake=initialize_fact_lake(root)
    factory,calls,streams,_=factory_for(body,status=status)
    result=capture.capture_once(capture.SOURCE,SUBJECT,str(root),execute=True,client_factory=factory)
    assert result['status']=='unavailable' and result['reason_codes']==['HTTP_OR_NORMALIZATION_FAILED']
    assert lake.read_payload(result['receipt']['observation_id'])==body
    assert len(calls)==1 and streams[0].closed


@pytest.mark.parametrize('status,headers,body,code', [
    (302,{'location':'https://unrelated.invalid'},b'redirect','REDIRECT_REJECTED'),
    (200,{'content-encoding':'gzip'},b'encoded','ENCODED_RESPONSE_REJECTED'),
    (200,{'content-length':str(C.MAX_BYTES+1)},b'x','RESPONSE_SIZE_REJECTED'),
    (200,{'content-length':'invalid'},b'x','RESPONSE_SIZE_REJECTED'),
    (200,{},b'x'*(C.MAX_BYTES+1),'RESPONSE_SIZE_REJECTED'),
    (200,{},b'','EMPTY_RESPONSE')])
def test_transport_rejection_does_not_publish_receipt(tmp_path,status,headers,body,code):
    root=tmp_path/'lake';initialize_fact_lake(root)
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    factory,calls,streams,_=factory_for(body,status=status,headers=headers)
    with pytest.raises(capture.CaptureError,match=code):
        capture.capture_once(capture.SOURCE,SUBJECT,str(root),execute=True,client_factory=factory)
    assert len(calls)==1 and streams[0].closed
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_elapsed_budget_and_network_failure_are_safe_and_bounded(tmp_path):
    root=tmp_path/'lake';initialize_fact_lake(root)
    factory,_,streams,_=factory_for(b'x')
    ticks=iter([0,21])
    with pytest.raises(capture.CaptureError,match='ELAPSED_BUDGET'):
        capture.capture_once(capture.SOURCE,SUBJECT,str(root),execute=True,client_factory=factory,clock=lambda:next(ticks))
    assert streams[0].closed
    def failure(**kwargs): raise httpx.ConnectError('sensitive transport detail')
    with pytest.raises(capture.CaptureError,match='^PUBLIC_TRANSPORT_UNAVAILABLE$'):
        capture.capture_once(capture.SOURCE,SUBJECT,str(root),execute=True,client_factory=failure)


def test_transport_refuses_url_or_policy_changes():
    expected=C.request_spec(capture.SOURCE,SUBJECT)
    transport=capture.bounded_transport(expected,client_factory=lambda **kw:pytest.fail('client created'))
    for change in ({'url':'https://unrelated.invalid'}, {'allow_redirects':True}, {'max_bytes':C.MAX_BYTES+1}, {'timeout':21}):
        kwargs=dict(url=expected,max_bytes=C.MAX_BYTES,timeout=20,allow_redirects=False);kwargs.update(change)
        with pytest.raises(capture.CaptureError,match='TRANSPORT_CONTRACT_MISMATCH'):transport(**kwargs)


def test_cli_default_and_failure_messages(tmp_path,capsys):
    argv=['--source',capture.SOURCE,'--subject',SUBJECT,'--archive-root',str(tmp_path/'absent')]
    assert capture.main(argv)==0
    assert json.loads(capsys.readouterr().out)['mode']=='PLAN_ONLY'
    assert capture.main(argv+['--execute'])==2
    result=json.loads(capsys.readouterr().out)
    assert result=={'status':'unavailable','reason_codes':['ARCHIVE_OR_IDENTITY_UNAVAILABLE'],'model_calls':0}
