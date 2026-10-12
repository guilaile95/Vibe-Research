import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { boundaryLabels, conditionDraft, formatMetric, percent, resultLabel, verificationDate, ownsVerificationDate, type VerificationView } from "../src/lib/nextDayVerification.ts";

test("missing evidence and provisional observations are never failures", () => {
  assert.match(resultLabel({ state: "NO_EVIDENCE", verified: null }), /待核验/);
  assert.match(resultLabel({ state: "PENDING_CLOSE", verified: null }), /待.*收盘/);
  assert.equal(resultLabel({ state: "VERIFIED", verified: false }), "不成立");
  assert.equal(resultLabel({ state: "VERIFIED", verified: true }), "成立");
  assert.equal(resultLabel({ state: "VERIFIED", verified: null }), "待核验");
});
test("count/rate zeros remain zeros and 0–1 rate becomes percent once", () => {
  assert.equal(formatMetric("limit_up_count", 0), "0 家");
  assert.equal(formatMetric("failed_board_rate", 0), "0.0%");
  assert.equal(formatMetric("failed_board_rate", 0.25), "25.0%");
  assert.equal(formatMetric("failed_board_rate", null), "未知");
  assert.equal(percent(null), "—");
  assert.equal(percent(0), "0.0%");
});
test("draft strips server-owned timestamps evidence and baseline", () => {
  const view = { items: [{ metric: "limit_up_count", direction: "up", reason: "test", written_at: "bad", baseline: { rate: 1 }, prior_value: 99 }] } as unknown as VerificationView;
  assert.deepEqual(conditionDraft(view), [{ metric: "limit_up_count", direction: "up", reason: "test" }]);
  assert.match(boundaryLabels.SEALED, /不能修改或删除/);
  assert.match(boundaryLabels.CALENDAR_UNKNOWN, /禁止写入/);
});
test("card reachable in DailyReview with explicit saves, cancellation and no automatic mutation", () => {
  const page = readFileSync(new URL("../src/pages/DailyReview.tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/components/dailyReview/NextDayVerificationCard.tsx", import.meta.url), "utf8");
  assert.match(page, /<NextDayVerificationCard initialDate=/);
  assert.match(card, /onClick=\{\(\) => void save\(\)\}/);
  assert.match(card, /controller\.abort\(\)/);
  assert.match(card, /id === sequence\.current/);
  assert.match(card, /savingLock\.current/);
  assert.match(card, /revision: view\.revision, items: draft/);
  assert.match(card, /ownsVerificationDate\(view, day\) && view.state === "OPEN"/);
  assert.match(card, /自动核验等待本地合格收盘事实/);
  assert.doesNotMatch(card, /setInterval|localStorage|agent|llm/);
});


test("cold mount uses canonical Shanghai date; invalid locale date never reaches API", () => {
  const now = new Date("2026-10-11T17:00:00Z");
  assert.equal(verificationDate(undefined, now), "2026-10-12");
  assert.equal(verificationDate(null, now), "2026-10-12");
  assert.equal(verificationDate("2026/10/12", now), "2026-10-12");
  assert.equal(verificationDate("2026-02-30", now), "2026-10-12");
  assert.equal(verificationDate("2026-10-09", now), "2026-10-09");
  const card = readFileSync(new URL("../src/components/dailyReview/NextDayVerificationCard.tsx", import.meta.url), "utf8");
  assert.match(card, /useState\(\(\) => verificationDate\(initialDate\)\)/);
  assert.match(card, /initialDate && !userTouched.current && !savingLock.current/);
  assert.match(card, /userTouched.current = true; setDay/);
});


test("date ownership forbids old view revision from saving into newly selected day", () => {
  const view = { trade_date: "2026-07-31" } as VerificationView;
  assert.equal(ownsVerificationDate(view, "2026-07-31"), true);
  assert.equal(ownsVerificationDate(view, "2026-08-03"), false);
  assert.equal(ownsVerificationDate(null, "2026-07-31"), false);
});
