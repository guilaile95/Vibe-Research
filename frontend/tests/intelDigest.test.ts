import assert from "node:assert/strict";
import test from "node:test";

import {
  prepareDigestItems,
  shouldSaveDigest,
  digestStatusBadge,
  formatShanghaiTime,
  isSectorMatch,
  isValidHttpUrl,
  isValidTimezoneAwareIso,
  resolvePublishedAt,
  toShanghaiIsoFromTs,
} from "../src/lib/intelDigestView.ts";

import {
  runIntelDigestGeneration,
} from "../src/lib/intelDigestOrchestrator.ts";
import type { Industry, IntelDigestSaveIn, IntelDigestSaveResult } from "../src/lib/api/types.ts";

const mockIndustry: Industry = {
  key: "ai",
  name: "AI 人工智能",
  accent: "#f97316",
  total: 2,
  items: [
    {
      title: "AI Chip Innovation Announced",
      zh: "AI 芯片重大突破",
      source: "TechCrunch",
      time: "07-31 10:00",
      published_at: "2026-07-31T10:00:00+08:00",
      url: "https://example.com/ai-chip?utm_source=rss",
    },
    {
      title: "Robotics Update",
      zh: "机器人突破",
      source: "Reuters",
      time: "07-30 10:00",
      published_at: "2026-07-30T10:00:00+08:00",
      url: "https://example.com/robotics",
    },
  ],
};

