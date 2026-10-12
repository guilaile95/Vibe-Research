import asyncio
import json
from pathlib import Path
import socket
from shortline_browser_golden import create_golden

def test_actual_api_and_store_match_browser_goldens(monkeypatch,tmp_path):
    loop=asyncio.new_event_loop()
    monkeypatch.setenv('VR_DATA_DIR',str(tmp_path/'data'))
    def deny(*args,**kwargs):raise AssertionError('external request forbidden')
    for owner,name in [(socket.socket,'connect'),(socket.socket,'connect_ex'),(socket,'create_connection'),(socket,'getaddrinfo')]:monkeypatch.setattr(owner,name,deny)
    try:
        actual=create_golden(monkeypatch,tmp_path,loop)
        expected=json.loads((Path(__file__).parents[2]/'frontend/tests/fixtures/shortline-review-browser.json').read_text(encoding='utf-8'))
        assert actual==expected
        assert actual['daily']['synthetic_model_calls']==6
        assert actual['weekly']['synthetic_model_calls']==4
        assert actual['partial']['version']['stages'][3]['status']=='skipped'
        assert actual['empty']['preview']['available'] is False
    finally:loop.close()
