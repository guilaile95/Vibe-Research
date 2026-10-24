"""Offline production full-A page mapping/breadth/cloud local-cost baseline.

Synthetic 6000-stock paginated payload, no network or fake network sleep. Timings
are local costs ONLY and explicitly exclude vendor pacing/network/process spawn.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import sys
import tempfile
import time
from unittest.mock import patch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--rows', type=int, default=6000)
    p.add_argument('--samples', type=int, default=20)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if not 1 <= a.rows <= 20000 or not 1 <= a.samples <= 100:
        p.error('fixture size exceeds benchmark bound')
    sys.path.insert(0, str(a.source_root / 'tools'))
    from validation_environment import configure_pytest_environment
    with tempfile.TemporaryDirectory(prefix='vr-perf-market-') as tmp:
        configure_pytest_environment(Path(tmp), os.environ)
        def deny(*args, **kwargs):
            raise RuntimeError('network prohibited in offline performance benchmark')
        with patch.object(socket, 'create_connection', deny), patch.object(socket, 'getaddrinfo', deny):
            sys.path.insert(0, str(a.source_root / 'backend'))
            import astock
            import market
            rows = [dict(f12=f'{i:06d}', f14=f'Synthetic{i}', f13=0, f2=10+i%50, f3=(i%19)-9,
                         f4=1, f5=1000, f6=100000+i, f7=2, f8=i%25, f9=10, f15=61, f16=9,
                         f17=10, f18=10, f20=1000000000+i, f21=500000000+i, f23=2,
                         f26=20200101, f100=f'industry{i%60}', f115=12) for i in range(a.rows)]
            calls = []
            class Response:
                def __init__(self, data): self.data = data
                def json(self): return self.data
            def page(_url, *, params, **_kwargs):
                pn,pz=int(params['pn']),int(params['pz'])
                calls.append(pn)
                return Response({'data':{'total':len(rows),'diff':rows[(pn-1)*pz:pn*pz]}})
            astock._em_get_page_with_retries = page
            def measure(fn, prepare=None):
                output=[]
                for _ in range(a.samples):
                    if prepare: prepare()
                    n=len(calls); wall,cpu=time.perf_counter_ns(),time.process_time_ns()
                    result=fn()
                    output.append(dict(wall_ms=(time.perf_counter_ns()-wall)/1e6,cpu_ms=(time.process_time_ns()-cpu)/1e6,
                                       page_requests=len(calls)-n, status=result.get('status') if isinstance(result,dict) else None,
                                       returned_rows=len(result) if isinstance(result,list) else None))
                vals=sorted(x['wall_ms'] for x in output)
                return dict(samples=output,p50_ms=statistics.median(vals),p95_ms=vals[math.ceil(len(vals)*.95)-1])
            results={}
            results['map_validate_full_snapshot']=measure(astock.a_share_snapshot)
            results['breadth_cold']=measure(market.get_market_breadth, market._CACHE.clear)
            results['breadth_warm']=measure(market.get_market_breadth)
            results['cloud_warm']=measure(market.get_market_cloud)
            # Semantic checks are not mixed into successful timing percentiles.
            market._CACHE.clear()
            original=astock.a_share_snapshot
            astock.a_share_snapshot=lambda: []
            empty=market.get_market_breadth()
            empty_cached='a_share_snapshot' in market._CACHE
            def failure(): raise RuntimeError('synthetic provider failure')
            astock.a_share_snapshot=failure
            failed=market.get_market_breadth()
            failed_cached='a_share_snapshot' in market._CACHE
            astock.a_share_snapshot=lambda: original()[:100]
            partial=market.get_market_breadth()
            output=dict(schema='market-local-cost.v1', environment=dict(platform=platform.platform(),python=sys.version),
                        fixture=dict(rows=a.rows,samples=a.samples,network='DENIED',transport='SYNTHETIC',
                                     excludes=['vendor delay','throttling sleep','actual network','process spawn']),
                        measurements=results,states=dict(empty=empty['status'],empty_cached=empty_cached,
                        failure=failed['status'],failure_cached=failed_cached,partial=partial['status']))
            a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(output,indent=2)+'\n')
            print(json.dumps({k:{f:v[f] for f in ('p50_ms','p95_ms')} for k,v in results.items()},indent=2))


if __name__=='__main__': main()
