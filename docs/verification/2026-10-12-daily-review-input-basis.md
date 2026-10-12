# Daily review generation input basis

## Contract

The analyze endpoint captures one bounded metadata snapshot from the exact UTF-8
`context_json` returned by `prepare_daily_review_analysis`, before starting the
existing model stream. The prompt builder embeds this string without rewriting it.
There is no second review generation or fetch when saving or restoring a result.
Save identity is detached from the potentially mutable review object.

New endpoint results use `daily_review_ai.v2`. The basis records context/review
schema identifiers, source trade date and timestamps, overall status, the eight
known component statuses, warning/unknown counts, omitted component-name count,
and SHA-256 of the context string. Unknown status maps to `unknown`. Arbitrary
warning text, unknown text, provider error strings, component names, full context,
model credentials and prompts are not persisted in this basis. No provider IDs
are fabricated: this input projection does not contain a provider evidence chain.

Limits: input context 2 MiB, depth 32, basis 4 KiB, schema token 64 characters,
timestamps 64 characters, nonnegative counts at most 10,000. Duplicate JSON keys,
non-finite JSON values, incompatible identities, unknown basis keys and malformed
persisted v2 records fail closed. A malformed basis does not overwrite an older
saved result. Invalid preparation fails before model execution.

The context hash is an identity, not a proof of completeness, provider provenance,
PIT authority or truth. It does not cover the full prompt or user request. This
feature does not change prompts, model configuration, generation semantics or any
account/frozen-decision authority.

## Compatibility and interface

Existing `daily_review_ai.v1` records retain the exact original field contract and
remain readable. They are not rewritten, backfilled or upgraded. The UI explicitly
says their historical component/gap snapshot was not saved. v2 has a separate exact
payload contract; invalid/missing v2 basis never falls back to v1.

The existing transaction date, model and data-cutoff labels are retained. A new
read-only disclosure compares the current page date/cutoff with the saved result,
shows captured component states/counts and warns that current data cannot supply
missing historical evidence. The done-result selector accepts both supported
versions so generation can restore the committed result normally.

## Verification boundary

Focused synthetic tests cover strict restore, malformed/oversized input,
unchanged historical v1, API preparation-before-model, mutation of current review
after preparation, actual temporary-store v2 save/restore, no overwrite on invalid
basis, and production JSX rendering. Browser/real-model/live-market acceptance is
separate; these tests do not make those claims.
