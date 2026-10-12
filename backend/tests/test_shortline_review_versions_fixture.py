"""Browser versions golden matches the actual registered route on a missing store."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
import app
import shortline_review_store as store


def test_empty_version_goldens_are_actual_route_readbacks(tmp_path,monkeypatch):
    archive=tmp_path/'absent'/'review.sqlite3'
    monkeypatch.setattr(store.review_history,'resolve_review_db_path',lambda:archive)
    golden=json.loads((Path(__file__).parents[2]/'frontend/tests/fixtures/shortline-review-empty-versions.json').read_text())
    client=TestClient(app.app)
    for day,expected in golden.items():
        url=f'/api/shortline-review/versions?trade_date={day}&mode=daily'
        response=client.get(url)
        assert response.status_code==200 and response.json()==expected
        for suffix in ('&mode=daily','&trade_date='+day,'&refresh=true','&root=/tmp'):
            assert client.get(url+suffix).status_code==400
        assert client.post(url,json={}).status_code==405
    assert client.get('/api/shortline-review/versions?trade_date=2026-02-30&mode=daily').status_code==422
    assert not archive.parent.exists()
