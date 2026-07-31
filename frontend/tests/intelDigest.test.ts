import assert from "node:assert/strict";
import test from "node:test";

import {
  prepareDigestItems,
  shouldSaveDigest,
  digestStatusBadge,
  isSectorMatch,
} from "../src/lib/intelDigestView.ts";

import {
  runIntelDigestGeneration,
} from "../src/lib/intelDigestOrchestrator.ts";
import type { Industry, IntelDigestSaveIn, IntelDigestSaveResult } from "../src/lib/api/types.ts";

const mockIndustry: Industry = {
  key: "ai",
  name: "AI 人工智能",
  accent: "#f97316",
  items: [
    { title: "AI Chip Innovation Announced", zh: "AI 芯片重大突破", source: "TechCrunch", time: "2026-07-31T10:00:00+08:00", url: "https://example.com/ai-chip?utm_source=rss" },
    { title: "Robotics Update", zh: "机器人突破", source: "Reuters", time: "2026-07-30T10:00:00+08:00", url: "https://example.com/robotics" },
  ],
};

test("prepareDigestItems: canonical sorting, deterministic prompt, input_items, and source_refs", () => {
  const itemsAsc = [...mockIndustry.items];
  const itemsDesc = [...mockIndustry.items].reverse();

  const resAsc = prepareDigestItems(itemsAsc);
  const resDesc = prepareDigestItems(itemsDesc);

  // Inverting original items order yields identical canonical output, prompt, input_items, and source_refs
  assert.deepEqual(resAsc.canonicalItems, resDesc.canonicalItems);
  assert.equal(resAsc.promptContext, resDesc.promptContext);
  assert.deepEqual(resAsc.inputItems, resDesc.inputItems);
  assert.deepEqual(resAsc.sourceRefs, resDesc.sourceRefs);

  // Assert published_at ISO format
  assert.ok(resAsc.inputItems[0].published_at?.includes("T"));
});

test("shouldSaveDigest rejects empty or whitespace-only texts", () => {
  assert.equal(shouldSaveDigest(""), false);
  assert.equal(shouldSaveDigest("   \n\t "), false);
  assert.equal(shouldSaveDigest(null), false);
  assert.equal(shouldSaveDigest(undefined), false);
  assert.equal(shouldSaveDigest("- Valid bullet point"), true);
});

test("digestStatusBadge formatting", () => {
  assert.deepEqual(digestStatusBadge(true, false), { text: "已保存", kind: "saved" });
  assert.deepEqual(digestStatusBadge(true, true), { text: "已去重", kind: "deduped" });
  assert.deepEqual(digestStatusBadge(false, false), { text: "", kind: "none" });
  assert.deepEqual(digestStatusBadge(undefined, undefined), { text: "", kind: "none" });
});

test("isSectorMatch detects sector switch race condition", () => {
  assert.equal(isSectorMatch("ai", "ai"), true);
  assert.equal(isSectorMatch("ai", "semiconductor"), false);
});

// Orchestrator unit tests covering Head Review phase & signal contracts
test("orchestrator: transitions phase to 'generating' then 'saving' before saveApi", async () => {
  let saveCalled = false;
  const phases: string[] = [];

  const mockSaveApi = async (payload: IntelDigestSaveIn): Promise<IntelDigestSaveResult> => {
    saveCalled = true;
    return {
      digest: {
        digest_id: "idg_123",
        digest_date: "2026-07-31",
        sector_key: "ai",
        sector_name: "AI 人工智能",
        status: "normal",
        summary_text: payload.summary_text,
        source_refs: payload.source_refs,
        input_fingerprint: "fp123",
        generated_at: "2026-07-31T10:00:00+08:00",
        created_at: "2026-07-31T10:00:00+08:00",
      },
      deduped: false,
    };
  };

  const mockChatStream = async (_msg: any, _ctx: any, handlers: any) => {
    handlers.onDelta?.("- AI 芯片突破");
    return { content: "- AI 芯片突破", trace: [], rounds: 1 };
  };

  const controller = new AbortController();
  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    onPhaseChange: (p) => phases.push(p),
    saveApi: mockSaveApi,
    chatStreamFn: mockChatStream as any,
  });

  assert.equal(saveCalled, true);
  assert.equal(res.status, "saved");
  assert.deepEqual(phases, ["generating", "saving"]);
});

test("orchestrator: stream cancellation retains partial summaryText draft", async () => {
  let saveCalled = false;
  const controller = new AbortController();

  const mockChatStream = async (_msg: any, _ctx: any, handlers: any) => {
    handlers.onDelta?.("- Partial delta text");
    controller.abort(); // Cancel during delta stream
    throw new Error("AbortError");
  };

  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: async () => { saveCalled = true; return { digest: null, deduped: false }; },
    chatStreamFn: mockChatStream as any,
  });

  assert.equal(saveCalled, false);
  assert.equal(res.status, "cancelled");
  assert.equal(res.summaryText, "- Partial delta text");
});

test("orchestrator: save API failure retains generated markdown text and returns save_failed status", async () => {
  const mockChatStream = async () => ({ content: "- Valid summary text", trace: [], rounds: 1 });
  const mockFailingSaveApi = async (): Promise<IntelDigestSaveResult> => {
    return { digest: null, deduped: false, error: "Intel 摘要数据存储故障" };
  };

  const controller = new AbortController();
  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: mockFailingSaveApi,
    chatStreamFn: mockChatStream as any,
  });

  assert.equal(res.status, "save_failed");
  assert.equal(res.summaryText, "- Valid summary text");
  assert.equal(res.error, "Intel 摘要数据存储故障");
});
