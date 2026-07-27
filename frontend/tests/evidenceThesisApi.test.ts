/**
 * 投资逻辑与证据账本：API 客户端单元测试
 *
 * 覆盖：
 * - API 请求方法、路径、body
 * - expected_revision 传递
 * - 409 冲突文案（ApiError.status === 409）
 * - archived 禁用逻辑（thesisArchive 路径含 confirm=true & expected_revision）
 * - diff 数据转换（路径 from/to 查询参数）
 * - 删除确认（confirm=true 查询参数）
 * - source_date 可空（null 不被字符串化成 "null"）
 * - accessed_at 必填（前端页面层校验，本测试只验证 API 不再补默认值）
 *
 * 风格对齐 myReportsApi.test.ts / sectorResearchApi.test.ts：拦截 fetch，
 * 记录请求并返回 mock 响应，不实际出站。
 */
import assert from "node:assert/strict";
import test from "node:test";

// ---------------------------------------------------------------------------
// fetch 拦截：记录所有 /api 请求，按需返回 mock 响应
// ---------------------------------------------------------------------------
type RecordedReq = {
  url: string;
  method: string;
  body: string | null;
  headers: Record<string, string>;
};

const requests: RecordedReq[] = [];
const realFetch = globalThis.fetch;

type MockRule = {
  match: (url: string, method: string) => boolean;
  status: number;
  body: unknown;
};

const mockRules: MockRule[] = [];

function defaultResponse(url: string, method: string) {
  for (const rule of mockRules) {
    if (rule.match(url, method)) {
      return { status: rule.status, body: rule.body };
    }
  }
  // 默认 200 + 空 data 包络
  return { status: 200, body: { data: {} } };
}

globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const method = (init?.method || "GET").toUpperCase();
  const headers: Record<string, string> = {};
  if (init?.headers) {
    const h = init.headers as Record<string, string>;
    for (const k of Object.keys(h)) headers[k] = String(h[k]);
  }
  requests.push({
    url,
    method,
    body: typeof init?.body === "string" ? init.body : null,
    headers,
  });
  const { status, body } = defaultResponse(url, method);
  const bodyStr = JSON.stringify(body);
  return new Response(bodyStr, {
    status,
    headers: { "Content-Type": "application/json" },
  });
}) as unknown as typeof fetch;

// 模拟 localStorage（authHeaders 会读取）
const _store: Record<string, string> = {};
(globalThis as any).localStorage = {
  getItem: (k: string) => _store[k] ?? null,
  setItem: (k: string, v: string) => { _store[k] = v; },
  removeItem: (k: string) => { delete _store[k]; },
};

// ---------------------------------------------------------------------------
// 导入被测代码（运行时客户端）
// ---------------------------------------------------------------------------
const { api, ApiError, unwrapApiPayload } = await import("../src/lib/api.ts");

function reset() {
  requests.length = 0;
  mockRules.length = 0;
}

function lastReq(): RecordedReq {
  return requests[requests.length - 1];
}

function mockOnce(match: (url: string, method: string) => boolean, status: number, body: unknown) {
  mockRules.push({ match, status, body });
}

// ---------------------------------------------------------------------------
// 测试
// ---------------------------------------------------------------------------

test("evidenceList 路径与方法（GET，无 /api 前缀重复）", async () => {
  reset();
  await api.evidenceList({ subject_type: "stock", subject_id: "600519", limit: 10, offset: 5 });
  const r = lastReq();
  assert.equal(r.method, "GET");
  assert.ok(r.url.includes("/api/evidence"), `url=${r.url}`);
  assert.ok(!r.url.includes("/api/api"), "不得双 /api 前缀");
  assert.ok(r.url.includes("subject_type=stock"));
  assert.ok(r.url.includes("subject_id=600519"));
  assert.ok(r.url.includes("limit=10"));
  assert.ok(r.url.includes("offset=5"));
});

