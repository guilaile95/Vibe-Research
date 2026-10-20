# Local credential generation protocol

This is a concurrency barrier, not a credential, permission grant, authentication mechanism, or provider-key revocation mechanism.

- One backend writer process is required (the supported launchers use one Uvicorn worker). The in-process lock is not a cross-process/distributed lock.
- Missing files and valid v1 records are read-only generation `0`. Reads/startup never migrate. Explicit save or clear writes v2. Unknown/corrupt state has no usable revision and cannot be overwritten by this API.
- Revisions are canonical ASCII decimal strings in the API, integers in the file, from 0 through 9223372036854775807. Mutation at the maximum fails closed. Generation is nonsecret.
- PUT requires `expectedRevision` equal to the current generation. Conflict is 409; missing old-client field is 422. Never retry an unknown/conflicting save using a newly fetched generation without another explicit save intent.
- DELETE requires `observedRevision`. Any observation from 0 through current is accepted as a clear barrier; future observations are rejected. Every clear increments the generation and atomically replaces the file with a nonsecret tombstone. It never unlinks the file or resets generation. No API key, provider, model or base URL remains in a tombstone.
- Every mutation computes its status from the same locked snapshot. v1 scheduled reads remain compatible. Old code must not be used to mutate v2 state during rollback: unknown v2 should remain unavailable, and old key files must not be restored as a recovery shortcut.
- The new frontend freezes a previously observed revision synchronously at save intent (never obtains a newer generation from a delayed initial GET), queues mutation intents across component unmounts, bounds HTTP waits to 10 seconds each, invalidates old save completions immediately on clear intent, checks mutation readback, and validates the stored generation before actual model submissions through both shared JSON/NDJSON transports. Explicit unsaved connection tests remain a separate opt-in draft operation.
- Refresh all old tabs when deploying this protocol. New clients reject old browser configs without a generation until explicitly saved again. This does not recall a provider key already copied elsewhere, cancel a model call already admitted, or authenticate an untrusted local client.
- Web Storage is not a transactional cross-tab store. A racing stale tab can physically rewrite localStorage after another tab clears it; new clients cannot use that stale generation for a new submission. This is not a claim that all browser copies are atomically erased. A storage-denied browser receives an explicit error rather than a success claim.

No real provider, API key, account, or user database is needed for the regression tests. Use the isolated test launcher and synthetic browser fixtures.
