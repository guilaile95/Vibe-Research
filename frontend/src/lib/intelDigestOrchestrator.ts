/**
 * Intel Daily Digest Generation Orchestrator.
 *
 * Orchestrates chatStream LLM call, prompt context construction, signal cancellation,
 * generation ID race checks, and backend persistence.
 * Used by both UI components and unit tests.
 */

import { api, type Industry, type IntelDigest, type IntelDigestSaveIn, type IntelDigestSaveResult } from "./api.ts";
import { chatStream } from "./llm.ts";
import { buildDigestInputItems, buildDigestSourceRefs, shouldSaveDigest } from "./intelDigestView.ts";

export interface RunIntelDigestGenerationParams {
  industry: Industry;
  signal: AbortSignal;
  generationId: number;
  getCurrentGenerationId: () => number;
  isMounted: () => boolean;
  onDelta?: (text: string) => void;
  saveApi?: (payload: IntelDigestSaveIn) => Promise<IntelDigestSaveResult>;
  chatStreamFn?: typeof chatStream;
}

export interface RunIntelDigestGenerationResult {
  status: "saved" | "deduped" | "cancelled" | "error" | "empty" | "superseded" | "save_failed";
  summaryText?: string;
  digest?: IntelDigest | null;
  error?: string;
}

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
    saveApi = (payload) => api.saveIntelDigest(payload),
    chatStreamFn = chatStream,
  } = params;

  if (signal.aborted || !isMounted()) {
    return { status: "cancelled" };
  }

  const inputItems = buildDigestInputItems(industry.items);
  const sourceRefs = buildDigestSourceRefs(industry.items);

  const ctx = industry.items
    .slice(0, 25)
    .map((it) => `[${it.time}] ${it.source}｜${it.zh || it.title}`)
    .join("\n");

  const prompt =
    `以下是「${industry.name}」赛道近期资讯。请提炼「今日要点」3-5 条：每条一句话（≤40 字），` +
    `抓住重要事件、趋势与可能影响。直接用「- 」列点，不要多余前后缀。\n\n${ctx}`;

  let accText = "";

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
      return { status: "cancelled" };
    }

    if (getCurrentGenerationId() !== generationId) {
      return { status: "superseded" };
    }

    const finalText = (streamResult?.content || accText).trim();
    if (!shouldSaveDigest(finalText)) {
      return { status: "empty" };
    }

    // Call save API after stream resolves
    try {
      const saveRes = await saveApi({
        sector_key: industry.key,
        status: "normal",
        summary_text: finalText,
        source_refs: sourceRefs,
        input_items: inputItems,
      });

      if (signal.aborted || !isMounted()) {
        return { status: "cancelled" };
      }

      if (getCurrentGenerationId() !== generationId) {
        return { status: "superseded" };
      }

      if (saveRes.error) {
        return {
          status: "save_failed",
          summaryText: finalText,
          error: saveRes.error,
        };
      }

      return {
        status: saveRes.deduped ? "deduped" : "saved",
        summaryText: finalText,
        digest: saveRes.digest,
      };
    } catch (saveErr) {
      if (signal.aborted || !isMounted()) {
        return { status: "cancelled" };
      }
      if (getCurrentGenerationId() !== generationId) {
        return { status: "superseded" };
      }
      const errMsg = saveErr instanceof Error ? saveErr.message : "保存失败";
      return {
        status: "save_failed",
        summaryText: finalText,
        error: errMsg,
      };
    }
  } catch (streamErr) {
    if (
      signal.aborted ||
      (typeof streamErr === "object" &&
        streamErr !== null &&
        "name" in streamErr &&
        streamErr.name === "AbortError")
    ) {
      return { status: "cancelled" };
    }

    const errMsg = streamErr instanceof Error ? streamErr.message : "生成失败";
    return { status: "error", error: errMsg };
  }
}