test("evidenceCreate 使用 POST 并以 JSON body 提交", async () => {
  reset();
  const body = {
    subject_type: "stock" as const,
    subject_id: "600519",
    evidence_type: "news" as const,
    claim: "Q3 营收 +20%",
    source_title: "公告",
    source_url: "https://example.com",
    source_date: "2025-10-28",
    accessed_at: "2025-10-28T10:00:00Z",
    classification: "fact" as const,
    confidence: "high" as const,
  };
  await api.evidenceCreate(body);
  const r = lastReq();
  assert.equal(r.method, "POST");
  assert.equal(r.url, "/api/evidence");
  assert.equal(r.headers["Content-Type"], "application/json");
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.claim, "Q3 营收 +20%");
  assert.equal(parsed.subject_type, "stock");
});

test("evidenceGet 路径含 id", async () => {
  reset();
  await api.evidenceGet("ev-1");
  const r = lastReq();
  assert.equal(r.method, "GET");
  assert.equal(r.url, "/api/evidence/ev-1");
});

test("evidenceUpdate 使用 PUT 且 body 为完整 EvidenceUpdateInput", async () => {
  reset();
  const body = {
    evidence_type: "news" as const,
    claim: "new claim",
    source_title: "src",
    source_url: "https://example.com",
    source_date: "2024-11-15",
    accessed_at: "2024-11-15T10:00:00Z",
    classification: "fact" as const,
    confidence: "high" as const,
  };
  await api.evidenceUpdate("ev-1", body);
  const r = lastReq();
  assert.equal(r.method, "PUT");
  assert.equal(r.url, "/api/evidence/ev-1");
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.claim, "new claim");
  assert.equal(parsed.evidence_type, "news");
  assert.equal(parsed.source_date, "2024-11-15");
  assert.equal(parsed.classification, "fact");
  assert.equal(parsed.confidence, "high");
  assert.equal(parsed.subject_type, undefined, "update body 不得含 subject_type");
  assert.equal(parsed.subject_id, undefined, "update body 不得含 subject_id");
});

test("thesisCreate body 不含 market/status（由服务端决定）", async () => {
  reset();
  const body = {
    subject_type: "stock" as const,
    subject_id: "600519",
    title: "T",
    summary: "S",
    core_claims: ["c1"],
    catalysts: [] as string[],
    risks: [] as string[],
    invalidation_conditions: [] as string[],
    change_summary: "init",
  };
  await api.thesisCreate(body);
  const parsed = JSON.parse(lastReq().body as string);
  assert.equal(parsed.market, undefined);
  assert.equal(parsed.status, undefined);
  assert.equal(parsed.subject_type, "stock");
  assert.equal(parsed.subject_id, "600519");
});

test("evidenceDelete 路径包含 confirm=true 查询参数", async () => {
  reset();
  await api.evidenceDelete("ev-1");
  const r = lastReq();
  assert.equal(r.method, "DELETE");
  assert.ok(r.url.includes("/api/evidence/ev-1"));
  assert.ok(r.url.includes("confirm=true"), "必须带 confirm=true 防误调用");
});

test("thesisCreate 使用 POST", async () => {
  reset();
  const body = {
    subject_type: "stock",
    subject_id: "600519",
    title: "贵州茅台增长逻辑",
    summary: "summary",
    core_claims: ["c1"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    change_summary: "init",
  };
  await api.thesisCreate(body);
  const r = lastReq();
  assert.equal(r.method, "POST");
  assert.equal(r.url, "/api/thesis");
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.title, "贵州茅台增长逻辑");
});

test("thesisList 支持 status 筛选并拼接查询参数", async () => {
  reset();
  await api.thesisList({ status: "archived", limit: 50, offset: 0 });
  const r = lastReq();
  assert.equal(r.method, "GET");
  assert.ok(r.url.includes("/api/thesis"));
  assert.ok(r.url.includes("status=archived"));
  assert.ok(r.url.includes("limit=50"));
});

