"""Owned, synthetic HTTP fixture. Never run against a user's data directory.

stdin EOF kills the fixture even if its owner is killed; a fixed lifetime is a
second bound. Only inert adapters are replaced; production routers and stores run.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import threading

ROOT = Path(os.environ['VR_SAVED_JOURNEY_ROOT']).resolve()
assert ROOT.is_dir()
for key in ('VR_DATA_DIR', 'VR_REPORTS_DIR', 'HOME', 'USERPROFILE', 'TMPDIR', 'TEMP', 'TMP'):
    assert Path(os.environ[key]).resolve().is_relative_to(ROOT), key

# Set up the Windows event-loop wakeup sockets before prohibiting connects.
loop = asyncio.SelectorEventLoop() if sys.platform == 'win32' else asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def owner_watch():
    sys.stdin.buffer.read(1)  # No data is ever sent; EOF means the owner is gone.
    os._exit(0)

threading.Thread(target=owner_watch, daemon=True).start()
deadline = threading.Timer(120, lambda: os._exit(90))
deadline.daemon = True
deadline.start()
violations = []
adapter_calls = {'public': 0, 'model': 0}

def reject(event):
    violations.append(event)
    raise RuntimeError('Forbidden synthetic fixture operation: ' + event)

def inside(path):
    return isinstance(path, int) or path == ':memory:' or Path(os.fsdecode(path)).resolve().is_relative_to(ROOT)

def audit(event, args):
    if event == 'open':
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and not inside(path): reject('write_outside_fixture')
    elif event == 'sqlite3.connect' and not inside(args[0]): reject('sqlite_outside_fixture')
    elif event in ('socket.connect', 'socket.sendto', 'socket.sendmsg', 'subprocess.Popen', 'os.system'):
        reject(event)
    elif event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex') and args[0] not in (None, 'localhost', '127.0.0.1', '::1'):
        reject('external_dns')
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir') and not inside(args[0]): reject('filesystem_outside_fixture')
    elif event in ('os.rename', 'os.link', 'os.symlink') and any(not inside(p) for p in args[:2]): reject('filesystem_outside_fixture')

sys.addaudithook(audit)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_info_router
runtime_info_router._git_snapshot = lambda _: (None, 'unknown')
import app as product
import company_research as service
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
import uvicorn

PHASE = os.environ['VR_SAVED_JOURNEY_PHASE']
CLOCK = os.environ['VR_SAVED_JOURNEY_CLOCK']
service.now = lambda: CLOCK

def public():
    adapter_calls['public'] += 1
    if PHASE != 'capture': reject('public_adapter_during_replay')
    return {'value': 0, 'date': CLOCK[:10], 'note': 'SYNTHETIC RESTART FIXTURE'}

service.source_plan = lambda *_: [('public_fixture', service.STAGES[:-1], 'synthetic.public', public)]
async def model(cfg, messages, *, limits):
    adapter_calls['model'] += 1
    if PHASE != 'capture': reject('model_adapter_during_replay')
    context = json.loads(messages[-1]['content'])
    yield {'type': 'delta', 'text': json.dumps({'stage': context['stage'], 'summary': 'Synthetic saved research', 'evidence_ids': ['public_fixture'], 'gaps': ['Unverified synthetic evidence']})}
    yield {'type': 'done'}

service.chat.stream_api_messages = model
product._require_llm_ready = lambda _: False
@asynccontextmanager
async def lifespan(_):
    yield
app = product.app
app.router.lifespan_context = lifespan

@app.middleware('http')
async def allowed(request, call_next):
    path = request.url.path
    permitted = request.method == 'GET' and (path in ('/api/e2e/saved-audit', '/api/company-research/runs') or path.startswith('/api/company-research/bundles/'))
    permitted |= PHASE == 'guard-probes' and request.method == 'GET' and path == '/api/e2e/guard-probes'
    permitted |= PHASE == 'capture' and request.method == 'POST' and path in ('/api/company-research/capture', '/api/company-research/generate')
    if not permitted:
        violations.append('unexpected_http')
        return JSONResponse({'detail': 'UNEXPECTED_FIXTURE_HTTP'}, status_code=503)
    return await call_next(request)

@app.get('/api/e2e/saved-audit')
def receipt():
    return {'violations': violations, 'adapter_calls': adapter_calls, 'pid': os.getpid(), 'clock': service.now(), 'date_mode': 'SIMULATED_NOT_NATURAL_ELAPSED', 'phase': PHASE}

@app.get('/api/e2e/guard-probes')
def guard_probes():
    import sqlite3
    import subprocess
    actions = [lambda: socket.create_connection(('127.0.0.1', 1)),
               lambda: socket.getaddrinfo('fixture.invalid', 443),
               lambda: (ROOT.parent / 'forbidden-probe').write_text('synthetic'),
               lambda: sqlite3.connect(str(ROOT.parent / 'forbidden-probe.db')),
               lambda: subprocess.Popen([sys.executable, '-c', 'pass'])]
    for action in actions:
        try:
            action()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Guard failed closed probe')
    return receipt()

sock = socket.socket()
sock.bind(('127.0.0.1', 0))
sock.listen(128)
(ROOT / 'ready.json').write_text(json.dumps({'port': sock.getsockname()[1], 'pid': os.getpid()}))
server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, loop='asyncio'))
try:
    loop.run_until_complete(server.serve(sockets=[sock]))
finally:
    sock.close()
    loop.close()
    os._exit(0)
