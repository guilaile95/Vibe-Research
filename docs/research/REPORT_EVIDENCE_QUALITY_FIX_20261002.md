# Report evidence freshness and excerpt coverage

## Scope and provenance

This bounded follow-up is based on PR358 commit `92abc3fbebee593cc1b675bdce5d8ba9ee2a850b`, tree `77f8c84733767b2a8f4d99e121c82f5287d65190`. Its report-module blobs are identical to the prior offline evaluation's PR356 baseline `15804a72a2d6da69e8f40048003ad58f8a58909b`:

- `backend/myreports.py`: `14a4f4845c3b95aa340808f99743504e8f7af6a2`.
- `backend/myreports_fulltext.py`: `058c4aef94ce46ef36e8d233c4cfea26c8d98884`.

The work uses a separate sparse checkout and branch. The original dirty `feat/research-brief-v01@753e1907` workspace and PR358's K-line, zero-value and cancellation files were not edited. File ownership was recorded in [PR358](https://github.com/guilaile95/Vibe-Research/pull/358#issuecomment-5956290343). Keep this follow-up Draft; no merge or deployment is included.

## Reproduced defects and resulting behavior

| Synthetic trigger | Before | After / recovery |
| --- | --- | --- |
| Replace a TXT source and update its metadata fingerprint, leaving the old SQLite index | Listing reports `FILE_CHANGED`, but old text can still enter the AI context | Search excludes it; context independently rejects an already returned hit. Explicit reindex binds the current source and restores retrieval. |
| Replace only the source bytes, or delete the source | Stored fingerprints alone cannot establish freshness | Actual source digest is checked at search and context construction. Missing source is unavailable even in list status. |
| Keep a cached hit, change and reindex its source | Old hit can outlive the index generation | Each hit carries the indexed source digest. A mismatched cached hit is `STALE_HIT`; re-search returns the current excerpt. |
| Raise during extraction when an older successful index exists | Exception exits before clearing the previous searchable chunks | Persist `INDEX_ERROR` and remove old chunks before raising a sanitized error. Successful explicit reindex restores availability. |
| Source changes during extraction, or a legacy index lacks its fingerprint | Source-to-text binding is unproven | Refuse searchable status / require explicit reindex. |
| First paragraph says preliminary revenue 100; a correction to 80 is over 320 characters later | The first excerpt contains 100 only; all selected reports can still count as included | The excerpt still omits 80. Coverage now explicitly marks `EXCERPTS_ONLY`, records excerpt truncation and warns that report counts do not establish full-text or final-conclusion coverage. |

The long-document change does **not** detect corrections or claim to retrieve all contrary evidence. It truthfully exposes the existing bounded excerpt. No semantic regular expression or new retrieval architecture was added.

## Compatibility contract

- `included_report_count` still counts distinct reports with at least one included excerpt.
- `uncovered_reports` still lists reports with no included excerpt. A partially included report can have `uncovered_reports=[]`.
- `context_truncated` still describes the context character budget. Rejected stale hits do not count as budget truncation.
- `hit_limit_reached` is based on the original returned hits, before freshness filtering.
- Additive fields: `content_coverage="EXCERPTS_ONLY"`, `excerpt_truncated`, `rejected_hit_count`. Hit fingerprints bind source generations; citation `sources` keep their existing shape.
- Listing avoids hashing every report. Search and context hash only their scoped candidates / selected reports. Listing metadata is not a claim of a full current-source verification.

## Verification

All material is synthetic. No real holdings, private research, credentials or external model were used.

1. **12/12 local stdlib integration regressions passed** on Python 3.8.10, loading the actual two product modules. The suite covers normal citation, read-only behavior, metadata and raw-only changes, deleted sources, legacy fingerprints, changed-source reindex, cached hits after reindex, raised and returned extraction failures, source mutation during extraction, long-document omission, selection isolation and budget/limit semantics. Failure injection is explicit and is not a model simulation.
2. **11/11 independent offline regressions passed**, authored and run separately under Astra/ultra. The reviewer inspected source-to-hit-to-context digest binding and selected-source isolation. These overlap the primary regressions and must not be summed as independent quality samples.
3. Updated the existing failed-extraction API test to expect the sanitized error and verify `INDEX_ERROR` / no old hits. Added two API/Codex transport cases asserting the same partial-excerpt disclosure with captured streams. Local full API tests require the project's FastAPI/pytest/pypdf environment; their remote CI result is reported on the PR, not inferred from the stdlib run.
4. `git diff --check` passed. The first local run's only error was a test-owned SQLite handle left open during Windows temporary-directory cleanup; it was fixed with explicit connection closing before the clean rerun. This was not a product assertion failure.

Reproduce the dependency-free product-module suite from repository root:

```sh
python -B -m unittest discover -s backend/tests -p test_myreports_evidence_quality.py -v
```

In the normal development environment, additionally run:

```sh
cd backend
pytest -q tests/test_myreports_fulltext.py tests/test_myreports_evidence_quality.py
```

## Fixed evaluation suite and untested model quality

The preceding immutable offline artifact contains 17 synthetic cases covering numerical provenance, citation support, conflicting sources, staleness, fiscal-period versus publication date, adjustment basis, no hit, tool errors, unknown/counterevidence and hostile document instructions. Reuse those inputs and their claim-by-claim review rubric; do not substitute a scripted answer for a real model answer.

- `cases.json` SHA256: `80d94f73fcb292c1918a7f0096a24df0d97431526ea64b58b2627bba8a4bde25`.
- `rubric.md` SHA256: `61e0873f54e51232783c256abd8ab99c856ec4b0fe55d4f4c15b90bc65fe3387`.
- EV17 distinguishes the old/artificial prefix-cut fault from the current serializer's positive control; a later correction surviving transport is not proof that a model understands it.
- Real model runs: **0**. Real answer quality: **NOT_EVALUATED**. Oracle arithmetic, string assertions, mocks, prompt rules and green CI cannot establish model truthfulness, citation entailment or resistance to hostile instructions.

Remaining boundaries: excerpt omissions remain possible; PDF/OCR extraction fidelity is outside this change; source verification is at the check boundary and does not make concurrent external file writes atomic. Unsupported natural-language truthfulness remains an evaluation/design question. A later authorized model run must use safely configured credentials, retain actual answers and evidence-specific adjudications, and score missing reviews as incomplete rather than passed.
