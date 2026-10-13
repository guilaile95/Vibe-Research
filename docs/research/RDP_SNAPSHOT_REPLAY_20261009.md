# Reopen research with the same imported dataset

Implementation and offline acceptance record: 2026-10-09. This backend-only slice
lets a saved query use generation A after a newer CSV import publishes generation B.
It does not establish that A was publicly available at the historical query date.

## Use the saved receipt

Existing queries still default to the current imported dataset. Successful queries
now include `snapshot_id`, `replay_receipt`, and `next_page`. Save the receipt with
your research result; preserve the RDP directory's `snapshots/` and `artifacts/`.
A receipt alone is not a backup of the dataset.

- `GET /api/research-data/daily-bars`, `/full-market`, `/patterns`, and `/manifest`
  accept optional `snapshot_id=<64 lowercase hex characters>`
- `POST /api/signals/factor-validation/evaluate` accepts the same optional field
- Factor evaluation resolves one generation at run start and passes that identity
  through every date and page; existing artifact/provenance mismatch guards remain
- Keep the original filters, dates and page size when paginating, and pass the
  returned `next_page.offset` and `next_page.snapshot_id`. A page receipt hashes
  that bounded page, not all possible results or another page size

Python example, using a receipt returned by `query_full_market`:

```python
import research_data_plane as rdp

result = rdp.query_full_market(root=data_root, as_of="2026-08-21", latest=False)
saved = result["replay_receipt"]
# Later, including after another import:
replayed = rdp.query_full_market(
    root=data_root, snapshot_id=saved["snapshot_id"], **saved["parameters"]
)
assert replayed["replay_receipt"] == saved
```

The receipt identifies the query and engine contract, normalized effective query
parameters (including a defaulted `as_of`), snapshot metadata digest, artifact
SHA-256, and deterministic response-content digest. Full Market receipts use the
Python `filters` list even for the legacy single-filter inputs; HTTP clients can
keep their original HTTP parameters and the resolved `as_of` from the receipt.
Factor receipts normalize omitted date bounds while preserving the original
request display in the response.

`rdp-replay.v1` defines the current execution contract. Canonical JSON uses sorted
object keys, UTF-8, compact separators and finite numbers. Content digests exclude
response `fetched_at`, `generated_at`, and the redundant `requested_as_of`; factor
request/sample date bounds are normalized. Identity, continuation and receipt
fields added by the receipt builder are outside the content digest. Array/row
order is retained because it is part of the result. Bump the engine contract when
query, factor, normalization or digest semantics change. A new engine/dependency
version is not a promise of identical results across versions.

## Storage, failures and legacy data

A snapshot ID hashes canonical manifest content, including import/source metadata,
not just Parquet bytes. Identical artifacts with different metadata have separate
IDs without duplicate Parquet files. Identical content and metadata reuse an ID.
The archive stores plain JSON; no executable restore format or new service is used.

Import validates artifact hash, metadata, counts and coverage before publishing.
A complete immutable snapshot is atomically linked into its final name before the
atomic current-manifest replacement. Interrupted publication can leave an unused
valid snapshot or artifact; it cannot silently replace the previous current
manifest with partial JSON. Referenced artifacts are never deleted during import
rollback. POSIX files/directories are flushed; Windows relies on atomic filesystem
link/replace and has no portable directory-fsync guarantee. This is not a guarantee
against hardware failure, external file tampering, or unsupported filesystems.

A pre-existing current manifest is fully validated and archived on first current
read or before a new import. An unwritable archive fails explicitly; it does not
pretend the result is replayable. Invalid legacy metadata blocks publication until
repaired. Metadata for older orphan artifacts is never fabricated. Already archived
pinned reads need no current manifest and do not create an archive.

Unknown IDs, malformed selectors, missing archives, corrupted snapshot metadata,
missing artifacts and artifact-hash drift fail closed. There is no fallback to the
current dataset. HTTP routes preserve their existing unavailable/422 behavior;
a failure without verified data has no successful replay receipt.

## Run the offline demonstration

With the project's backend dependencies installed, from repository root:

```bash
python tools/research/rdp_snapshot_replay_demo.py
```

The script uses synthetic CSV data in a temporary directory, imports a close of
12, then a historical correction to 14. The current query returns 14; replaying A
returns 12 with the identical receipt. It makes no network/provider/model calls.
The temporary data is removed on exit; the portable demonstration output is
[the saved JSON receipt](RDP_SNAPSHOT_REPLAY_DEMO_20261009.json). This is an example
artifact, not a selectable snapshot in a user's real dataset.

Regression cases are in
[`test_research_snapshot_replay.py`](../../backend/tests/test_research_snapshot_replay.py).
They cover two-generation replay on all three queries, normalized dates and clock
independence, bounded pagination, metadata-only generation changes, corrupt/missing
inputs, legacy migration failure, interrupted publication, factor reimport between
pages/dates and retained provenance guards. Existing RDP/factor and downstream
consumer regressions are also run; exact counts belong to the delivery report.

## Evidence limits

`historical_public_availability=NOT_PROVEN`, unknown licensing and unadjusted-price
limitations remain. Import time and trade date never become publication-time
Evidence. This adds no provider, automatic historical-knowledge selection,
survivorship-free universe, new factor, trading action, UI history screen or
profitability claim. Offline synthetic checks do not establish real-market or
model quality or natural Product Reality.
