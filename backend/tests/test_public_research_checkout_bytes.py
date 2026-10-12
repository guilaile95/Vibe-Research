"""Exact provenance bytes survive Windows-style Git checkout without normalization."""
import hashlib
from pathlib import Path
import subprocess

import pytest
from fact_lake_store import initialize_fact_lake
import public_research_archive as archive
import public_research_contract as C
from public_research_fixtures import raw, CAPTURED

ROOT = Path(__file__).parents[2]
PINNED_SHA256 = {
    'backend/tests/fixtures/public_research/polymarket.json': '0f2a85e92aca45b23f421fed5de8ec49bcec303a5841f5e5ee4e3c70e17efe1e',
    'backend/tests/fixtures/public_research/kalshi.json': '224b681a20bd30a8a591c6187033ddd0c928cab32c83c705f373105225cfc940',
    'backend/tests/fixtures/public_research/taiwan.json': '82c6077b6281ab04d2d221375234f45fd408fdfc8c40f2fa131f0883f1d87bf9',
    'backend/tests/fixtures/public_research/dram.json': '4133b1501488f5e41fb4777624e52d79ff641c28e5318f41d373ac175324c14b',
    'backend/tests/fixtures/public_research/commodity.txt': '4e4dc114978e86e329aa0b8dfd451e120d44ed0a1de23d938a5a553efd0cb04d',
    'backend/tests/fixtures/public_research/hiring.json': '59a4f04c912d361ab4878edebac9ee2e7aaf94e0ba4117f480e48b5106b798be',
    'docs/third-party/vibe-astock-LICENSE': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30',
    'docs/third-party/vibe-astock-NOTICE': '2bc1decf17882fe77b6592025fefb774798ac92945501707ffea8783c2afe276',
}


def test_git_autocrlf_checkout_preserves_exact_evidence_bytes(tmp_path):
    """Exercise Git's actual conversion, with an unpinned conversion control."""
    repo = tmp_path / 'repository'; repo.mkdir()
    out = tmp_path / 'checkout'; out.mkdir()
    def git(*args):
        return subprocess.run(['git', '-c', 'core.autocrlf=true', '-c', 'core.safecrlf=false', *args],
                              cwd=repo, check=True, capture_output=True, timeout=30)
    git('init', '--quiet')
    (repo / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
    for name, expected in PINNED_SHA256.items():
        body = (ROOT / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == expected
        assert hashlib.sha256(body.replace(b'\n', b'\r\n')).hexdigest() != expected
        target = repo / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
    (repo / 'unmarked-control.txt').write_bytes(b'alpha\nbeta\n')
    git('add', '--all')
    git('checkout-index', '--all', '--prefix=' + out.as_posix() + '/')
    assert (out / 'unmarked-control.txt').read_bytes() == b'alpha\r\nbeta\r\n'
    for name, expected in PINNED_SHA256.items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('source', list(C.SOURCES))
def test_crlf_remains_different_raw_evidence_not_silently_normalized(tmp_path, source):
    lake = initialize_fact_lake(tmp_path / 'lake')
    subject = C.SOURCES[source]['subjects'][0]
    lf = raw(source, subject)
    crlf = lf.replace(b'\n', b'\r\n')
    assert lf != crlf
    receipts = [archive.persist_capture(lake, body, source, subject, CAPTURED, fixture=True)
                for body in (lf, crlf)]
    assert receipts[0]['raw_payload_hash'] != receipts[1]['raw_payload_hash']
    for body, receipt in zip((lf, crlf), receipts):
        assert receipt['raw_payload_hash'] == 'sha256:' + hashlib.sha256(body).hexdigest()
        assert lake.read_payload(receipt['observation_id']) == body
        replayed = archive.replay(lake, lake.get_observation(receipt['observation_id']))
        assert replayed['evidence']['raw_payload_hash'] == receipt['raw_payload_hash']
