# Offline research-quality diagnostics

This read-only diagnostic CLI consumes the existing saved company, comparison and daily-review contracts. It makes **zero model/provider calls**, writes no database or report state, and adds no runtime dependencies. It does not replace `ai_answer_quality.py` arithmetic checks, existing citation validation or frozen-bundle identity checks. Those remain owned by their existing modules.

## Run against saved exports

Use the backend Python environment with the project's existing requirements installed, from the repository root:

```sh
python tools/research/research_quality_check.py report --kind company --report saved-run.json --evidence saved-bundle.json
python tools/research/research_quality_check.py report --kind comparison --report saved-comparison.json --evidence saved-pair.json
python tools/research/research_quality_check.py report --kind daily --report saved-daily-result.json
python tools/research/research_quality_check.py report --kind daily --report saved-daily-result.json --context exact-original-context.json
python tools/research/research_quality_check.py noise --case backend/tests/fixtures/research_quality/cross_company.json
```

Inputs remain local; no uploads or external service calls. Output prints only diagnostic statuses, hashes, counts and cited source IDs, not the report text, model configuration, account data or context body. Do not publish private exports or human reviewer identities. Files are bounded to 4 MiB each, with a combined report evaluation limit of 4 MiB. Invalid/unreadable input produces a generic error, without file paths or raw exception text.

- Company: the saved `company_research.v1` run plus its frozen bundle, as returned by existing research history/detail paths. Existing validators check the same bundle/run/stage contracts. The adapter supplies export-local row identities to the validator; it does **not** independently certify database owner columns or durable storage provenance.
- Comparison: the saved `company_comparison` run plus the frozen pair object (`schema_version`, `as_of`, `subjects`, `evidence`, `pair_sha256`). Qualified citations retain market, symbol and evidence ID; identical source IDs across two companies are not interchangeable.
- Daily: the stored AI-result record (`result_type`, `schema_version`, `trade_date`, `payload`, generation/model metadata and `input_fingerprint`). Existing restore validation is reused. The optional original context must match the v2 basis's exact UTF-8 SHA-256, including whitespace. Do not recreate a context from today's data and call it the original. Legacy v1 or v2 without the original context cannot resolve field-path citations and remains `NOT_EVALUATED` there. Exact textual context paths are identifiers, not proof that the prose is supported.

For fixture replay, existing company fixtures store the actual observed production-path stub run at `events[-1].record` and its bundle at `bundle`. Existing comparison fixtures store `record`; the frozen pair can be projected using the six pair fields above. These artifacts are labeled synthetic and offline-stub, not real model evidence. Daily tests persist and restore a synthetic result through the real saved-result service; no fabricated provider result is represented as a real model run.

Exit codes: `0` all evaluated checks pass; `1` a check fails; `2` input cannot be read/parsed; `3` incomplete (`NOT_EVALUATED`). Current report checks deliberately leave unmeasured semantic/noise dimensions incomplete, so a valid saved report normally exits `3`. Never treat any nonfailure as a green quality gate.

## Independent dimensions and interpretation

| Dimension | What can be established | What is not established |
| --- | --- | --- |
| Schema | Existing saved report/input contract validates | Report truth or independent database authenticity |
| Citation resolution | Exact IDs resolve to available sources, qualified by subject | Citation entailment, source truth, adequate coverage |
| Company alignment | Explicit citation subject agrees with output subject | Unlabeled prose mentions or cross-company reasoning |
| Time alignment | All available sources have declared dates, none after cutoff; malformed/future dates fail | Historical point-in-time availability, freshness, fiscal-period comparability |
| Numeric provenance | Explicit human-labeled quoted numeric claims, with declared units and period | Automatic extraction, conversions, arithmetic, every number in report |
| Coverage | Human labels for quoted spans | Automatic complete coverage of research questions |
| Conflict handling | Human labels for quoted spans | Automatic discovery of every conflict |
| Semantic support | Human labels for quoted spans | “Citations exist, therefore claims are true” |
| Noise contrast | Controlled saved paired-output comparison | General model robustness or semantic invariance |

