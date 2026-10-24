# Report search and pre-model context performance — 2026-10-24

## Scope and mechanism

Baseline: `c16ade49174a26597de05244ac9f70d2855c590a`. These measurements are from an isolated Linux cloud workspace, Python 3.11.16 / Node 24.19.0, **not the user's target computer**. No live provider, model, credentials or user documents were used.

A scoped report search previously opened one private immutable SQLite image to qualify sources and another image to search indexed chunks. Pre-model report-context construction likewise opened separate images for source eligibility and exact chunk revalidation. Each image performs four bounded full-index byte reads, including its final unchanged check. A query scoped to one report therefore still paid for eight reads of the entire shared text index.

The change reuses one image **within each operation only**. Search and later context construction still open separate fresh images. Source SHA-256, SQLite schema, selected-report scope, exact chunk digest/snippet, OCR provenance, result ordering, evidence budgets and final byte/identity verification remain. There is no persistent cache, schema migration, larger budget or freshness relaxation. Mutation during a combined operation fails closed rather than exposing a mixed-generation result.

## Controlled measurements

The same harness generated one selected text document and an unrelated indexed text payload of 1, 8 or 32 MiB. Actual SQLite sizes were 1,114,112 / 8,638,464 / 34,435,072 bytes. Every operation returned an identical result digest across baseline and candidate at all sizes.

Each series contains 25 measured repetitions after one warm-up. Order was baseline A → candidate → baseline B for search, then the same order for context. Other task benchmark/test lanes were paused for this final timing window. Host-level scheduling and filesystem page-cache effects remain possible; both baseline series and all samples are retained, not just the fastest result.

Warm filesystem cache, milliseconds (P50 / P95):

| Operation / payload | Baseline A | Candidate | Baseline B |
| --- | ---: | ---: | ---: |
| Scoped search / 1 MiB | 5.92 / 6.85 | 2.67 / 2.96 | 6.22 / 7.00 |
| Scoped search / 8 MiB | 50.42 / 55.57 | 23.33 / 25.55 | 56.17 / 62.07 |
| Scoped search / 32 MiB | 244.47 / 257.46 | 128.88 / 145.45 | 252.54 / 266.33 |
| Context build / 1 MiB | 5.64 / 7.28 | 2.79 / 3.17 | 5.54 / 6.19 |
| Context build / 8 MiB | 49.58 / 58.03 | 23.77 / 27.88 | 48.29 / 72.38 |
| Context build / 32 MiB | 240.47 / 255.15 | 122.42 / 128.88 | 260.18 / 274.87 |

At the largest fixture, logical index bytes read per operation fell exactly from 275,480,576 to 137,740,288, and private image constructions from two to one. These are application read bytes, **not physical disk I/O**; no peak-memory reduction is claimed. The entire 64 MiB read limit and safe immutable-image boundary remain unchanged.

Raw samples, CPU samples, exact data sizes and digests are in [performance-20261024/](performance-20261024/), in `search-{baseline-a,candidate,baseline-b}.json` and `context-{baseline-a,candidate,baseline-b}.json`.

## Runtime baseline and deliberately omitted optimizations

[Runtime raw evidence](performance-20261024/runtime-status-final.json) uses actual Node subprocesses returning controlled CLI text. It does **not** measure the real Codex CLI, subscription authentication, model latency or model quality.

- Cold status, 25 samples: P50 57.03 ms, P95 68.74 ms; two subprocesses/sample.
- Warm status, 100 samples: P50 0.000891 ms, P95 0.001111 ms; zero subprocesses.
- Cold burst of 20 concurrent status callers, 25 samples: P50 59.76 ms, P95 66.74 ms; still two subprocesses/burst, not 40.

The existing bounded asynchronous probes, two-second cache and singleflight already remove repeated probe work. No Runtime change, looser concurrency limit, additional model call or stale-auth cache was justified.

An exploratory profile also found repeated in-memory Campaign DDL constraint probes taking about 0.46 ms/read under profiling. This alone did not justify a new semantic-proof cache. It was **not changed**, and no end-user speedup is claimed for it. Existing Fact Lake expected-schema fingerprint caching was retained rather than reimplemented.

## Reproduction

Use the same candidate harness against each checkout with that checkout's dependencies available:

```sh
python tools/performance/benchmark_report_search.py --repo /path/to/baseline --operation search --repeats 25 --output baseline-search.json
python tools/performance/benchmark_report_search.py --operation search --repeats 25 --output candidate-search.json
python tools/performance/benchmark_report_search.py --repo /path/to/baseline --operation context --repeats 25 --output baseline-context.json
python tools/performance/benchmark_report_search.py --operation context --repeats 25 --output candidate-context.json
node tools/performance/benchmark_runtime_status.mjs
```

The Python harness creates a disposable synthetic catalog, strips inherited application/provider configuration with the existing validation policy, and never invokes extraction or an external service. It checks identical output on every repetition. The Node harness uses an isolated synthetic home and a model factory that throws if called.

## Verification boundary

Target-machine cold-disk latency, production-scale document distributions, actual provider/model startup and real-user end-to-end interaction remain unverified by these isolated measurements. This patch does not alter deployment or user data. Ordinary source reversion is the rollback; no data migration is needed.

## Focused correctness gate

Final candidate: **149 tests passed, 6 subtests passed** across the new snapshot-reuse tests and existing fulltext, hit freshness, page read/chat, corruption, evidence-quality and archive-journey suites. New coverage explicitly checks one image per operation, no cross-operation reuse, changed extraction rejection, unchanged supplied-hit identity, parser-error/empty-result cleanup, missing-source handling, pending-WAL rejection and mid-operation index mutation rejection. `git diff --check` passed.

The first test draft incorrectly assumed a one-character literal query was invalid; the production contract allows it. That test was corrected to inject a parser failure specifically to verify connection cleanup; no production query rule was relaxed or test removed. The final gate above includes the corrected test.

[Measurement manifest](performance-20261024/measurement-manifest.json) records the exact measured candidate source/harness SHA-256 values and raw-file hashes. Candidate code was measured before committing; integration must match these source bytes. Full stable CI and merged SHA are integration-level gates, not implied by this focused result.
