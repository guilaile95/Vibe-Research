# Archived two-session membership navigation

## Scope

The daily review's current and historical dates can read the existing local
v0.2 final fact store and compare stock identities for the official previous
trading session. This is a member table, not the upstream strong-stock feedback
feature in full. It contains no prices, returns, promotion rates, transition
classification, layer-conditioned counts, or trading actions. The frozen
layered-promotion coverage gate is unchanged and remains implementation-disabled.

`GET /api/market/cohort-identity?trade_date=YYYY-MM-DD` accepts exactly one date,
inherits the application's origin/API-key guards, and performs no collection.
The UI binds to the actual page date and rejects stale/foreign-date replies.

## Evidence contract

Both current stored records must be normal/final v0.2 with consistent source,
section, date and time metadata. `ladder.board_semantics` must be explicitly
present, complete, unique by normalized stock identity, and agree exactly with
ladder health and recomputed metrics. The canonical facts limit-up count must
also exactly equal member count. This view rejects even count discrepancies
within the unchanged composer tolerance; it does not alter stored fact status
or imply that the original fact is necessarily wrong. Supported codes have 60/68/00/30 prefixes;
optional SH/SZ suffixes must match and aliases cannot duplicate a member.
Stored derived board semantics are validated; only source continuous `boards`
is displayed. N/M effective height never substitutes for consecutive boards.
Zero-member lists are not admitted: the existing EastMoney contract cannot
prove legal zero, and no Tushare aggregate-only proof is promoted to member
evidence. The prior date comes from the existing offline official calendar, not a
weekday guess or the closest available record. A missing side suppresses the
entire table. Missing membership fields never imply a zero-member pool.

Rows enumerate only the previous list. Presence in today's selected complete
list is an identity lookup, not proof of continuation, profitability or a
tradable result. Absence says only that today's selected list did not contain
the code; today's board count then remains unknown. Input row counts appear
only in evidence details for completeness, never as transition metrics.

Records are the current stored revisions, observed post hoc. SHA256 binds the
normalized envelope read for this response; it is not a raw-response receipt.
Fetched/snapshot/persistence timestamps are shown. No historical PIT claim is
made, including when yesterday's record was persisted after today's session.
Existing v0.1 aggregate-only records cannot supply member identities. Existing
Tushare empty-pool proofs without the explicit membership field are not upgraded.
The feature does not add or activate a producer and does not guarantee that a
user already has eligible stored records. Missing evidence stays unavailable.

## Strict source immutability and shared reader fix

Ordinary SQLite `mode=ro` can create WAL/SHM sidecars on a closed WAL-mode store.
The shared single-date reader and new paired-date reader instead copy a bounded
(maximum 64 MiB), regular, non-symlink DB image without opening source SQLite.
Two bounded reads verify file-descriptor identity, metadata and matching bytes.
Nonempty WAL/rollback journals, symlinked sidecars and detected drift fail closed;
there is no checkpoint or fallback to an older main-file state. Active stores
may therefore report busy until normal writer closure/checkpoint completes.

After SQLite header/page checks, the two journal-mode bytes (18 and 19) in the
private memory image alone are changed from WAL (2,2) to rollback (1,1). This lets
SQLite deserialize a checkpointed WAL image without looking for a journal. All
other bytes and the source file are unchanged; original-file SHA is kept distinct.
Memory-only query-only/trusted-schema-off SQLite validates integrity and reads
both dates from that one captured image. The legacy single-date public return
shape is preserved. This prevents the previously missed sidecar write in the
next-day verification reader as well as the new view.

This protects against detected concurrent changes and preserves a captured
image; it is not a claim of security against a privileged process controlling
filesystem operations. No arbitrary path or as-of selector is accepted over HTTP.

## Verification boundary

Focused tests cover actual default-WAL storage to registered ASGI route, whole
source-directory byte immutability, missing/corrupt/busy/symlink/drifting files,
source schema/coverage/identity/aggregate/time failures, calendar boundaries,
API authentication/origin, and the unchanged promotion gate. Frontend tests
check actual current/history JSX bindings and readback validation. Dedicated
strict browser runtime belongs to the existing authorized CI lane; no local
browser or provider is run. Real production evidence availability and full
strong-stock return feedback remain separate, unimplemented requirements.


## Windows stat identity portability

CPython 3.12.10's Windows [path-stat compatibility wrapper](https://github.com/python/cpython/blob/v3.12.10/Modules/posixmodule.c#L2009-L2018)
reports creation time through `st_ctime`, while its [descriptor conversion](https://github.com/python/cpython/blob/v3.12.10/Python/fileutils.c#L1026-L1041)
reports file change time there. Equality of the entire cross-API tuple can thus
reject a stable file. Windows cross-API checks keep device, inode, size,
modification time and explicit birth time; each API's full fingerprint including
ctime is still checked independently. Descriptor fingerprints are checked before
and after each bounded read and across both opens; path fingerprints remain
checked before, between and after reads and after the memory query. Other
platforms, or runtimes lacking explicit birth time, retain strict tuple matching.
No timestamps, file IDs, content checks, active-journal guards or write prohibitions
are removed. Synthetic platform metadata regressions do not replace native
Windows CI; the native stat pair is included in assertion failure diagnostics.
