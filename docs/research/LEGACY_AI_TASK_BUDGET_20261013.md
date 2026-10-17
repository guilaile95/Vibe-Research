# Legacy Daily Review and Debate model budgets

Originally implemented on 2026-10-13; this recovery record was reconstructed on
2026-10-16 against merged base f64de28471f96b3b288b698b0d93365fc8ac992e.
The original complete document and backend test bytes were unavailable after
workspace loss. Production edits were replayed from retained implementation
blocks against verified preimages. This document and backend tests were
reconstructed from the original contract. Historical pass counts are not
validation of this candidate.

## Scope

Only the legacy Daily Review analysis route and Debate model stages opt into
a fresh, server-owned ModelTaskBudget. Ordinary chat, the async API streaming
transport, and connection-test defaults keep their existing behavior.

| Task | Model-phase local wait | API requests / CLI runtime invocations | API max_tokens per request | Local output characters |
| --- | --- | --- | --- | --- |
| Daily Review | 90 seconds | 1 | 2500 | 12000 |
| Debate, one round | 180 seconds shared | 3 | 2500 | 36000 |
| Debate, two rounds | 180 seconds shared | 5 | 2500 | 60000 |

Daily Review data preparation and Debate dossier collection precede the model
budget and are not covered by it. The selected model stages use no tools.
The optional tool path shares dispatch and output limits, including tool
continuations and final synthesis; executing a provider tool is not given a
hard process deadline by this patch.

## Failure and ownership contract

A monotonic deadline, atomic dispatch reservations, and cumulative output
counter are shared across the task. API max_tokens is supplied on every actual
request; the local output count includes content and tool-call identifiers,
names, and argument fragments. The counter rejects an overflowing fragment
before forwarding it. There are no hidden retries.

The consumer checks cancellation/deadline while a synchronous worker may be
blocked preparing a request, waiting for headers, reading, or cleaning up.
A per-process pool admits at most four such tasks. Admission remains occupied
until the actual generator and cleanup watchers exit, even after the consumer
has stopped. Repeated timeouts cannot create unbounded admitted orphan workers.
A stuck request can occupy a slot indefinitely. This is not a hard worker
lifetime bound, a global cross-process quota, or a guarantee that DNS/socket
close returns.

Active API responses are closed on cancellation when available. The CLI adapter
requests cancellation for the owned session and closes its active response.
Cleanup ownership is retained until those operations return. Remote model
termination is not guaranteed, and cleanup may outlast the local wait budget.

Completion is buffered until clean iterator EOF and requires nonempty answer
text. Deadline/cancel/cap failure produces an error without a valid complete
result. No later stage or tool may start after the relevant check fails.
Debate checks again after the final referee stage_done before aggregate done.
Daily Review checks before saving and supplies a cancellation/deadline predicate
to the save transaction. Partial output is not saved as a complete result.

## Cost interpretation

API request counts and per-request max_tokens bound parameters supplied by
this application; they do not measure provider usage or invoice totals.
Prompt/input costs are not capped by the output budget. CLI counts runtime
invocations and locally received output only. It cannot enforce or verify hosted
model calls, tokens, or subscription cost. Unknown cost does not mean free.

The common notice renders Daily Review and both Debate depths before action,
distinguishes preparation from the model phase and API requests from CLI
invocations, and states cancellation and cost limits.

## Validation status for the recovered candidate

All Python execution, frontend tests, production build, live model/provider
checks, and runtime acceptance are PENDING / NOT_EVALUATED on 2026-10-16 because
the execution environment is unavailable. Connector-only anchor checks, Git
blob verification, and source inspection are not runtime passes.

Required offline regressions include held request preparation/headers/read/close
and CLI cancellation cleanup saturation; shared deadlines across stages and
the final referee boundary; atomic dispatch exhaustion; tool continuations;
local output overflow; cancellation before tools; late, missing, duplicate or
empty terminal output; independent task budgets; and no Daily Review save after
failure. Existing transport and Daily Review suites must also pass under the
network guard. Tests that intentionally create local HTTP fixtures need an exact
fixture-owned ephemeral-port allowlist, without provider access.

Reconstructed tests are supplied for fresh execution and independent review.
A Draft preservation branch is not approval to merge or deploy.
