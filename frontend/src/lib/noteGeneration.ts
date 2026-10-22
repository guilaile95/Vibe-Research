import type { AiGeneratedResult, DailyReviewAiPayload, DailyReviewInputBasis } from "./api/types";
import { validatedReviewBasis, reviewBasisTimestamp } from "./dailyReviewBasis.ts";

/** An immutable local snapshot, not a promise that the server still retains this result. */
export interface NoteGeneration {
  schemaVersion: "note-generation.v1";
  resultType: "daily_review_ai";
  resultSchemaVersion: string;
  tradeDate: string;
  generatedAt: string;
  modelProvider: string;
  modelName: string;
  sourceReviewGeneratedAt: string;
  sourceDataCutoff: string | null;
  staleAtSave: boolean;
  inputBasis?: DailyReviewInputBasis;
}
const fields = ["schemaVersion", "resultType", "resultSchemaVersion", "tradeDate", "generatedAt", "modelProvider", "modelName", "sourceReviewGeneratedAt", "sourceDataCutoff", "staleAtSave", "inputBasis"];
const fail = (): never => { throw new Error("生成依据格式无效或版本不受支持，未修改研究记录"); };
const text = (v: unknown, max = 160): string => typeof v === "string" && v.trim().length > 0 && v.length <= max && !/[\u0000-\u001f]/.test(v) ? v : fail();
const time = (v: unknown): string => {
  const s = text(v, 64);
  return reviewBasisTimestamp(s) ? s : fail();
};

export function parseNoteGeneration(value: unknown): NoteGeneration {
  if (!value || typeof value !== "object" || Array.isArray(value) || JSON.stringify(value).length > 8192) return fail();
  const v = value as Record<string, unknown>;
  if (Object.keys(v).some(k => !fields.includes(k)) || v.schemaVersion !== "note-generation.v1" || v.resultType !== "daily_review_ai" || typeof v.staleAtSave !== "boolean") return fail();
  const date = text(v.tradeDate, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date) return fail();
  const result: NoteGeneration = {
    schemaVersion: "note-generation.v1", resultType: "daily_review_ai",
    resultSchemaVersion: text(v.resultSchemaVersion, 64), tradeDate: date, generatedAt: time(v.generatedAt),
    modelProvider: text(v.modelProvider), modelName: text(v.modelName),
    sourceReviewGeneratedAt: time(v.sourceReviewGeneratedAt),
    sourceDataCutoff: v.sourceDataCutoff === null ? null : time(v.sourceDataCutoff), staleAtSave: v.staleAtSave,
  };
  if (v.inputBasis !== undefined) {
    const b = validatedReviewBasis({ result_type: result.resultType, schema_version: result.resultSchemaVersion,
      trade_date: result.tradeDate, payload: { markdown: "", source_review_generated_at: result.sourceReviewGeneratedAt,
        source_data_cutoff: result.sourceDataCutoff, input_basis: v.inputBasis as DailyReviewInputBasis },
      generated_at: result.generatedAt, model_provider: result.modelProvider, model_name: result.modelName, stale: result.staleAtSave });
    if (!b) return fail();
    result.inputBasis = { ...b, component_statuses: { ...b.component_statuses } };
  }
  return result;
}

export function dailyReviewNoteGeneration(result: AiGeneratedResult<DailyReviewAiPayload>, content: string): NoteGeneration | undefined {
  if (!content.trim() || content !== result.payload.markdown) return undefined;
  const basis = validatedReviewBasis(result);
  return { schemaVersion: "note-generation.v1", resultType: "daily_review_ai", resultSchemaVersion: result.schema_version,
    tradeDate: result.trade_date, generatedAt: result.generated_at, modelProvider: result.model_provider, modelName: result.model_name,
    sourceReviewGeneratedAt: result.payload.source_review_generated_at, sourceDataCutoff: result.payload.source_data_cutoff,
    staleAtSave: result.stale, ...(basis ? { inputBasis: basis } : {}) };
}