test("thesisUpdate 携带 expected_revision（乐观并发）", async () => {
  reset();
  const body = {
    title: "t2",
    summary: "s2",
    status: "active" as const,
    core_claims: [],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    expected_revision: 3,
    change_summary: "update",
  };
  await api.thesisUpdate("th-1", body);
  const r = lastReq();
  assert.equal(r.method, "PUT");
  assert.equal(r.url, "/api/thesis/th-1");
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.expected_revision, 3, "expected_revision 必须随 body 提交");
});

test("thesisArchive 路径含 confirm=true 与 expected_revision（archived 冻结）", async () => {
  reset();
  await api.thesisArchive("th-1", 5, "归档：不再追踪");
  const r = lastReq();
  assert.equal(r.method, "DELETE");
  assert.ok(r.url.includes("/api/thesis/th-1"));
  assert.ok(r.url.includes("confirm=true"), "归档必须显式 confirm=true");
  assert.ok(r.url.includes("expected_revision=5"), "归档必须携带 expected_revision");
  assert.ok(r.url.includes("change_summary="), "change_summary 应作为查询参数");
});

test("thesisRevisions 与 thesisRevision 路径", async () => {
  reset();
  await api.thesisRevisions("th-1");
  assert.equal(lastReq().url, "/api/thesis/th-1/revisions");
  await api.thesisRevision("th-1", 2);
  assert.equal(lastReq().url, "/api/thesis/th-1/revisions/2");
});

test("thesisDiff 路径包含 from/to 查询参数（diff 数据转换入口）", async () => {
  reset();
  await api.thesisDiff("th-1", 1, 2);
  const r = lastReq();
  assert.equal(r.method, "GET");
  assert.ok(r.url.includes("/api/thesis/th-1/diff"));
  assert.ok(r.url.includes("from=1"));
  assert.ok(r.url.includes("to=2"));
});

test("thesisLinkEvidence POST，body 含 evidence_id/stance/expected_revision", async () => {
  reset();
  await api.thesisLinkEvidence("th-1", {
    evidence_id: "ev-1",
    stance: "support",
    expected_revision: 1,
    change_summary: "link",
  });
  const r = lastReq();
  assert.equal(r.method, "POST");
  assert.equal(r.url, "/api/thesis/th-1/evidence");
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.evidence_id, "ev-1");
  assert.equal(parsed.stance, "support");
  assert.equal(parsed.expected_revision, 1);
});

test("thesisUpdateStance PUT，路径含 evidence_id", async () => {
  reset();
  await api.thesisUpdateStance("th-1", "ev-1", {
    stance: "oppose",
    expected_revision: 2,
    change_summary: "stance change",
  });
  const r = lastReq();
  assert.equal(r.method, "PUT");
  assert.equal(r.url, "/api/thesis/th-1/evidence/ev-1");
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.stance, "oppose");
  assert.equal(parsed.expected_revision, 2);
});

test("thesisUnlinkEvidence DELETE，查询参数含 expected_revision", async () => {
  reset();
  await api.thesisUnlinkEvidence("th-1", "ev-1", 3, "unlink");
  const r = lastReq();
  assert.equal(r.method, "DELETE");
  assert.ok(r.url.includes("/api/thesis/th-1/evidence/ev-1"));
  assert.ok(r.url.includes("expected_revision=3"));
  assert.ok(r.url.includes("change_summary=unlink"));
});

test("409 冲突：ApiError.status === 409 且 detail 文案符合设计", async () => {
  reset();
  // 后端返回 409 + {detail, current_revision}
  mockOnce(
    (url) => url.includes("/api/thesis/th-conflict"),
    409,
    { detail: "投资逻辑已发生变化，请重新加载后重试", current_revision: 4 },
  );
  await assert.rejects(
    api.thesisUpdate("th-conflict", {
      title: "x", summary: "", status: "active",
      core_claims: [], catalysts: [], risks: [], invalidation_conditions: [],
      expected_revision: 99, change_summary: "x",
    } as any),
    (err: unknown) => {
      assert.ok(err instanceof ApiError, "应抛 ApiError");
      assert.equal((err as ApiError).status, 409);
      assert.match((err as ApiError).message, /投资逻辑已发生变化/);
      return true;
    },
  );
});

