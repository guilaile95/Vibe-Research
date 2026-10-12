# Codex subscription login classification

Date: 2026-10-11. Scope: Simon adoption matrix item 27, after the accepted SDK event guard. Reference: [fixed upstream classifier](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/orchestrator/src/local_agent_runtime.ts).

## Public contract

Existing `runtime`, `installed`, `authenticated`, `available`, `status`, and `version` fields remain. `authenticated` means eligible subscription authentication, not any CLI credential. Additive fields are optional for older-server compatibility:

- `auth_kind`: `chatgpt`, `api_key`, `logged_out`, or `unknown`
- `probe_error`: `null`, `timeout`, `not_found`, `malformed_output`, `nonzero_exit`, or `process_error`
- `status` adds `probe_failed`

Only an explicit ChatGPT conclusion with successful exit is ready/available. API-key authentication is unavailable for the subscription path, with `not_authenticated` plus `auth_kind=api_key` and a specific explanation. There is no automatic API-provider fallback. Only the exact logout conclusion with exit 1 is logged out. Conflicting, empty, unrecognized, or wrong-exit output does not prove authentication or logout.

ENOENT is `runtime_unavailable/not_found`; other failed probes are `probe_failed/unknown`. Existing `login_pending` and `login_failed` lifecycle states remain for explicit logout results. A failed detector never clears or changes login state. Safe public enums and fixed messages replace raw process output and exceptions. Version output must match a bounded CLI version label; no account details or stderr are returned.

`installed=false` after an outer HTTP timeout remains a conservative legacy Boolean, not evidence that the binary is absent. Consumers must use `status`, `auth_kind`, and `probe_error` to distinguish unknown from not installed/not authenticated.

## Source-to-sink

The runtime classifies stub-injectable bounded process results, gates chat before SDK/session creation, and exposes status through the existing endpoint. The backend preserves only the allowlisted additive fields, handles HTTP timeout as unknown, and rejects unready Codex requests without switching providers. Settings renders API-key login and detection failure separately from logout. Older payloads without the new fields retain their previous display.

Dedicated CODEX_HOME, environment filtering, pinned SDK, login flow, tool isolation and the accepted event guard are unchanged. No new provider, credentials, persistent access or security configuration is introduced.

## Timing and remaining limitation

Preserve existing 8-second per-process CLI startup tolerance and 4-second backend HTTP budget. Each subprocess now has a 64-KiB output limit and SIGKILL timeout signal. The outer HTTP request can time out before the runtime returns; that outcome is unknown with a safe timeout reason, not the inner CLI's eventual classification. Stub tests separately cover both layers. No actual subprocess teardown or CLI login was exercised.

The existing synchronous runtime probe may take up to two 8-second windows; the backend timeout does not cancel it. Existing Settings polling while login is pending is every 1.5 seconds and may overlap requests. This change adds no retry, no polling frequency increase and no process concurrency. A detection failure stops the pending-only polling state. Deduplication/cancellation redesign is outside this classification change and remains a known architectural limitation.

## Verification

- 58 focused Node tests: process-result stubs plus accepted event-guard regressions
- 25 focused backend API/projection/readiness tests, including inner and outer timeout layers
- 8 tests evaluate the exact Settings JSX label expression, including legacy payloads
- Frontend production build passed

These are synthetic/source-level checks, not real account authentication, browser acceptance or real CLI/model execution. The full runtime suite was intentionally not run because an existing MCP configuration test invokes the real CLI. Exact-commit CI and independent review remain separate acceptance gates.
