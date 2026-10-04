# Research evidence and cancellation fixes — 2026-10-02

## Version and scope

Baseline: PR356 head `15804a72a2d6da69e8f40048003ad58f8a58909b`, tree `7dc2802b38555f83deffb8c3d3dd06e91c423d9b`. Both were reconstructed and verified exactly from the connected GitHub API, including 129 locally missing blobs. The stable branch was separately confirmed at `aab09365f5bb18699268aafe7ff333e84c71c87d`.

This changes three confirmed research defects. It contains no new desktop packaging, installation, trading, deployment or stable-runtime switch. Existing original-workspace modifications were preserved, with a local byte-verified backup of 16 tracked modifications and 23 visible untracked files. The isolated development copy is updated; the original dirty workspace remains on its previous branch/head.

## Changes

1. **K-line adjustment and provenance.** AI K-line statistics require Tencent's explicit `qfq` series key. Raw-only or empty adjusted series fail closed; the AI tool no longer substitutes the general unadjusted `astock.kline` route. Successful output states source, adjustment, fallback policy, retrieval time and latest bar date. Retrieval time does not claim a current market observation. General callers retain their existing unadjusted contract. This deliberately reduces availability when adjusted data cannot be proved, including unsupported BSE adjusted history. Chat and debate metadata handling must also preserve an unavailable result as an error rather than partial observations.
2. **Financial zero values.** Numeric `0`, `0.0` and provider string `"0"` are retained; booleans, `None`, the existing missing strings and nonfinite values remain separate. The fix covers both financial summary and health-statement normalization, preserving the existing string/numeric and invalid-value contracts.
3. **Portfolio advice cancellation.** The JSON route reads ASGI disconnect events while generation runs in a worker, propagating one event through the model configuration and service. Result persistence receives `should_cancel`; both decision-evidence and signal-ledger transactions check cancellation before commit and roll back uncommitted writes. Cancellation does not become a failed-evidence archive. A cancelled generation cannot replace the prior completed result in the tested precommit cases; successful retries still persist and restore.

## Independent verification on the local Windows computer

All fixtures used synthetic prices, model outputs, account/holding records and temporary databases. No real provider, user credential, user portfolio or external paid-model request was used.

| Verification | Result and actual boundary |
| --- | --- |
| Production frontend TypeScript + Vite build | Passed; Node 26.8.2 and reused installed dependencies. Existing chart chunk warning remains. This is not a fresh dependency-install or Node 22 CI claim. |
| Complete frontend unit-test command | 835 passed; one test file was blocked by sandbox esbuild directory access. Its two tests passed when rerun with approved process permissions: 837 logical tests verified across the two runs. |
| Same exact financial function before/after probe | Ten input cases verified independently: zero/zero string preserved; booleans/null/missing/nonfinite handled distinctly. Synthetic provider frame, no network. |
| Real Uvicorn + loopback TCP, five cases | Initial success; cancellation during model twice; cancellation immediately before SQLite write; successful retry. All three cancelled cases actually delivered `http.disconnect` to the application, preserved `completed-initial`, and made no archive calls. Retry returned 200 and persisted `completed-retry`. Preparation/model/validator/archive adapters were synthetic; the route, generator and SQLite store were real. |
| Independent transaction probe, five cases | Real SQLite INSERT-triggered cancellation: old AI-result row retained; decision-evidence and signal-ledger new/overwrite transactions rolled back; all five archive tables unchanged; no failed trace. |
| Actual rendered Chromium + same-origin Uvicorn | Production built portfolio UI, route, generator, validator, result storage and archives; synthetic model/prices and temporary ledger. Two UI cancellations delivered real disconnects. Reload restored the prior completed result; retry and subsequent reload restored the new result. Zero page exceptions. At 390px viewport, document width was 390px and the visible retry button remained enabled. |

The pre-fix exact-PR356 TCP experiment reproduced the opposite behavior: all three interrupted cases overwrote the prior result and invoked both archives, while the application never read `http.disconnect`. Screenshots and JSON logs for the independent experiments are retained in the local task evidence directory; they contain synthetic data.

The committed backend regression tests exercise the real ASGI disconnect channel and real result restore, repeated cancellations, model/before-save/inside-save stages, financial boundaries, K-line contracts and error-envelope integration. The focused suite passed **283 tests in 17 files** (9.46 seconds); independent final review approved the patch without blocking findings. The later explicit debate-section assertion passed alongside the chat/K-line subset (65 tests). These runs use the existing project Python 3.12 environment and no live providers.

After preparing the isolated checkout's Python 3.12 environment, run from its `backend` directory:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_tencent_kline_contract.py tests/test_ai_tools_bse_kline.py tests/test_astock_financial_health.py tests/test_financials_api.py tests/test_critical_data_financials_adapter.py tests/test_portfolio_advice_cancellation.py tests/test_portfolio_advice_api.py tests/test_portfolio_advice_service.py tests/test_portfolio_advice_error_mapping.py tests/test_portfolio_advice_architecture.py tests/test_ai_result_store.py tests/test_ai_result_service.py tests/test_decision_trace_store.py tests/test_decision_evidence_service.py tests/test_signal_ledger_store.py tests/test_signal_ledger_service.py tests/test_chat_grounding.py -q -p no:cacheprovider
```

## Cancellation guarantee and remaining acceptance

The guarantee starts when the application observes cancellation and applies to writes that have not crossed their final cancellation check/commit boundary. A completed result is not deleted if cancellation arrives after its commit. The two archives are existing independent best-effort transactions; this change does not make three databases one atomic transaction. A callback cannot guarantee that an event arriving after its final check wins over commit.

Closing a local HTTP/model stream cannot guarantee reversal of an external provider's accepted computation or billing. Model preparation and injected runners that do not cooperate may finish their current work before a later gate stops persistence. Real adjusted-provider availability, real model research quality, exact-head remote CI and stable-branch integration remain separate acceptance steps.

Transport semantics reference: [ASGI HTTP disconnect receive event](https://asgi.readthedocs.io/en/latest/specs/www.html#disconnect-receive-event).
