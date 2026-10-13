import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { isSealQualityArchiveForDate } from "../src/lib/sealQuality.ts";
import { validatedReviewBasis } from "../src/lib/dailyReviewBasis.ts";
import { isEvidenceReadinessForDate } from "../src/lib/evidenceReadiness.ts";
import { isVerificationViewForDate } from "../src/lib/nextDayVerification.ts";
import { isCohortIdentityForDate } from "../src/lib/cohortIdentity.ts";

// The backend parity test proves these exact bytes match real registered HTTP
// reads. This test separately proves the full-page fixture reaches real guards.
const golden = JSON.parse(readFileSync(new URL("./fixtures/daily-review-integrated.json", import.meta.url), "utf8"));
for (const [day, value] of Object.entries(golden) as [string, Record<string, unknown>][]) {
  test(`integrated ${day} golden is accepted by both production card validators`, () => {
    assert.equal(isSealQualityArchiveForDate(value["seal-quality"], day), true);
    assert.equal(isCohortIdentityForDate(value["cohort-identity"], day), true);
    assert.equal(isEvidenceReadinessForDate(value["evidence-readiness"], day), true);
    if (value["journal-saved"]) assert.equal(isVerificationViewForDate(value["journal-saved"], day), true);
    assert.equal(isSealQualityArchiveForDate(value["seal-quality"], "2026-08-03"), false);
    assert.equal(isCohortIdentityForDate(value["cohort-identity"], "2026-08-03"), false);
  });
}


test("actual restored AI goldens distinguish valid basis from legacy missing capture", () => {
  const records = JSON.parse(readFileSync(new URL("./fixtures/daily-review-ai-basis.json", import.meta.url), "utf8"));
  assert.ok(validatedReviewBasis(records.v2));
  assert.equal(validatedReviewBasis(records.v1), null);
  const malformed = structuredClone(records.v2);
  malformed.payload.input_basis.trade_date = "2026-07-30";
  assert.equal(validatedReviewBasis(malformed), null);
});