`FAIL` dominates aggregation, with no averaging or invented weights. Empty checks and unknown evidence are `NOT_EVALUATED`. `model_quality` is always `NOT_EVALUATED`: this tool cannot certify model reliability. Structural `PASS` is labeled with its narrow scope. Missing dates stay unknown even when an archive request cutoff exists; an older publication date is allowed, not required to equal the research cutoff. Missing any available source's date makes that temporal dimension incomplete. These are declared metadata checks, not full temporal reasoning.

## Optional human-label sidecar

Use `--labels labels.json`. Hashes use canonical JSON: UTF-8, sorted keys, compact separators, no NaN; `report_sha256 = digest(record)` and `evidence_sha256 = digest([evidence, exact_context_text_or_null])`. The CLI prints both hashes. The contract is:

```json
{
  "schema_version": "research-quality-labels.v1",
  "report_sha256": "<printed hash>",
  "evidence_sha256": "<printed hash>",
  "origin": "HUMAN_REVIEW",
  "reviewer": "local reviewer identifier",
  "checks": [{
    "dimension": "semantic_support",
    "verdict": "NOT_EVALUATED",
    "quote": "exact nonempty quote from the saved report",
    "rationale": "What was examined, and why support remains unknown",
    "source_ids": [["US:AAPL", "global_quote_ref"]]
  }]
}
```

Allowed semantic dimensions are `coverage`, `conflict_handling`, `semantic_support` and `numeric_provenance`; verdicts are `PASS`, `FAIL`, `NOT_EVALUATED`. Each label needs a real quoted span and available same-subject source IDs. Numeric labels additionally require `unit` (`CNY`, `USD`, `HKD`, `percent`, `ratio`, `shares`, `count`) and ISO `period_end`; unsupported units fail closed rather than guessing a conversion. A reviewed subset is explicitly reported `LABELED_SUBSET_ONLY`. Labels are reviewer assertions, not independently verified gold or complete-report coverage. Unknown support must be labeled unknown. Empty labels do not pass. Changed reports/evidence invalidate old labels. No built-in semantic gold is shipped.

## Noise cases and saved paired responses

Five labeled **synthetic inputs** cover irrelevant data, another company, conflicting numbers, missing evidence and source-embedded prompt injection. None includes a canned “correct model response.” Fixtures alone never establish robustness.

```sh
python tools/research/research_quality_check.py noise --case case.json --baseline saved-baseline.json --perturbed saved-perturbed.json
```

Each saved-run object must contain `case_id`, `role` (`baseline`/`perturbed`), distinct `run_id`, `subjects`, identical `model` metadata, `baseline_evidence_sha256`, `input_sha256 = digest(case[role + '_input'])`, a nonempty string `output`, `output_sha256 = digest(output)`, and `capture_origin` (`SAVED_PROVIDER_RESPONSE` or `OFFLINE_STUB`). The case must retain the same task, requested subjects and cutoff across inputs, bind its clean evidence hash and actually change the input. Stale inputs, changed questions/subjects/cutoffs, different models, reused run IDs and mutated outputs fail closed.

For actual provider responses supplied from an already-authorized run, this command reports exact output equality and length differences as `paired_comparison: OBSERVED`. It never makes new calls and never infers semantic robustness from identical text. Capture origin is an explicit caller attestation, not authenticated provider provenance. Stub pairs return `OFFLINE_STUB_NOT_MODEL_EVIDENCE`. Both remain `model_robustness: NOT_EVALUATED`, requiring separate human review/gold for any substantive claim. Contract tests may synthesize these envelopes solely to test validation; they are not real paired-run results.

## Verification scope

Run `python -m pytest backend/tests/test_research_quality_diagnostics.py -q`. Focused tests exercise existing saved company/comparison fixtures, actual daily persistence, missing context, absent dates, future versus older dates, cross-subject identity, malformed units, empty/unknown evaluations, human failures, hash-bound annotations, stub/no-pair cases and stale/uncontrolled paired inputs. CLI tests verify JSON diagnostics and distinct incomplete/failure exits. No browser acceptance, provider-quality evaluation, real human labeling exercise, real paired-run evaluation, production model calls or UI build is implied by these tests; no UI source is changed.
