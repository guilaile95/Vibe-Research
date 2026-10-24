"""Opt-in ONE live public overview refresh in isolated storage, never a load test.

Uses the production 12s response / 210s shared worker lifetime. Records only stage
metrics, provider hostnames, status/coverage counts, not market rows or errors.
Run only with permission to access the production public-provider endpoints.
"""
from __future__ import annotations
import argparse
from concurrent.futures import TimeoutError as FutureTimeout
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlsplit


def _measured_child(path, operation, code):
    events_path = Path(os.environ['VR_PERF_EVENT_FILE'])
    started = time.monotonic()
    def record(event, **values):
        packet = {'event': event, 'elapsed_s': time.monotonic() - started, **values}
        with events_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(packet) + '\n')
    record('child_started')
    import market
    import astock
    import public_data_budget
    import requests
    record('imports_ready')
    def stage(owner, name):
        original = getattr(owner, name)
        def measured(*args, **kwargs):
            wall, cpu = time.monotonic(), time.process_time()
            record('stage_started', stage=name)
            try:
                result = original(*args, **kwargs)
            except BaseException as exc:
                record('stage_ended', stage=name, status='exception', error_type=type(exc).__name__,
                       wall_s=time.monotonic()-wall, cpu_s=time.process_time()-cpu)
                raise
            counts = {}
            if isinstance(result, list):
                counts['rows'] = len(result)
            if isinstance(result, dict):
                counts['status'] = result.get('status')
                if isinstance(result.get('data'), dict):
                    counts['stock_count'] = result['data'].get('stock_count')
                    counts['valid_count'] = result['data'].get('valid_count')
            record('stage_ended', stage=name, wall_s=time.monotonic()-wall,
                   cpu_s=time.process_time()-cpu, **counts)
            return result
        setattr(owner, name, measured)
    for owner, name in [(astock, 'a_share_snapshot'), (market, 'calculate_market_breadth'),
                        (market, 'get_market_breadth'), (market, '_emotion'), (market, '_sectors')]:
        stage(owner, name)
    original_send = requests.sessions.Session.send
    def send(session, request, **kwargs):
        wall = time.monotonic()
        host = urlsplit(request.url).hostname
        record('request_started', host=host)
        try:
            response = original_send(session, request, **kwargs)
        except BaseException as exc:
            record('request_ended', host=host, wall_s=time.monotonic()-wall, error_type=type(exc).__name__)
            raise
        record('request_ended', host=host, wall_s=time.monotonic()-wall, http_status=response.status_code)
        return response
    requests.sessions.Session.send = send
    public_data_budget._child(path, operation, code)
    record('child_finished')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-live-public', action='store_true', required=True)
    p.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    source = args.source_root.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    events = args.output.with_suffix('.events.jsonl').resolve()
    if events.exists() or args.output.exists():
        p.error('choose fresh output paths; never append unrelated probe runs')
    sys.path.insert(0, str(source / 'tools'))
    from validation_environment import configure_pytest_environment
    with tempfile.TemporaryDirectory(prefix='vr-live-perf-') as tmp:
        configure_pytest_environment(Path(tmp), os.environ)
        os.environ['VR_PERF_EVENT_FILE'] = str(events)
        sys.path.insert(0, str(source / 'backend'))
        import public_data_budget as budget
        budget._child = _measured_child
        budget.startup()
        started = time.monotonic()
        output = {'schema':'one-live-market-probe.v1','scope':'isolated cloud executor, not user machine',
                  'input':'live public no credentials', 'response_budget_s':budget.TIMEOUT,
                  'worker_budget_s':budget.OVERVIEW_TIMEOUT}
        try:
            try:
                value = budget.run('overview')
                output['initial'] = {'status':'completed', 'elapsed_s':time.monotonic()-started}
            except budget.PublicDataUnavailable as exc:
                output['initial'] = {'status':exc.code, 'elapsed_s':time.monotonic()-started}
                if exc.code != 'SOURCE_REFRESH_PENDING':
                    raise
                # Await the SAME production flight, not another refresh/poll.
                value = budget._OVERVIEW_FLIGHT.result(timeout=max(0, budget.OVERVIEW_TIMEOUT+3-(time.monotonic()-started)))
            sentiment = value.get('sentiment') or {}
            output['complete'] = {'elapsed_s':time.monotonic()-started, 'status':sentiment.get('status'),
                                  'breadth_status':sentiment.get('breadth_status'),
                                  'stock_count':sentiment.get('stock_count'), 'valid_count':sentiment.get('valid_count'),
                                  'sector_rows':len(value.get('sectors') or [])}
        except BaseException as exc:
            output['complete'] = {'elapsed_s':time.monotonic()-started, 'status':getattr(exc,'code',type(exc).__name__)}
        finally:
            budget.shutdown()
            output['worker_reaped'] = budget._OVERVIEW_THREAD is None or not budget._OVERVIEW_THREAD.is_alive()
            recorded = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
            output['events'] = recorded
            output['request_count'] = sum(e['event']=='request_started' for e in recorded)
            useful = [e for e in recorded if e['event']=='stage_ended' and e.get('stage')=='get_market_breadth' and e.get('valid_count',0) and e.get('status') in ('normal','partial')]
            output['first_useful_breadth_in_worker_s'] = useful[0]['elapsed_s'] if useful else None
            # First internal breadth availability is not browser-visible until current
            # aggregate completes; do not label it client first content.
            output['first_useful_breadth_client_visible'] = False
            args.output.write_text(json.dumps(output, indent=2)+'\n')
            print(json.dumps({k:v for k,v in output.items() if k!='events'}, indent=2))


if __name__ == '__main__':
    main()
