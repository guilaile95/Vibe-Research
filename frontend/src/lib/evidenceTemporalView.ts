import type { TemporalAuthorityBasis, TemporalAuthorityState } from "./api/types.ts";

/** Display-only Chinese chrome. Canonical temporal API enum keys stay unchanged. */

export const TEMPORAL_AUTHORITY_HEADING = "时间权威";
export const TEMPORAL_METADATA_NOT_SOURCE_COPY = "你提交的元数据不是来源权威。";
export const TEMPORAL_OBSERVED_NOT_EFFECTIVE_COPY = "观察时间不是生效时间。";
export const TEMPORAL_BASIS_LABEL = "依据";
export const TEMPORAL_EFFECTIVE_AT_LABEL = "生效时间";
export const TEMPORAL_EC1_LABEL = "EC1";
export const TEMPORAL_REASON_LABEL = "原因";
export const TEMPORAL_SOURCE_IDENTITY_LABEL = "来源标识";
export const TEMPORAL_SOURCE_PUBLISHED_AT_LABEL = "来源发布时间";
export const TEMPORAL_EVENT_IDENTITY_LABEL = "事件标识";
export const TEMPORAL_EVENT_OCCURRED_AT_LABEL = "事件发生时间";
export const TEMPORAL_OBSERVED_AT_LABEL = "观察时间";
export const TEMPORAL_CREATED_AT_LABEL = "创建时间";
export const TEMPORAL_INGESTED_AT_LABEL = "写入时间";
export const TEMPORAL_SAVE_BUTTON_LABEL = "保存已声明 / 已观察的时间信息";
export const TEMPORAL_UTC_HELP_COPY = "仅接受明确带 Z 的规范 UTC 文本。你提交的元数据不会自行成为来源权威。";
export const TEMPORAL_SOURCE_IDENTITY_PLACEHOLDER = "已声明的来源标识";
export const TEMPORAL_EVENT_IDENTITY_PLACEHOLDER = "已声明的事件标识";
export const TEMPORAL_DATETIME_PLACEHOLDER = "2026-08-17T08:30:00.000000Z";

export const TEMPORAL_STATE_LABELS: Record<TemporalAuthorityState, string> = {
  PROVEN: "已证明",
  UNPROVEN: "未证明（已声明的元数据）",
  ERROR: "错误（已拒绝）",
};

export const TEMPORAL_AUTHORITY_BASIS_LABELS: Record<TemporalAuthorityBasis, string> = {
  SOURCE_PUBLISHED_AT: "来源发布时间",
  EVENT_OCCURRED_AT: "事件发生时间",
  NONE: "无权威时间",
};

function mappedLabel<T extends string>(value: string, labels: Record<T, string>): string {
  return Object.prototype.hasOwnProperty.call(labels, value) ? labels[value as T] : value;
}

export function temporalAuthorityStateLabel(state: string): string {
  return mappedLabel(state, TEMPORAL_STATE_LABELS);
}

export function temporalAuthorityBasisLabel(basis: string): string {
  return mappedLabel(basis, TEMPORAL_AUTHORITY_BASIS_LABELS);
}
