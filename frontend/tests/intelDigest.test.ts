import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDigestSourceRefs,
  buildDigestInputItems,
  shouldSaveDigest,
  digestStatusBadge,
  isSectorMatch,
} from "../src/lib/intelDigestView.ts";

import {
  runIntelDigestGeneration,
  type RunIntelDigestGenerationParams,
} from "../src/lib/intelDigestOrchestrator.ts";
import type { Industry, IntelDigestSaveIn, IntelDigestSaveResult } from "../src/lib/api/types.ts";

const mockIndustry: Industry = {
  key: "ai",
  name: "AI 人工智能",
  accent: "#f97316",
  items: [
    { title: "AI Chip Innovation Announced", zh: "AI 芯片重大突破", source: "TechCrunch", time: "2026-07-31", url: "https://example.com/ai-chip?utm_source=rss" },
  ],
};

test("buildDigestSourceRefs and buildDigestInputItems slice top 25 items", () => {
  const mockItems = Array.from({ length: 30 }, (_, i) => ({
    title: `Title ${i}`,
    source: `Source ${i}`,
    url: `https://example.com/${i}`,
    time: `2026-07-31 10:0${i % 10}`,
    zh: `中文 ${i}`,
  }));

  const refs = buildDigestSourceRefs(mockItems);
  assert.equal(refs.length, 25);
  assert.equal(refs[0].title, "中文 0");
  assert.equal(refs[0].url, "https://example.com/0");

  const inputs = buildDigestInputItems(mockItems);
  assert.equal(inputs.length, 25);
  assert.equal(inputs[0].published_at, "2026-07-31 10:00");
  assert.equal(inputs[0].title, "中文 0");
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

// Orchestrator unit tests covering Head Review Section 7 contracts
test("orchestrator: stream resolve after complete calls saveApi and returns saved status", async () => {
  let saveCalled = false;
  let savedPayload: IntelDigestSaveIn | null = null;

  const mockSaveApi = async (payload: IntelDigestSaveIn): Promise<IntelDigestSaveResult> => {
    saveCalled = true;
    savedPayload = payload;
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
    saveApi: mockSaveApi,
    chatStreamFn: mockChatStream as any,
  });

  assert.equal(saveCalled, true);
  assert.equal(res.status, "saved");
  assert.equal(res.summaryText, "- AI 芯片突破");
  assert.equal(savedPayload?.sector_key, "ai");
});

test("orchestrator: stream error does NOT call saveApi", async () => {
  let saveCalled = false;
  const mockSaveApi = async (): Promise<IntelDigestSaveResult> => {
    saveCalled = true;
    return { digest: null, deduped: false };
  };

  const mockErrStream = async () => {
    throw new Error("后端响应流意外中断");
  };

  const controller = new AbortController();
  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: mockSaveApi,
    chatStreamFn: mockErrStream as any,
  });

  assert.equal(saveCalled, false);
  assert.equal(res.status, "error");
  assert.equal(res.error, "后端响应流意外中断");
});

test("orchestrator: empty stream content does NOT call saveApi", async () => {
  let saveCalled = false;
  const mockSaveApi = async (): Promise<IntelDigestSaveResult> => {
    saveCalled = true;
    return { digest: null, deduped: false };
  };

  const mockEmptyStream = async () => ({ content: "   \n  ", trace: [], rounds: 1 });

  const controller = new AbortController();
  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: mockSaveApi,
    chatStreamFn: mockEmptyStream as any,
  });

  assert.equal(saveCalled, false);
  assert.equal(res.status, "empty");
});

test("orchestrator: AbortSignal abort returns cancelled and does NOT call saveApi", async () => {
  let saveCalled = false;
  const mockSaveApi = async (): Promise<IntelDigestSaveResult> => {
    saveCalled = true;
    return { digest: null, deduped: false };
  };

  const controller = new AbortController();
  controller.abort(); // Aborted before starting

  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: mockSaveApi,
  });

  assert.equal(saveCalled, false);
  assert.equal(res.status, "cancelled");
});

test("orchestrator: abort during stream resolution cancels saveApi call", async () => {
  let saveCalled = false;
  const controller = new AbortController();

  const mockChatStream = async () => {
    controller.abort(); // Aborted during stream execution
    return { content: "- Summary text", trace: [], rounds: 1 };
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
});

test("orchestrator: superseded generation ID prevents saving", async () => {
  let saveCalled = false;
  let currentGenId = 1;

  const mockChatStream = async () => {
    currentGenId = 2; // Superseded by a newer request during stream
    return { content: "- Summary text", trace: [], rounds: 1 };
  };

  const controller = new AbortController();
  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => currentGenId,
    isMounted: () => true,
    saveApi: async () => { saveCalled = true; return { digest: null, deduped: false }; },
    chatStreamFn: mockChatStream as any,
  });

  assert.equal(saveCalled, false);
  assert.equal(res.status, "superseded");
});

test("orchestrator: save API failure retains generated markdown text and returns save_failed status", async () => {
  const mockChatStream = async () => ({ content: "- Valid summary text", trace: [], rounds: 1 });
  const mockFailingSaveApi = async (): Promise<IntelDigestSaveResult> => {
    throw new Error("Intel 摘要数据存储故障");
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
