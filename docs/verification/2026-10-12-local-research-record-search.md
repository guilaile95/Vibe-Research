# Local research record browsing (A37)

Notes now filters all existing local record kinds and searches saved title, body,
kind and optional research question/security fields as literal text. Type, text
and security filters intersect. Queries remain in component memory, never in a
network request or model context. Existing note backup/recovery/deletion and old
optional research metadata are unchanged. More than120 query characters or4million
candidate text characters produces an explicit refusal to search, not truncated
matches. Filtering never rewrites saved notes.

Company research and debate already have explicit local save actions. The research
calculation page now explicitly saves its validated result, exact input fingerprint,
mode and captured synthetic flag to the same browser notes. Raw input is excluded.
The saved result may include private ledger-derived rows: it remains browser-local,
is not included in public share cards or automatic market AI context, and the UI
must not imply public data. Subsequent editing invalidates the current result.
A synchronous per-mode/fingerprint guard prevents repeated same-render saves and
releases on storage failure for an explicit retry. Results above1MiB are refused.

This is a view of explicitly saved records, not an invented complete run history.
The note preserves result status and research limitations; saving does not promote
calculation output or model text to verified fact. No new model call or collection.

Focused verification:31 pure contract/existing backup-recovery/production JSX tests
pass; TypeScript and production build pass. Actual desktop/mobile browser remains
for cumulative CI. No local browser or live provider/model was run.
