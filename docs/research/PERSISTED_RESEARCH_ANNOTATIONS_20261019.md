# Persisted research annotations — bounded implementation

## User workflow

In Stock Data, open daily K-lines, select an exact bar with the existing mouse or keyboard inspector, and open **手工研究标注**. Enter a note (1–2000 nonblank characters), optionally a finite reference price and an existing same-stock Evidence or Thesis ID, then explicitly append-save. The table rereads server storage after save. A failure retains the input and asks the user to read back before retrying.

Notes are independent research material, never formal thesis edits, evidence creation, decisions or trades. Saves are append-only; no update/delete API or controls are provided. The existing facts SQLite domain database stores up to 1000 records globally. Reads do not create a database or mutate its bytes. Existing and differing notes are retained.

## Context and version boundaries

- The existing `/api/kline` default response remains unchanged. Opt-in `annotation_context=true` enriches the envelope alongside the same data array, using the single existing source read. No extra provider request is made.
- Server-generated context covers code, daily period, the normalized last 60 valid bars and their content hash. Conflicting duplicate dates make context unavailable. The client checks the exact normalized bar content before exposing save and keeps metadata in a WeakMap attached to the exact array, not localStorage.
- A process-local HMAC research receipt expires after one hour or server restart. It is a data attestation, not an authentication grant. The user must reload bars after expiry/restart. Saved annotations remain readable and their stable content identities remain comparable. Multi-worker routing may reject a receipt minted by another process; deployments should use the existing single-process local runtime for this flow.
- Save requires an exact date present in that receipt. A different code, changed content, period or missing date cannot silently fall onto another candle. Archived notes with a different content hash or absent date remain in the table marked **unmapped**.
- Evidence links require a live, nondeleted same-stock record; its `updated_at` is captured. Thesis links require an existing same-stock record and capture its current revision. Links open the current record and explicitly label the captured version. Linking does not upgrade source authority or modify the linked record.
- Text renders as escaped React text; neither annotation text nor source IDs are HTML or executable instructions.

## Verification scope

Offline API/unit checks cover append/read/restart, bounded input, nonfinite prices, forged/expired receipts, exact-date binding, conflict duplicates, same-stock/version references, corruption fail-closed, read-only reads, and absence of edit/delete routes. Component hook-harness checks cover explicit save/readback, duplicate clicks, escaped text, selection changes, late results/unmount, missing context and retained input on failure. Existing chart inspection/event tests are regression coverage.

Production frontend TypeScript/Vite build is checked separately. Browser/OS runtime acceptance is **not evaluated**: the known browser launch denial was not retried. These checks do not establish real provider reliability, sustained adoption or actual trading outcomes. No external model/provider test calls, credentials, push, PR, merge or deployment belong to this implementation.
