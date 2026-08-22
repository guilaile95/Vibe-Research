// P1-DF3：Review boundary 结构化输入的行为测试（真实函数断言）。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  browserTimeZoneName,
  formatUtcOffsetMinutes,
  parseReviewBoundary,
} from "../src/lib/reviewBoundaryInput.ts";

test("合法 datetime-local 值解析为该本地时刻的 canonical UTC ISO", () => {
  const parsed = parseReviewBoundary("2026-08-30T10:00");
  assert.equal(parsed.status, "VALID");
  if (parsed.status !== "VALID") return;
  // 与内置本地时间解释逐字一致（不硬编码机器时区）。
  assert.equal(parsed.iso, new Date(2026, 7, 30, 10, 0).toISOString());
});

test("秒精度保留且 ISO 毫秒化", () => {
  const parsed = parseReviewBoundary("2026-08-30T10:00:30");
  assert.equal(parsed.status, "VALID");
  if (parsed.status !== "VALID") return;
  assert.equal(parsed.iso.endsWith(":30.000Z"), true);
  assert.equal(parsed.iso, new Date(2026, 7, 30, 10, 0, 30).toISOString());
});

test("空值 / 残缺 / 垃圾输入 fail closed", () => {
  for (const value of ["", "   ", "2026-08-30", "2026-08-30T10", "abc", "2026-08-30 10:00"]) {
    const parsed = parseReviewBoundary(value);
    assert.equal(parsed.status, "INVALID");
    if (parsed.status !== "INVALID") return;
    assert.equal(typeof parsed.reason, "string");
  }
});

test("不存在的时刻 fail closed，不被浏览器静默滚正", () => {
  for (const value of ["2026-02-30T10:00", "2026-01-01T25:00", "2026-01-01T10:61"]) {
    assert.equal(parseReviewBoundary(value).status, "INVALID");
  }
});

test("UTC 偏移格式覆盖整点、半小时与零偏移", () => {
  assert.equal(formatUtcOffsetMinutes(0), "UTC+00:00");
  assert.equal(formatUtcOffsetMinutes(-480), "UTC+08:00");
  assert.equal(formatUtcOffsetMinutes(300), "UTC-05:00");
  assert.equal(formatUtcOffsetMinutes(-330), "UTC+05:30");
});

test("时区名可解析且非空", () => {
  assert.notEqual(browserTimeZoneName(), "");
});

test("页面使用结构化 review boundary 控件并展示时区/canonical，无时钟推导", () => {
  const source = readFileSync(
    new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /type="datetime-local"/);
  assert.match(source, /data-review-by-canonical/);
  assert.match(source, /data-review-by-tz/);
  assert.match(source, /parseReviewBoundary\(reviewByLocal\)/);
  assert.match(source, /review_by: reviewBoundary\.iso/);
  // 不允许任何时钟默认值或从 horizon 推导 review boundary
  assert.doesNotMatch(source, /Date\.now/);
  assert.doesNotMatch(source, /expected_horizon/);
  // 旧的手写 ISO 文本路径必须移除
  assert.doesNotMatch(source, /canonicalReviewBy/);
  assert.doesNotMatch(source, /placeholder="2026-08-30T10:00:00Z"/);
});
