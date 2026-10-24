"""Offline transport doubles for consumers of the unified bounded chat stream."""
import json


class CompletionStream:
    def __init__(self, message):
        self.message = message
        self.closed = False

    def iter_content(self, chunk_size=None):
        yield ('data: ' + json.dumps({'choices': [{'delta': self.message}]}) + '\n\n').encode()
        yield b'data: [DONE]\n\n'

    def close(self):
        self.closed = True


def install_completion_stream(monkeypatch, chat, completion):
    """Keep real SSE parsing, tool dispatch, budgets and completion validation."""
    def stream(cfg, messages, use_tools):
        cfg['_task_budget'].reserve_dispatch()
        return CompletionStream(completion(cfg, messages, use_tools)['choices'][0]['message'])
    monkeypatch.setattr(chat, '_call_llm_stream', stream)
