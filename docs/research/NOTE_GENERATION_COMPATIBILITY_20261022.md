# Saved generation snapshots (2026-10-22)

New daily-review saves optionally include `generation` (`note-generation.v1`) independently of the unchanged six-digit-security `research` metadata. The source result body must be nonempty and exactly match the displayed/saved body; streaming fallback or a mismatching restored result saves body only and discloses the missing basis. No synthetic stock code, result ID, generation date, model, or historical coverage is filled in.

The result type/schema/trade date/original generation time and model are identity clues, not a globally unique server ID. The unchanged saved body and, when available, original validated input-basis SHA-256/coverage are retained. The input hash identifies the model context, not proof of the output's truth. Source cutoff may remain unknown. `ts` remains save time. Snapshots never resolve to a newer result; the UI explicitly states that the original may have been replaced/deleted and availability has not been checked.

Generation is limited to 8192 JSON characters with allowlisted fields, bounded strings, exact version and validated coverage. New metadata corruption fails closed, leaves original localStorage bytes available through the existing raw-data download/recovery flow, and blocks write operations instead of silently dropping a record.

## Compatibility and rollback

- No generation fields: export the existing `vibe-notes.backup.v1` format. Existing research notes remain unchanged.
- Any generation field: export `vibe-notes.backup.v2`; the new reader accepts both versions. A v1 file carrying generation is rejected, not silently downgraded.
- Old clients reject v2 backup imports. However, old clients opening the same `vr-notes` storage can discard the optional generation fields when rewriting/exporting records. There is **no lossless old-client round trip guarantee**.
- Before rollback, export and preserve a complete v2 backup with this version. Keep a separate copy outside browser storage. Do not use an old client's export as a replacement. Restore with a generation-aware client. Do not manually relabel v2 as v1.
- Existing duplicate-ID merge policy remains first existing record wins; 200-note limit and no-eviction behavior remain unchanged. A corrupt new field does not authorize replacement; existing explicit corrupted-data recovery still applies.

## Synthetic verification

`node --experimental-strip-types --test tests/note-generation.test.ts tests/notesBackup.test.ts tests/note-generation-ui.test.mjs` covers unchanged bodies, old/new/mixed backup round trips, duplicate IDs, v1 downgrade rejection, corrupt metadata byte preservation, limits, quota and retry, and exact-content binding. `npm run test:e2e:notes-backup` additionally invokes `note-generation.fixture.mjs` for 1440px/390px display, download and clean import; optional `NOTE_GENERATION_EVIDENCE_DIR` saves screenshots. This is isolated synthetic validation, not actual source/model, deployment, or natural next-day acceptance.
