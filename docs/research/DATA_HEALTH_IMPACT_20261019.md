# Data Health relationship drill-down, 2026-10-19

## Supported slice

The existing `GET /api/data-health/{source_id}` detail has an additive optional
`impact` projection (`data-health-impact.v1`). The existing Data Health page
shows source diagnostics, known relationships, and read-only navigation together.

Only `evidence_ledger` has a registered object relationship: persisted
`thesis_evidence_links` joined to the actual Thesis and current Evidence record.
The Thesis's explicit subject identifies the stock, sector, or theme. Relationship
membership is **not proof that a source issue damaged that object**. Current
Evidence availability is shown independently of source quality or evidence truth.
Missing/deleted Evidence and cross-subject links cannot produce an Evidence
navigation link. Missing Thesis endpoints or duplicate identities fail closed.

All other sources, including quotes, announcements, financials, and MyReports,
return `unmapped`, not an empty claim of zero affected objects. The existing event
store does not persist subject identity; provider-wide failures must never be
joined to all stocks or inferred from matching labels/URLs. Campaign dependencies,
unlinked Evidence and immutable report/snapshot dependencies are not mapped here.
An absent, unreadable, or incompatible ledger returns `unknown`. A valid empty
link set remains `mapped` with no links and an explicit absence-of-proof notice.

## Actions and boundaries

Only existing `/thesis/:id` and `/evidence/:id` read-page links are supplied.
The UI distinguishes investment logic from reports and labels frozen Thesis
records. Its notice never rewrites frozen snapshots/reports, ignores an error,
changes FrozenGate, switches providers or automatically reruns any model.
All health reads remain offline and non-mutating. The existing WAL-aware readonly
ledger snapshot is reused, with one transaction and at most 200 ordered link rows;
truncation is disclosed. Detail source identity and existing request ownership
protect newer source selection and reloads from stale impact responses.

## Verification scope

Synthetic persisted-ledger tests cover ordinary links, missing/deleted records,
recovery, wrong subjects, duplicate identities, missing Thesis endpoints, frozen
notice projection, bounded output and unchanged filesystem bytes. API tests cover
registered versus unsupported sources. Frontend pure tests cover source/schema
ownership. The existing `test:e2e:intel-health-recovery` runner additionally checks
rendered impact, missing/recovered evidence, frozen notices, valid navigation URLs,
unsupported providers and late-response ownership at desktop/mobile widths.
These checks do not establish real-provider/model quality or natural usage value.

Local slice validation: 113 focused backend Data Health tests passed; frontend
unit suite 1,890 passed with one existing skip; TypeScript/Vite build passed.
Rendered browser acceptance was **not completed**: bundled Chromium was absent,
and the installed Chromium could not create its local socket in the execution
sandbox. The reviewed retry failed before launch. The browser scenarios remain
available in the supported runner for an environment that permits normal launch;
no isolation or security settings were changed to bypass the restriction.
