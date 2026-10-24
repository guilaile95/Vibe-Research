import io
import json
import pytest
import ai_credential_store as credentials
import ai_tools
import safe_outputs

SECRET = 'SYNTHETIC_PROXY_PASSWORD'


def test_tool_exception_and_nested_errors_are_safe(monkeypatch):
    def failed(_):
        raise RuntimeError('https://user:' + SECRET + '@example.com/?key=' + SECRET)
    monkeypatch.setitem(ai_tools._HANDLERS, 'synthetic', failed)
    assert SECRET not in json.dumps(ai_tools.exec_tool('synthetic', {}))
    monkeypatch.setitem(ai_tools._HANDLERS, 'synthetic', lambda _: {'data': [{'error': SECRET}], 'status': 'partial', 'date': '2026-10-23'})
    result = ai_tools.exec_tool('synthetic', {})
    assert SECRET not in json.dumps(result) and result['status'] == 'partial'
    assert result['date'] == '2026-10-23'


def test_stdio_mcp_is_independent_output_boundary(monkeypatch):
    import mcp_server
    captured = []
    monkeypatch.setattr(mcp_server.chat, '_exec_tool', lambda *a: {'error': SECRET})
    monkeypatch.setattr(mcp_server, '_result', lambda _id, value: captured.append(value))
    mcp_server._handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'synthetic'}})
    assert captured[0]['isError'] is True
    assert SECRET not in json.dumps(captured)


@pytest.mark.parametrize('url', ['https://user:' + SECRET + '@example.com/v1?key=' + SECRET,
                                'https://' + SECRET + '@example.com/v1'])
def test_credential_url_rejected_and_origin_never_echoes_userinfo(url):
    assert safe_outputs.safe_url_origin(url) == 'https://example.com'
    with pytest.raises(credentials.CredentialStoreError) as caught:
        credentials._validate_payload({'provider': 'openai-compatible', 'baseURL': url, 'apiKey': 'synthetic-key', 'model': 'synthetic-model'})
    assert SECRET not in str(caught.value)


def test_ordinary_origin_and_api_path_are_preserved():
    payload = {'provider': 'openai-compatible', 'baseURL': 'https://example.com:8443/v1', 'apiKey': 'synthetic-key', 'model': 'synthetic-model'}
    assert credentials._validate_payload(payload)['baseURL'] == payload['baseURL']
    assert credentials._sanitize_base_url(payload['baseURL']) == 'https://example.com:8443'


def test_legacy_userinfo_is_not_runnable_but_can_be_cas_repaired(tmp_path, monkeypatch):
    monkeypatch.setenv('VR_DATA_DIR', str(tmp_path))
    path = credentials.credential_path()
    path.parent.mkdir()
    path.write_text(json.dumps({'schema_version': credentials.SCHEMA_VERSION, 'revision': 7,
        'configured': True, 'provider': 'openai-compatible', 'baseURL': 'https://u:' + SECRET + '@example.com/v1',
        'apiKey': 'synthetic-key', 'model': 'synthetic-model', 'updated_at': '2026-10-23T00:00:00Z'}))
    before = path.read_bytes()
    state = credentials.status()
    assert state['revision'] == '7' and state['configured'] is False
    assert SECRET not in json.dumps(state)
    assert credentials.scheduled_config()[0] is None
    assert path.read_bytes() == before
    repaired = credentials.save({'provider': 'openai-compatible', 'baseURL': 'https://example.com/v1',
        'apiKey': 'synthetic-replacement', 'model': 'synthetic-model'}, expected_revision='7')
    assert repaired['revision'] == '8' and repaired['configured'] is True


def test_mcp_top_level_error_never_contains_exception(monkeypatch, capsys):
    import mcp_server
    def fail(_):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(mcp_server, '_handle', fail)
    monkeypatch.setattr(mcp_server, '_force_utf8_stdio', lambda: None)
    monkeypatch.setattr(mcp_server.sys, 'stdin', io.StringIO('{"id":1,"method":"ping"}\n'))
    mcp_server.main()
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert json.loads(output.out)['error']['code'] == -32603


def test_pdf_network_exception_has_fixed_public_message(monkeypatch):
    import app
    import requests
    import myreports
    class Session:
        def get(self, *a, **kw):
            raise requests.exceptions.ProxyError(SECRET)
    monkeypatch.setattr(app, '_report_download_session', Session)
    with pytest.raises(myreports.ReportError) as caught:
        app._download_pdf('https://pdf.dfcfw.com/pdf/H3_TEST_1.pdf')
    assert SECRET not in str(caught.value)
