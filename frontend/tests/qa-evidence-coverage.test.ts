import assert from "node:assert/strict";
import test from "node:test";
import type { EvidenceListResult, EvidenceRecord } from "../src/lib/api/types.ts";
import { CandidateEvidenceLoadError, loadCandidateEvidence } from "../src/lib/candidateEvidence.ts";
import { buildCandidateEvidenceGap } from "../src/lib/candidateCampaign.ts";

const records = (count: number): EvidenceRecord[] => Array.from({ length: count }, (_, index) => ({
  id: `qa-${index}`, subject_type: "stock", subject_id: "000001", evidence_type: "news",
  claim: `synthetic claim ${index}`, source_title: "synthetic", source_url: null,
  source_date: "2026-01-01", accessed_at: "2026-01-01T00:00:00Z", classification: "unknown",
  confidence: "low", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  deleted: 0, edit_token: "evidence-edit.v1:" + "a".repeat(64), deleted_at: null,
}));

function reader(items: EvidenceRecord[]) {
  const offsets: number[] = [];
  return {
    offsets,
    read: async ({ limit, offset }: { limit: number; offset: number }): Promise<EvidenceListResult> => {
      assert.equal(limit, 200, "must respect the backend's maximum page size");
      offsets.push(offset);
      return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
    },
  };
}

test("candidate coverage includes the 201st filing and its classification/source date", async () => {
  const items = records(201);
  items[200] = { ...items[200], evidence_type: "financial_filing", classification: "fact",
    confidence: "high", source_date: "2026-10-01" };
  const pages = reader(items);
  const result = await loadCandidateEvidence(pages.read, () => false);
  assert.deepEqual(pages.offsets, [0, 200, 0]);
  assert.equal(result?.total, 201);
  const gap = buildCandidateEvidenceGap(result!.records);
  assert.equal(gap.coverage.find(({ key }) => key === "FUNDAMENTALS")?.count, 1);
  assert.equal(gap.coverage.find(({ key }) => key === "FUNDAMENTALS")?.gap, false);
  assert.equal(gap.highConfidenceFactCount, 1);
  assert.equal(gap.latestSourceDate, "2026-10-01");
  assert.deepEqual(gap.classificationCounts, { fact: 1, inference: 0, unknown: 200 });
});

test("empty/exact-page/multiple-page loads finish with no empty-page loop", async () => {
  for (const [count, expectedOffsets] of [[0, [0]], [200, [0]], [401, [0, 200, 400, 0]]] as const) {
    const items = records(count);
    const pages = reader(items);
    assert.deepEqual(await loadCandidateEvidence(pages.read, () => false), { records: items, total: count });
    assert.deepEqual(pages.offsets, expectedOffsets);
  }
});

test("a failed later page or final readback never returns partial coverage", async () => {
  for (const failAt of [2, 3]) {
    const pages = reader(records(201));
    let calls = 0;
    const failure = new Error("synthetic read failure");
    await assert.rejects(loadCandidateEvidence(async (params) => {
      if (++calls === failAt) throw failure;
      return pages.read(params);
    }, () => false), (cause) => cause === failure);
    assert.equal(calls, failAt);
  }
});

test("changed totals, missing rows and overlapping IDs fail closed without retry loops", async () => {
  for (const change of ["grow", "shrink", "missing", "duplicate"] as const) {
    const pages = reader(records(201));
    let calls = 0;
    await assert.rejects(loadCandidateEvidence(async (params) => {
      calls++;
      const page = await pages.read(params);
      if (params.offset > 0) {
        if (change === "grow") page.total++;
        if (change === "shrink") page.total--;
        if (change === "missing") page.items = [];
        if (change === "duplicate") page.items[0] = records(1)[0];
      }
      return page;
    }, () => false), CandidateEvidenceLoadError);
    assert.equal(calls, 2);
  }
});

test("readback rejects same-total changes in ordering or updated_at", async () => {
  for (const change of ["reorder", "updated", "total"] as const) {
    const pages = reader(records(201));
    let calls = 0;
    await assert.rejects(loadCandidateEvidence(async (params) => {
      const page = await pages.read(params);
      if (++calls === 3) {
        if (change === "reorder") [page.items[0], page.items[1]] = [page.items[1], page.items[0]];
        if (change === "updated") page.items[0] = { ...page.items[0], updated_at: "2026-10-02T00:00:00Z" };
        if (change === "total") page.total++;
      }
      return page;
    }, () => false), CandidateEvidenceLoadError);
    assert.equal(calls, 3);
  }
});

test("navigation cancellation ignores in-flight pages and sends no more requests", async () => {
  const pages = reader(records(401));
  let cancelled = false;
  const result = await loadCandidateEvidence(async (params) => {
    const page = await pages.read(params);
    cancelled = true; // Code changed while the response was in flight.
    return page;
  }, () => cancelled);
  assert.equal(result, null);
  assert.deepEqual(pages.offsets, [0]);
  assert.equal(await loadCandidateEvidence(pages.read, () => true), null);
  assert.deepEqual(pages.offsets, [0]);
});
