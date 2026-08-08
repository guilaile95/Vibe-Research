/**
 * Intel Daily Digest Generation Orchestrator.
 *
 * Orchestrates chatStream LLM call, prompt context construction, signal cancellation,
 * generation ID race checks, phase transitions (generating -> saving), and backend persistence.
 * Used by both UI components and unit tests.
 *
 * Zero-valid-item contract (Round 4):
 * - prepareDigestItems filters invalid materials first
 * - If status === "unavailable" (no valid dated items): never call chatStream, never POST save
 * - POST uses the real material status (normal | partial), never hard-coded "normal"
 */

import { api, type Industry, type IntelDigest, type IntelDigestSaveIn, type IntelDigestSaveResult } from "./api.ts";
import { chatStream } from "./llm.ts";
import { prepareDigestItems, shouldSaveDigest } from "./intelDigestView.ts";

export interface RunIntelDigestGenerationParams {
  industry: Industry;
  signal: AbortSignal;
  generationId: number;
  getCurrentGenerationId: () => number;
  isMounted: () => boolean;
  onDelta?: (text: string) => void;
  onPhaseChange?: (phase: "generating" | "saving") => void;
  saveApi?: (payload: IntelDigestSaveIn, signal?: AbortSignal) => Promise<IntelDigestSaveResult>;
  chatStreamFn?: typeof chatStream;
}

export interface RunIntelDigestGenerationResult {
  status:
    | "saved"
    | "deduped"
    | "cancelled"
    | "error"
    | "empty"
    | "superseded"
    | "save_failed"
    | "unavailable";
  summaryText?: string;
  digest?: IntelDigest | null;
  error?: string;
  materialStatus?: "normal" | "partial" | "unavailable";
  droppedCount?: number;
}

const ZERO_VALID_MSG = "没有可用于摘要的有效带日期资讯";

export async function runIntelDigestGeneration(
  params: RunIntelDigestGenerationParams
): Promise<RunIntelDigestGenerationResult> {
  const {
    industry,
    signal,
    generationId,
    getCurrentGenerationId,
    isMounted,
    onDelta,
    onPhaseChange,
    saveApi = (payload, sig) => api.saveIntelDigest(payload, sig),
    chatStreamFn = chatStream,
  } = params;

  if (signal.aborted || !isMounted()) {
    return { status: "cancelled" };
  }

  const prepared = prepareDigestItems(industry.items);

  // Zero valid materials: never call chatStream, never POST save
  if (prepared.status === "unavailable" || prepared.canonicalItems.length === 0) {
    return {
      status: "unavailable",
      error: ZERO_VALID_MSG,
      materialStatus: "unavailable",
      droppedCount: prepared.droppedCount,
    };
  }

  const { promptContext, inputItems, sourceRefs, status: materialStatus, droppedCount } = prepared;

  const prompt =
    `以下是「${industry.name}」赛道近期资讯。请提炼「今日要点」3-5 条：每条一句话（≤40 字），` +
    `抓住重要事件、趋势与可能影响。直接用「- 」列点，不要多余前后缀。\n\n${promptContext}`;

  let accText = "";
  onPhaseChange?.("generating");

  try {
    const streamResult = await chatStreamFn(
      [{ role: "user", content: prompt }],
      `${industry.name}赛道资讯`,
      {
        onDelta: (t) => {
          accText += t;
          if (!signal.aborted && isMounted() && getCurrentGenerationId() === generationId) {
            onDelta?.(accText);
          }
        },
      },
      signal
    );

    if (signal.aborted || !isMounted()) {
      return { status: "cancelled", summaryText: accText, materialStatus, droppedCount };
    }

    if (getCurrentGenerationId() !== generationId) {
      return { status: "superseded", summaryText: accText, materialStatus, droppedCount };
    }

    const finalText = (streamResult?.content || accText).trim();
    if (!shouldSaveDigest(finalText)) {
      return { status: "empty", materialStatus, droppedCount };
    }

    // Phase transition to "saving" - Point of no return in UI
    onPhaseChange?.("saving");

    try {
      const saveRes = await saveApi(
        {
          sector_key: industry.key,
          // Use real material status (normal | partial) — never hard-code "normal"
          status: materialStatus,
          summary_text: finalText,
          source_refs: sourceRefs,
          input_items: inputItems,
        },
        signal
      );

      if (signal.aborted || !isMounted()) {
        return { status: "cancelled", summaryText: finalText, materialStatus, droppedCount };
      }

      if (getCurrentGenerationId() !== generationId) {
        return { status: "superseded", summaryText: finalText, materialStatus, droppedCount };
      }

      if (saveRes.error) {
        return {
          status: "save_failed",
          summaryText: finalText,
          error: saveRes.error,
          materialStatus,
          droppedCount,
        };
      }

      return {
        status: saveRes.deduped ? "deduped" : "saved",
        summaryText: finalText,
        digest: saveRes.digest,
        materialStatus,
        droppedCount,
      };
    } catch (saveErr) {
      if (signal.aborted || !isMounted()) {
        return { status: "cancelled", summaryText: finalText, materialStatus, droppedCount };
      }
      if (getCurrentGenerationId() !== generationId) {
        return { status: "superseded", summaryText: finalText, materialStatus, droppedCount };
      }
      const errMsg = saveErr instanceof Error ? saveErr.message : "保存失败";
      return {
        status: "save_failed",
        summaryText: finalText,
        error: errMsg,
        materialStatus,
        droppedCount,
      };
    }
  } catch (streamErr) {
    if (
      signal.aborted ||
      (typeof streamErr === "object" &&
        streamErr !== null &&
        "name" in streamErr &&
        (streamErr as { name: string }).name === "AbortError")
    ) {
      return { status: "cancelled", summaryText: accText, materialStatus, droppedCount };
    }

    const errMsg = streamErr instanceof Error ? streamErr.message : "生成失败";
    return { status: "error", error: errMsg, materialStatus, droppedCount };
  }
}
