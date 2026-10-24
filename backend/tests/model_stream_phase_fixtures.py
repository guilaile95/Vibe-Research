"""Phase-local timing for transport tests, separate from DNS admission tests."""
import threading
import time
from types import SimpleNamespace

import httpx
import chat


def isolate_stream_phase(monkeypatch, handler):
    """Remove unrelated DNS-thread/SSL setup while preserving real async timeouts.

    Only the named preparation worker executes inline. The production request
    builder, budget, SSE parser, cancellation scopes and cleanup still run.
    Dedicated DNS/admission tests must not use this helper.
    """
    real_thread = threading.Thread

    def thread(*args, **kwargs):
        if kwargs.get('name') != 'vibe-model-dns':
            return real_thread(*args, **kwargs)
        assert not args and set(kwargs) == {'target', 'daemon', 'name'}
        return SimpleNamespace(start=kwargs['target'])

    monkeypatch.setattr(chat, 'threading', SimpleNamespace(**{**vars(threading), 'Thread': thread}))
    # Avoid building a discarded real TLS context before the mocked client.
    monkeypatch.setattr(chat.model_transport, 'async_transport', lambda endpoint: httpx.MockTransport(handler))
    clock = PhaseClock()
    monkeypatch.setattr(chat, 'time', SimpleNamespace(monotonic=clock.monotonic))
    return clock


class PhaseClock:
    """Model time starts only on explicit phase entry; AnyIO keeps real time."""
    def __init__(self):
        self.started = None
        self.offset = 0.0

    def start(self):
        if self.started is None:
            self.started = time.monotonic()

    def advance(self, seconds):
        self.offset += seconds

    def monotonic(self):
        return self.offset + (time.monotonic() - self.started if self.started is not None else 0.0)