test("prepareDigestItems: canonical sorting, deterministic prompt, input_items, and source_refs", () => {
  const itemsAsc = [...mockIndustry.items];
  const itemsDesc = [...mockIndustry.items].reverse();

  const resAsc = prepareDigestItems(itemsAsc);
  const resDesc = prepareDigestItems(itemsDesc);

  assert.deepEqual(resAsc.canonicalItems, resDesc.canonicalItems);
  assert.equal(resAsc.promptContext, resDesc.promptContext);
  assert.deepEqual(resAsc.inputItems, resDesc.inputItems);
  assert.deepEqual(resAsc.sourceRefs, resDesc.sourceRefs);
  assert.equal(resAsc.status, "normal");
  assert.equal(resAsc.droppedCount, 0);
  assert.ok(resAsc.inputItems[0].published_at?.includes("T"));
  assert.ok(resAsc.inputItems[0].published_at?.includes("+") || resAsc.inputItems[0].published_at?.endsWith("Z"));
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

// ── Round 4: invalid item filtering ──────────────────────────────────────────

test("prepareDigestItems: undated items are filtered out", () => {
  const items = [
    { title: "Has date", source: "S", url: "https://a.com/1", published_at: "2026-07-31T10:00:00+08:00" },
    { title: "No date", source: "S", url: "https://a.com/2", time: "—" },
    { title: "Display time only", source: "S", url: "https://a.com/3", time: "07-31 10:00" },
  ];
  const res = prepareDigestItems(items as any);
  assert.equal(res.canonicalItems.length, 1);
  assert.equal(res.canonicalItems[0].title, "Has date");
  assert.equal(res.droppedCount, 2);
  assert.equal(res.status, "partial");
});

test("prepareDigestItems: items without valid URL are filtered", () => {
  const items = [
    { title: "OK", source: "S", url: "https://a.com/1", published_at: "2026-07-31T10:00:00+08:00" },
    { title: "No URL", source: "S", url: "", published_at: "2026-07-31T10:00:00+08:00" },
    { title: "Bad scheme", source: "S", url: "ftp://a.com/x", published_at: "2026-07-31T10:00:00+08:00" },
    { title: "No host", source: "S", url: "https://", published_at: "2026-07-31T10:00:00+08:00" },
  ];
  const res = prepareDigestItems(items as any);
  assert.equal(res.canonicalItems.length, 1);
  assert.equal(res.droppedCount, 3);
  assert.equal(res.status, "partial");
});

test("prepareDigestItems: old cache with ts>0 enters normally", () => {
  // 2026-07-31 10:00:00+08:00 = 1753927200? Let's compute from known value
  // Use a fixed ts that toShanghaiIsoFromTs will convert
  const ts = Math.floor(Date.UTC(2026, 6, 31, 2, 0, 0) / 1000); // 02:00 UTC = 10:00 Shanghai
  const items = [
    { title: "Old cache news", source: "RSS", url: "https://example.com/old", ts, time: "07-31 10:00" },
  ];
  const res = prepareDigestItems(items as any);
  assert.equal(res.canonicalItems.length, 1);
  assert.equal(res.status, "normal");
  assert.equal(res.droppedCount, 0);
  assert.ok(isValidTimezoneAwareIso(res.canonicalItems[0].published_at));
  assert.equal(res.canonicalItems[0].published_at, toShanghaiIsoFromTs(ts));
});

test("prepareDigestItems: old cache with only display time (no ts) is filtered", () => {
  const items = [
    { title: "Display only", source: "S", url: "https://a.com/1", time: "07-31 10:00" },
    { title: "Dash time", source: "S", url: "https://a.com/2", time: "—" },
  ];
  const res = prepareDigestItems(items as any);
  assert.equal(res.canonicalItems.length, 0);
  assert.equal(res.status, "unavailable");
  assert.equal(res.droppedCount, 2);
});

test("prepareDigestItems: never fabricates hardcoded 2026-07-31 date", () => {
  const items = [
    { title: "No date", source: "S", url: "https://a.com/1" },
  ];
  const res = prepareDigestItems(items as any);
  assert.equal(res.canonicalItems.length, 0);
  // Ensure the old hardcode is gone from any output
  const blob = JSON.stringify(res);
  assert.equal(blob.includes("2026-07-31T10:00:00+08:00"), false);
});

test("prepareDigestItems: all valid → status=normal; partial drop → partial; all invalid → unavailable", () => {
  const allValid = prepareDigestItems(mockIndustry.items);
  assert.equal(allValid.status, "normal");

  const partial = prepareDigestItems([
    ...mockIndustry.items,
    { title: "Bad", source: "S", url: "", time: "—" },
  ] as any);
  assert.equal(partial.status, "partial");
  assert.ok(partial.droppedCount >= 1);

  const none = prepareDigestItems([
    { title: "X", source: "S", url: "not-a-url" },
  ] as any);
  assert.equal(none.status, "unavailable");
  assert.equal(none.canonicalItems.length, 0);
});

test("isValidTimezoneAwareIso rejects naive dates", () => {
  assert.equal(isValidTimezoneAwareIso("2026-07-31"), false);
  assert.equal(isValidTimezoneAwareIso("2026-07-31T10:00:00"), false);
  assert.equal(isValidTimezoneAwareIso("2026-07-31T10:00:00+08:00"), true);
  assert.equal(isValidTimezoneAwareIso("2026-07-31T02:00:00Z"), true);
  assert.equal(isValidHttpUrl("https://"), false);
  assert.equal(isValidHttpUrl("https://example.com/a"), true);
});

test("formatShanghaiTime renders timezone-aware ISO values in Beijing time", () => {
  assert.equal(formatShanghaiTime("2026-08-29T03:00:00Z"), "2026-08-29 11:00");
  assert.equal(formatShanghaiTime("2026-08-29T11:00:00+08:00"), "2026-08-29 11:00");
  assert.equal(formatShanghaiTime("2026-08-29 11:00"), "2026-08-29 11:00");
  assert.equal(formatShanghaiTime("invalid-time"), "invalid-time");
  assert.equal(formatShanghaiTime(null), "未知");
});

test("resolvePublishedAt never uses display time fields", () => {
  assert.equal(resolvePublishedAt({ time: "07-31 10:00" }), null);
  assert.equal(resolvePublishedAt({ time: "—" }), null);
  assert.equal(resolvePublishedAt({ time: "2 小时前" }), null);
  assert.equal(
    resolvePublishedAt({ published_at: "2026-07-31T10:00:00+08:00" }),
    "2026-07-31T10:00:00+08:00"
  );
});

test("fingerprint stability: undated items produce identical empty canonical results across runs", () => {
  const undated = [
    { title: "No date article", source: "Wire", url: "https://example.com/undated" },
  ];
  const r1 = prepareDigestItems(undated as any);
  // Simulate "time passing" — still no fabricated dates
  const r2 = prepareDigestItems(undated as any);
  assert.deepEqual(r1.canonicalItems, r2.canonicalItems);
  assert.deepEqual(r1.inputItems, r2.inputItems);
  assert.equal(r1.status, "unavailable");
  assert.equal(r2.status, "unavailable");
});

// ── Orchestrator unit tests ──────────────────────────────────────────────────

test("orchestrator: transitions phase to 'generating' then 'saving' before saveApi", async () => {
  let saveCalled = false;
  let savedStatus: string | undefined;
  const phases: string[] = [];

  const mockSaveApi = async (payload: IntelDigestSaveIn): Promise<IntelDigestSaveResult> => {
    saveCalled = true;
    savedStatus = payload.status;
    return {
      digest: {
        digest_id: "idg_123",
        digest_date: "2026-07-31",
        sector_key: "ai",
        sector_name: "AI 人工智能",
        status: payload.status,
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
  assert.equal(savedStatus, "normal");
  assert.deepEqual(phases, ["generating", "saving"]);
});

test("orchestrator: AbortError with accText → cancelled, not saved, saveApi not called", async () => {
  let saveCalled = false;
  const controller = new AbortController();

  const mockChatStream = async (_msg: any, _ctx: any, handlers: any) => {
    handlers.onDelta?.("- Partial delta text already accumulated");
    // Proper AbortError (name === "AbortError"), with signal also aborted
    controller.abort();
    const err = new Error("The operation was aborted");
    err.name = "AbortError";
    throw err;
  };

  const res = await runIntelDigestGeneration({
    industry: mockIndustry,
    signal: controller.signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: async () => {
      saveCalled = true;
      return { digest: null, deduped: false };
    },
    chatStreamFn: mockChatStream as any,
  });

  assert.equal(saveCalled, false);
  assert.equal(res.status, "cancelled");
  assert.equal(res.summaryText, "- Partial delta text already accumulated");
  // Must NOT be marked as saved
  assert.notEqual(res.status, "saved");
  assert.notEqual(res.status, "deduped");
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

test("orchestrator: all invalid items → chatStream call count 0, save call count 0", async () => {
  let chatCalls = 0;
  let saveCalls = 0;

  const emptyIndustry: Industry = {
    key: "ai",
    name: "AI 人工智能",
    accent: "#f97316",
    total: 2,
    items: [
      { title: "No date", source: "S", time: "—", url: "https://a.com/1" },
      { title: "No url", source: "S", published_at: "2026-07-31T10:00:00+08:00", url: "" },
    ],
  };

  const res = await runIntelDigestGeneration({
    industry: emptyIndustry,
    signal: new AbortController().signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: async () => {
      saveCalls++;
      return { digest: null, deduped: false };
    },
    chatStreamFn: (async () => {
      chatCalls++;
      return { content: "should not run", trace: [], rounds: 0 };
    }) as any,
  });

  assert.equal(chatCalls, 0);
  assert.equal(saveCalls, 0);
  assert.equal(res.status, "unavailable");
  assert.ok(res.error?.includes("没有可用于摘要的有效带日期资讯"));
});

test("orchestrator: partial materials POST with status=partial (not hard-coded normal)", async () => {
  let postedStatus: string | undefined;

  const mixedIndustry: Industry = {
    key: "ai",
    name: "AI 人工智能",
    accent: "#f97316",
    total: 2,
    items: [
      {
        title: "Valid",
        source: "S",
        url: "https://example.com/v",
        published_at: "2026-07-31T10:00:00+08:00",
      },
      {
        title: "Invalid undated",
        source: "S",
        url: "https://example.com/bad",
        time: "—",
      },
    ],
  };

  const res = await runIntelDigestGeneration({
    industry: mixedIndustry,
    signal: new AbortController().signal,
    generationId: 1,
    getCurrentGenerationId: () => 1,
    isMounted: () => true,
    saveApi: async (payload) => {
      postedStatus = payload.status;
      return {
        digest: {
          digest_id: "idg_p",
          digest_date: "2026-07-31",
          sector_key: "ai",
          sector_name: "AI",
          status: payload.status,
          summary_text: payload.summary_text,
          source_refs: [],
          input_fingerprint: "fp",
          generated_at: "2026-07-31T10:00:00+08:00",
          created_at: "2026-07-31T10:00:00+08:00",
        },
        deduped: false,
      };
    },
    chatStreamFn: (async () => ({ content: "- Point", trace: [], rounds: 1 })) as any,
  });

  assert.equal(res.status, "saved");
  assert.equal(postedStatus, "partial");
  assert.equal(res.materialStatus, "partial");
});
