"""Production screener/RDP routes under a test-only, audited no-outbound guard.

Uvicorn creates its event loop before importing this module. On Windows this
also creates its local socketpair before the guard: no general loopback-connect
exception is granted. No provider, model, subprocess, UDP or DNS egress is allowed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import threading

ROOT = Path(os.environ['VR_DATA_DIR']).resolve()
LOG = Path(os.environ['VR_SCREENER_NETWORK_LOG']).resolve()
assert ROOT.is_dir() and LOG.is_relative_to(ROOT)
assert Path(os.environ['VIBE_RESEARCH_RESEARCH_DATA_DIR']).resolve().is_relative_to(ROOT)
assert os.environ.get('VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH') == '1'
violations: list[str] = []
lock = threading.Lock()
LOG.write_text('[]', encoding='utf-8')

# Only standalone guard verification needs to construct its own Windows loop.
verification_loop = None
if __name__ == '__main__' and sys.platform == 'win32':
    import asyncio
    verification_loop = asyncio.SelectorEventLoop()


def reject(kind):
    with lock:
        violations.append(kind)
        LOG.write_text(json.dumps(violations), encoding='utf-8')
    raise RuntimeError(f'Screener offline guard blocked {kind}')


def audit(event, args):
    if event in {'socket.connect', 'socket.sendto', 'socket.sendmsg', 'subprocess.Popen', 'os.system'}:
        reject(event)
    elif event in {'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr'}:
        if args[0] not in {None, '127.0.0.1', '::1'}:
            reject('external_dns')


sys.addaudithook(audit)
# Blocks DNS + all outbound connects at the audit boundary, including callers
# which retained socket method references before this module was imported.
socket.create_connection = lambda *a, **kw: reject('socket.create_connection')

if __name__ == '__main__':
    assert sys.argv[1:] == ['--verify-guard']
    from contextlib import closing
    attempts = [
        lambda: socket.getaddrinfo('provider.invalid', 443),
        lambda: socket.gethostbyname('provider.invalid'),
        lambda: socket.create_connection(('127.0.0.1', 1)),
    ]
    with closing(socket.socket()) as tcp, closing(socket.socket(type=socket.SOCK_DGRAM)) as udp:
        attempts += [
            lambda: tcp.connect(('203.0.113.1', 443)),
            lambda: tcp.connect_ex(('127.0.0.1', 1)),
            lambda: udp.sendto(b'fixture', ('203.0.113.1', 53)),
        ]
        for attempt in attempts:
            try:
                attempt()
            except RuntimeError:
                pass
            else:
                raise AssertionError('guard allowed forbidden operation')
    assert len(violations) == len(attempts)
    print(json.dumps({'blocked_before_network': len(violations), 'violations': violations}))
    if verification_loop is not None:
        verification_loop.close()
    raise SystemExit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend'))
# Optional runtime diagnostics otherwise spawn git while importing the app.
import runtime_info_router
runtime_info_router._git_snapshot = lambda _path: (None, 'offline_fixture')
import app as product
from contextlib import asynccontextmanager


@asynccontextmanager
async def offline_lifespan(_app):
    # This harness tests local reads, not ingestion or schedulers.
    yield


app = product.app
app.router.lifespan_context = offline_lifespan
