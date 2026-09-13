import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  TEMPORAL_AUTHORITY_BASIS_LABELS,
  TEMPORAL_AUTHORITY_HEADING,
  TEMPORAL_BASIS_LABEL,
  TEMPORAL_CREATED_AT_LABEL,
  TEMPORAL_DATETIME_PLACEHOLDER,
  TEMPORAL_EC1_LABEL,
  TEMPORAL_EFFECTIVE_AT_LABEL,
  TEMPORAL_EVENT_IDENTITY_LABEL,
  TEMPORAL_EVENT_IDENTITY_PLACEHOLDER,
  TEMPORAL_EVENT_OCCURRED_AT_LABEL,
  TEMPORAL_INGESTED_AT_LABEL,
  TEMPORAL_METADATA_NOT_SOURCE_COPY,
  TEMPORAL_OBSERVED_AT_LABEL,
  TEMPORAL_OBSERVED_NOT_EFFECTIVE_COPY,
  TEMPORAL_REASON_LABEL,
  TEMPORAL_SAVE_BUTTON_LABEL,
  TEMPORAL_SOURCE_IDENTITY_LABEL,
  TEMPORAL_SOURCE_IDENTITY_PLACEHOLDER,
  TEMPORAL_SOURCE_PUBLISHED_AT_LABEL,
  TEMPORAL_STATE_LABELS,
  TEMPORAL_UTC_HELP_COPY,
  temporalAuthorityBasisLabel,
  temporalAuthorityStateLabel,
} from "../src/lib/evidenceTemporalView.ts";

test("evidence temporal chrome is Chinese while canonical keys stay unchanged", () => {
  assert.equal(TEMPORAL_AUTHORITY_HEADING, "时间权威");
  assert.equal(TEMPORAL_METADATA_NOT_SOURCE_COPY, "你提交的元数据不是来源权威。");
  assert.equal(TEMPORAL_OBSERVED_NOT_EFFECTIVE_COPY, "观察时间不是生效时间。");
  assert.equal(TEMPORAL_BASIS_LABEL, "依据");
  assert.equal(TEMPORAL_EFFECTIVE_AT_LABEL, "生效时间");
  assert.equal(TEMPORAL_EC1_LABEL, "EC1");
  assert.equal(TEMPORAL_REASON_LABEL, "原因");
  assert.equal(TEMPORAL_SOURCE_IDENTITY_LABEL, "来源标识");
  assert.equal(TEMPORAL_SOURCE_PUBLISHED_AT_LABEL, "来源发布时间");
  assert.equal(TEMPORAL_EVENT_IDENTITY_LABEL, "事件标识");
  assert.equal(TEMPORAL_EVENT_OCCURRED_AT_LABEL, "事件发生时间");
  assert.equal(TEMPORAL_OBSERVED_AT_LABEL, "观察时间");
  assert.equal(TEMPORAL_CREATED_AT_LABEL, "创建时间");
  assert.equal(TEMPORAL_INGESTED_AT_LABEL, "写入时间");
  assert.equal(TEMPORAL_SAVE_BUTTON_LABEL, "保存已声明 / 已观察的时间信息");
  assert.equal(TEMPORAL_UTC_HELP_COPY, "仅接受明确带 Z 的规范 UTC 文本。你提交的元数据不会自行成为来源权威。");
  assert.equal(TEMPORAL_SOURCE_IDENTITY_PLACEHOLDER, "已声明的来源标识");
  assert.equal(TEMPORAL_EVENT_IDENTITY_PLACEHOLDER, "已声明的事件标识");
  assert.equal(TEMPORAL_DATETIME_PLACEHOLDER, "2026-08-17T08:30:00.000000Z");

  assert.deepEqual(Object.keys(TEMPORAL_STATE_LABELS), ["PROVEN", "UNPROVEN", "ERROR"]);
  assert.equal(TEMPORAL_STATE_LABELS.PROVEN, "已证明");
  assert.equal(TEMPORAL_STATE_LABELS.UNPROVEN, "未证明（已声明的元数据）");
  assert.equal(TEMPORAL_STATE_LABELS.ERROR, "错误（已拒绝）");
  assert.equal(temporalAuthorityStateLabel("PROVEN"), "已证明");
  assert.equal(temporalAuthorityStateLabel("UNPROVEN"), "未证明（已声明的元数据）");
  assert.equal(temporalAuthorityStateLabel("ERROR"), "错误（已拒绝）");
  assert.equal(temporalAuthorityStateLabel("UNEXPECTED_STATE"), "UNEXPECTED_STATE");

  assert.deepEqual(Object.keys(TEMPORAL_AUTHORITY_BASIS_LABELS), [
    "SOURCE_PUBLISHED_AT",
    "EVENT_OCCURRED_AT",
    "NONE",
  ]);
  assert.equal(TEMPORAL_AUTHORITY_BASIS_LABELS.SOURCE_PUBLISHED_AT, "来源发布时间");
  assert.equal(TEMPORAL_AUTHORITY_BASIS_LABELS.EVENT_OCCURRED_AT, "事件发生时间");
  assert.equal(TEMPORAL_AUTHORITY_BASIS_LABELS.NONE, "无权威时间");
  assert.equal(temporalAuthorityBasisLabel("SOURCE_PUBLISHED_AT"), "来源发布时间");
  assert.equal(temporalAuthorityBasisLabel("EVENT_OCCURRED_AT"), "事件发生时间");
  assert.equal(temporalAuthorityBasisLabel("NONE"), "无权威时间");
  assert.equal(temporalAuthorityBasisLabel("UNEXPECTED_BASIS"), "UNEXPECTED_BASIS");
});

test("EvidenceDetail wires temporal chrome from the view lib without changing intake fields", () => {
  const source = readFileSync(new URL("../src/pages/EvidenceDetail.tsx", import.meta.url), "utf8");
  assert.match(source, /from "@\/lib\/evidenceTemporalView"/);
  assert.match(source, /TEMPORAL_AUTHORITY_HEADING/);
  assert.match(source, /TEMPORAL_OBSERVED_NOT_EFFECTIVE_COPY/);
  assert.match(source, /TEMPORAL_SAVE_BUTTON_LABEL/);
  assert.match(source, /temporalAuthorityStateLabel/);
  assert.match(source, /temporalAuthorityBasisLabel/);
  assert.match(source, /source_identity:/);
  assert.match(source, /source_published_at:/);
  assert.match(source, /event_identity:/);
  assert.match(source, /event_occurred_at:/);
  assert.match(source, /observed_at:/);
  assert.match(source, /created_at:/);
  assert.match(source, /ingested_at:/);
  assert.match(source, /api\.evidenceTemporalIntake\(id, body\)/);
  assert.doesNotMatch(source, /Temporal authority/);
  assert.doesNotMatch(source, /Submitted metadata is not source authority/);
  assert.doesNotMatch(source, /Observed time is not effective time/);
  assert.doesNotMatch(source, /Source identity/);
  assert.doesNotMatch(source, /asserted source identity/);
  assert.doesNotMatch(source, /保存 ASSERTED \/ OBSERVED METADATA/);
  assert.doesNotMatch(source, /未证明（ASSERTED metadata）/);
  assert.doesNotMatch(source, /\bBUY\b|\bSELL\b/);
});