test("archived mutation 返回 409 时 ApiError.message 包含冻结文案", async () => {
  reset();
  mockOnce(
    (url, method) => url.includes("/api/thesis/th-archived") && method === "PUT",
    409,
    { detail: "已归档的投资逻辑不可修改" },
  );
  await assert.rejects(
    api.thesisUpdate("th-archived", {
      title: "x", summary: "", status: "active",
      core_claims: [], catalysts: [], risks: [], invalidation_conditions: [],
      expected_revision: 1, change_summary: "x",
    } as any),
    (err: unknown) => {
      assert.equal((err as ApiError).status, 409);
      assert.match((err as ApiError).message, /已归档/);
      return true;
    },
  );
});

test("500 安全错误：ApiError 不暴露 SQL/路径/traceback", async () => {
  reset();
  mockOnce(
    (url) => url.includes("/api/evidence/ev-broken"),
    500,
    { detail: "数据库完整性校验失败" },
  );
  await assert.rejects(
    api.evidenceGet("ev-broken"),
    (err: unknown) => {
      assert.equal((err as ApiError).status, 500);
      const msg = (err as ApiError).message;
      assert.ok(!/\.db/i.test(msg), "不得暴露数据库文件路径");
      assert.ok(!/traceback/i.test(msg), "不得暴露 traceback");
      assert.ok(!/sqlite/i.test(msg), "不得暴露 SQLite 内部错误文本");
      return true;
    },
  );
});

test("unwrapApiPayload 解包 data 字段（与后端 {data: ...} 包络一致）", () => {
  const out = unwrapApiPayload({ data: { id: "x" } });
  assert.deepEqual(out, { id: "x" });
  // 没有 data 字段时原样返回
  const out2 = unwrapApiPayload({ detail: "err" });
  assert.deepEqual(out2, { detail: "err" });
});

test("source_date 可空：null 应原样序列化为 null（不被字符串化）", async () => {
  reset();
  await api.evidenceCreate({
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "news",
    claim: "c",
    source_title: "t",
    source_url: null,
    source_date: null, // 可空
    accessed_at: "2025-10-28T10:00:00Z",
    classification: "fact",
    confidence: "high",
  });
  const r = lastReq();
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.source_date, null, "source_date=null 必须保留为 null");
  assert.equal(parsed.source_url, null);
});

test("accessed_at 必填：API 客户端不补默认值，由页面层强制校验", async () => {
  reset();
  // 故意传空字符串，客户端应原样透传（页面层负责校验拒绝）
  await api.evidenceCreate({
    subject_type: "stock",
    subject_id: "600519",
    evidence_type: "news",
    claim: "c",
    source_title: "t",
    source_url: null,
    source_date: null,
    accessed_at: "",
    classification: "fact",
    confidence: "high",
  } as any);
  const r = lastReq();
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.accessed_at, "", "客户端不补默认值，原样透传空串");
});

test("分页边界：limit=200 与 offset=0 路径正确", async () => {
  reset();
  await api.evidenceList({ limit: 200, offset: 0 });
  const r = lastReq();
  assert.ok(r.url.includes("limit=200"));
  assert.ok(r.url.includes("offset=0"));
});

test("跨 subject 防护：linkEvidence 客户端不补 subject，由后端校验 400/422", async () => {
  reset();
  // 客户端只传 evidence_id + stance + expected_revision；subject 一致性由后端校验
  await api.thesisLinkEvidence("th-1", {
    evidence_id: "ev-other-subject",
    stance: "support",
    expected_revision: 1,
    change_summary: "link",
  });
  const r = lastReq();
  const parsed = JSON.parse(r.body as string);
  assert.equal(parsed.evidence_id, "ev-other-subject");
  assert.ok(!("subject_type" in parsed), "客户端不携带 subject_type，由后端权威校验");
});

// 还原 fetch（避免污染其它测试）
test("teardown: restore fetch", () => {
  globalThis.fetch = realFetch;
  assert.ok(true);
});
