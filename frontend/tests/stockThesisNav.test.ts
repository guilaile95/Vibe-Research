/**
 * 个股面板 → Thesis 新建/列表 跳转预填契约
 *
 * StockThesisPanel 生成：
 *   /thesis/new?subject_type=stock&subject_id=...
 *   /thesis?subject_type=stock&subject_id=...
 *
 * ThesisNew / ThesisList 必须能从 searchParams 读出预填。
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(__dirname, "../src");

function readSrc(rel: string) {
  return readFileSync(join(srcRoot, rel), "utf8");
}

/** 与 StockThesisPanel 一致的跳转 URL 构造 */
function stockNewThesisHref(code: string) {
  return `/thesis/new?subject_type=stock&subject_id=${encodeURIComponent(code)}`;
}

function stockListThesisHref(code: string) {
  return `/thesis?subject_type=stock&subject_id=${encodeURIComponent(code)}`;
}

/** ThesisNew 初始化：从 query 读 subject_type / subject_id */
function parseThesisNewParams(search: string) {
  const sp = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return {
    subject_type: (sp.get("subject_type") as "stock" | "sector" | "theme") || "stock",
    subject_id: sp.get("subject_id") || "",
  };
}

/** ThesisList 筛选初始化 + 成对提交 */
function parseThesisListFilters(search: string) {
  const sp = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const subjectType = sp.get("subject_type") || "";
  const subjectId = sp.get("subject_id") || "";
  const status = sp.get("status") || "";
  return { subjectType, subjectId, status };
}

function buildListApiParams(subjectType: string, subjectId: string, status: string) {
  const params: { subject_type?: string; subject_id?: string; status?: string } = {};
  if (subjectType && subjectId.trim()) {
    params.subject_type = subjectType;
    params.subject_id = subjectId.trim();
  }
  if (status) params.status = status;
  return params;
}

function filtersToSearchParams(subjectType: string, subjectId: string, status: string) {
  const next = new URLSearchParams();
  if (subjectType && subjectId.trim()) {
    next.set("subject_type", subjectType);
    next.set("subject_id", subjectId.trim());
  }
  if (status) next.set("status", status);
  return next;
}

test("StockThesisPanel 源码包含新建/查看全部预填链接", () => {
  const src = readSrc("components/stock/StockThesisPanel.tsx");
  assert.ok(
    src.includes("/thesis/new?subject_type=stock&subject_id="),
    "新建逻辑链接必须带 subject_type=stock&subject_id",
  );
  assert.ok(
    src.includes("/thesis?subject_type=stock&subject_id="),
    "查看全部链接必须带 subject_type=stock&subject_id",
  );
});

test("ThesisNew 源码使用 useSearchParams 预填 subject", () => {
  const src = readSrc("pages/ThesisNew.tsx");
  assert.ok(src.includes("useSearchParams"), "ThesisNew 必须 useSearchParams");
  assert.ok(src.includes('searchParams.get("subject_type")'), "必须读取 subject_type");
  assert.ok(src.includes('searchParams.get("subject_id")'), "必须读取 subject_id");
  assert.ok(!/market\s*[:=]/.test(src.split("const body")[1]?.slice(0, 400) ?? ""), "创建 body 不应再含 market");
  assert.ok(src.includes("市场由股票代码自动识别"), "应提示市场由代码自动识别");
});

test("ThesisList 源码使用 useSearchParams 初始化筛选并同步 URL", () => {
  const src = readSrc("pages/ThesisList.tsx");
  assert.ok(src.includes("useSearchParams"), "ThesisList 必须 useSearchParams");
  assert.ok(src.includes("setSearchParams"), "修改筛选时必须同步 URL");
  assert.ok(src.includes("subject_type") && src.includes("subject_id"), "必须处理 subject 筛选");
});

test("个股新建逻辑入口：600519 预填解析正确", () => {
  const href = stockNewThesisHref("600519");
  assert.equal(href, "/thesis/new?subject_type=stock&subject_id=600519");
  const form = parseThesisNewParams(href.split("?")[1]);
  assert.equal(form.subject_type, "stock");
  assert.equal(form.subject_id, "600519");
});

test("个股查看全部入口：列表仅当前股票筛选", () => {
  const href = stockListThesisHref("301091");
  assert.equal(href, "/thesis?subject_type=stock&subject_id=301091");
  const filters = parseThesisListFilters(href.split("?")[1]);
  assert.equal(filters.subjectType, "stock");
  assert.equal(filters.subjectId, "301091");
  const apiParams = buildListApiParams(filters.subjectType, filters.subjectId, filters.status);
  assert.deepEqual(apiParams, { subject_type: "stock", subject_id: "301091" });
});

test("subject_id 与 subject_type 必须成对；单独一侧不提交", () => {
  assert.deepEqual(buildListApiParams("", "600519", ""), {});
  assert.deepEqual(buildListApiParams("stock", "", ""), {});
  assert.deepEqual(buildListApiParams("stock", "600519", "active"), {
    subject_type: "stock",
    subject_id: "600519",
    status: "active",
  });
});

test("筛选条件同步到 URL 后可还原", () => {
  const sp = filtersToSearchParams("stock", "688256", "active");
  assert.equal(sp.get("subject_type"), "stock");
  assert.equal(sp.get("subject_id"), "688256");
  assert.equal(sp.get("status"), "active");
  const restored = parseThesisListFilters(sp.toString());
  assert.equal(restored.subjectType, "stock");
  assert.equal(restored.subjectId, "688256");
  assert.equal(restored.status, "active");
});
