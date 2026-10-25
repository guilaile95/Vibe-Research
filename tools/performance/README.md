# Reproducible performance measurements

`local_api_baseline.py` measures the current production app without patching its
handlers. Run it using the platform's locked backend development interpreter:

```sh
python tools/performance/local_api_baseline.py --output local-api.json \
  --startup-runs 7 --samples 40 --scales 0,100,1000 \
  --measurement-label quiet-baseline
```

Use `--checkout /path/to/other/checkout` with the **same harness file and Python
interpreter** for a candidate or fixed baseline. Run baseline and candidate
serially while unrelated builds/tests are paused. Keep all output samples,
including slow ones. The label records operator conditions, not an automatic
claim that the host was idle. The output records the harness digest, Git commit
and tree, dirty-source flag, dependencies, environment, and timing interval.

The script rejects checkouts containing known legacy private input paths, uses
owned temporary storage, removes inherited provider credentials/overrides, and
blocks Python TCP/DNS operations. It permits local Unix socket-pair operations
needed by the event loop. This is an offline guard, not a sandbox against native
libraries or arbitrary subprocesses; the selected local routes do not launch
provider jobs. It is intended for the Linux benchmark environment. The harness
has not been qualified for Windows Proactor internal TCP socket-pairs.

## What is measured

- Fresh Python process imports the entire application: wall time, process CPU,
  and post-import peak RSS. This is not cold OS page cache.
- Actual application lifespan entry and exit: public budget setup/shutdown,
  official in-process MCP session management, registry persistence/recovery,
  and portfolio scheduler initialization. Existing test flags disable automatic
  Native Intel fetching and its recurring scheduler. The portfolio sleeper is
  not stubbed, but its 30-minute refresh is outside the measurement window.
- In-process HTTPX ASGI requests execute real FastAPI routing, middleware,
  validation, local databases, and response serialization. They do not bind a
  network socket or measure Uvicorn/TCP, browser work, or external services.
- Eleven GET paths plus one invalid-input GET are interleaved at concurrency 1.
  The first request is separate from repeated warm observations; it occurs after
  app lifespan entry and synthetic fixture insertion, not before startup.
- Campaign scales are 0, 100, and 1,000 rows by default, created through the real
  service in owned temporary data. Other stores are initialized/empty. Output
  includes bytes and exact success/invalid-input statuses. Empty Native Intel
  remains unavailable, not falsely upgraded to normal market data.
- Every sample is retained. P50 uses the median and P95 the nearest-rank method.
  Low sample sizes are exploratory; seven startup trials have limited tail
  precision. Peak RSS is process high-water, not retained heap or a leak test.
- Linux `/proc/self/io` deltas cover the whole request sequence, not per-endpoint
  physical disk latency. Temporary fixture cleanup is not timed as lifespan exit.

Run harness unit checks with:

```sh
python -m unittest discover -s tools/performance -p test_local_api_baseline.py
```

## Deliberately separate evidence

Do not use these figures as first useful market result, full refresh duration,
provider/network/model latency, browser FCP/INP, React rendering, IndexedDB,
real-machine Windows startup, or sustained background resource measurements.
Those require their own matching data, environment and harness. Do not compare
cloud Node 24 runs to CI Node 22 as if they were a controlled before/after pair.

## One opt-in public market refresh

`probe_market_refresh.py --allow-live-public --output fresh-output.json` runs
exactly one isolated refresh with the existing source budget, cooldown and
integrity checks. It is not a load test. Never reset its temporary source state
to evade a cooldown or repeatedly launch it after an access failure.

The v2 events retain only hostnames, allowlisted endpoint identity, numeric
page/size/total/row/unique-identity counts, HTTP status and exception types.
Failure diagnostics contain at most 16 exception nodes, allowlisted type names,
bounded integer errno values and fixed observation categories (unknown stays
unknown), never exception text. Categories are not proven root causes and are
not retroactively added to older probe evidence.
They never retain query strings, credentials, stock identifiers or payloads.
Repeated responses count toward raw observations but do not inflate observed
unique identities. Counts are diagnostic evidence, **not certified coverage**:
only the unchanged production validator determines whether the snapshot is valid.
Diagnostic parsing time is separate from network wall time; both remain part of
the instrumented end-to-end run. Platform and Python version are recorded rather
than hardcoding a cloud execution label on Windows.

The probe does not override application routing or OS network policy. Stop on
an access restriction; a failed cloud connection does not prove that the provider
is down or that a Windows connection will fail. Offline regression checks run in
the backend suite (`backend/tests/test_market_probe_diagnostics.py`).
