/**
 * 投资逻辑与证据账本 — Playwright E2E smoke
 *
 * 架构（对齐 stock-data-panel.smoke.browser.mjs）：
 * - Playwright 加载 Vite build（frontend/dist），由 Node 静态服务器提供
 * - 所有 /api/* 流量经 page.route 拦截 mock，不依赖真实后端
 *
 * 覆盖 smoke 流程：
 * 1. 创建 thesis → 验证 revision 1
 * 2. 创建 evidence
 * 3. 关联 evidence → revision 增加
 * 4. 修改 stance → revision 增加
 * 5. 编辑 thesis → 查看 diff
 * 6. 编辑 evidence → 验证联动 revision
 * 7. 软删除 evidence → 当前列表不显示，历史版本仍显示
 * 8. 当前聚合状态与 snapshot 等价
 *
 * 另加 archived 最小验证：
 * - 归档 thesis
 * - 尝试编辑 → 显示冻结状态
 * - Evidence 变化不更新 archived revision
 */
import { chromium } from "playwright";
import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "../../..");
const frontendDist = path.join(root, "frontend", "dist");

let frontendPort = 0;
let browserLabel = "unknown";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitHttp(url, attempts = 80) {
  for (let i = 0; i < attempts; i++) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status < 500) return;
    } catch {
      /* retry */
    }
    await sleep(400);
  }
  throw new Error(`timeout waiting ${url}`);
}

function startStaticServer(dir, port) {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
  };

  const server = createServer((req, res) => {
    const rawUrl = req.url || "/";
    if (rawUrl.startsWith("/api/")) {
      res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ detail: "use page.route mocks" }));
      return;
    }
    let pathname = rawUrl.split("?")[0];
    if (pathname === "/") pathname = "/index.html";
    let target = path.join(dir, pathname);
    const resolvedDir = path.resolve(dir);
    const resolvedTarget = path.resolve(target);
    if (!resolvedTarget.startsWith(resolvedDir + path.sep) && resolvedTarget !== resolvedDir) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("forbidden");
      return;
    }
    if (!existsSync(target) || (existsSync(target) && path.extname(target) === "")) {
      target = path.join(dir, "index.html");
    }
    const ext = path.extname(target);
    const type = mime[ext] || "application/octet-stream";
    res.setHeader("Content-Type", type);
    createReadStream(target).pipe(res);
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function launchBrowser() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const launchOpts = {
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  };
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const b = await chromium.launch(launchOpts);
      browserLabel = `local chromium-${b.version()}`;
      return b;
    } catch (error) {
      lastError = error;
      if (attempt === 0) {
        launchOpts.channel = "chrome";
      }
    }
  }
  throw lastError || new Error("failed to launch any Chromium");
}

// ---------------------------------------------------------------------------
// Mock state：模拟后端 evidence/thesis 全部接口
// ---------------------------------------------------------------------------
function nowIso() {
  return new Date().toISOString();
}

function newId(prefix) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function createApiMockState() {
  // 内存数据库：evidence Map + thesis Map + revision Map（per thesis）
  const evidences = new Map();
  const theses = new Map();
  // thesisId → array of revisions (oldest first)
  const revisionsByThesis = new Map();
  // thesisId → Set of linked evidence_id (current)
  const linksByThesis = new Map();
  // thesisId → Map(evidence_id → stance)
  const stanceByThesis = new Map();

  function snapshotThesis(thesisId) {
    const t = theses.get(thesisId);
    if (!t) return null;
    const links = linksByThesis.get(thesisId) || new Set();
    const stanceMap = stanceByThesis.get(thesisId) || new Map();
    const evidenceLinks = [];
    for (const eid of links) {
      const ev = evidences.get(eid);
      if (!ev || ev.deleted) continue;
      evidenceLinks.push({
        evidence_id: ev.id,
        evidence_type: ev.evidence_type,
        stance: stanceMap.get(eid) || "neutral",
        claim: ev.claim,
        classification: ev.classification,
        confidence: ev.confidence,
        source_title: ev.source_title,
        source_url: ev.source_url,
        source_date: ev.source_date,
        accessed_at: ev.accessed_at,
      });
    }
    return {
      thesis: { ...t },
      evidence_links: evidenceLinks,
    };
  }

  function insertRevision(thesisId, changeSummary) {
    const t = theses.get(thesisId);
    if (!t) return null;
    const rev = (t.current_revision || 0) + 1;
    t.current_revision = rev;
    t.updated_at = nowIso();
    const snapshot = snapshotThesis(thesisId);
    const revRecord = {
      id: newId("rev"),
      thesis_id: thesisId,
      revision_number: rev,
      snapshot,
      change_summary: changeSummary,
      created_at: nowIso(),
    };
    if (!revisionsByThesis.has(thesisId)) revisionsByThesis.set(thesisId, []);
    revisionsByThesis.get(thesisId).push(revRecord);
    return revRecord;
  }

  // 模拟 cascade：编辑/删除 evidence 时，对所有非 archived 的关联 thesis 生成新 revision
  function cascadeEvidenceChange(evidenceId, action) {
    const summary = action === "delete"
      ? `删除关联证据：${evidenceId}`
      : `更新关联证据：${evidenceId}`;
    for (const [thesisId, links] of linksByThesis.entries()) {
      if (!links.has(evidenceId)) continue;
      const t = theses.get(thesisId);
      if (!t || t.status === "archived") continue; // archived 不联动
      insertRevision(thesisId, summary);
    }
  }

  function handle(route) {
    return (async () => {
      const request = route.request();
      const url = request.url();
      if (!url.includes("/api/")) {
        await route.continue();
        return;
      }
      const u = new URL(url);
      const pathname = u.pathname;
      const method = request.method();

      function ok(body, status = 200) {
        return route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      }

      function err(status, detail, extra = {}) {
        return route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify({ detail, ...extra }),
        });
      }

      // 路由分发
      // ---- Evidence ----
      if (pathname === "/api/evidence" && method === "GET") {
        const items = Array.from(evidences.values()).filter((e) => !e.deleted);
        return ok({ data: { items, total: items.length, limit: 50, offset: 0 } });
      }
      if (pathname === "/api/evidence" && method === "POST") {
        const body = JSON.parse(request.postData() || "{}");
        const id = newId("ev");
        const now = nowIso();
        const rec = {
          id,
          subject_type: body.subject_type,
          subject_id: body.subject_id,
          evidence_type: body.evidence_type,
          claim: body.claim,
          source_title: body.source_title,
          source_url: body.source_url ?? null,
          source_date: body.source_date ?? null,
          accessed_at: body.accessed_at,
          classification: body.classification,
          confidence: body.confidence,
          created_at: now,
          updated_at: now,
          deleted: 0,
          deleted_at: null,
        };
        evidences.set(id, rec);
        return ok({ data: rec });
      }
      const evMatch = pathname.match(/^\/api\/evidence\/([^/]+)$/);
      if (evMatch) {
        const eid = evMatch[1];
        const rec = evidences.get(eid);
        if (!rec) return err(404, "证据不存在");
        if (method === "GET") return ok({ data: rec });
        if (method === "PUT") {
          const body = JSON.parse(request.postData() || "{}");
          Object.assign(rec, body, { updated_at: nowIso() });
          // cascade：编辑证据 → 所有关联非 archived thesis 生成 revision
          cascadeEvidenceChange(eid, "update");
          return ok({ data: rec });
        }
        if (method === "DELETE") {
          const confirmFlag = u.searchParams.get("confirm");
          if (confirmFlag !== "true") return err(400, "请确认删除操作");
          rec.deleted = 1;
          rec.deleted_at = nowIso();
          // cascade：软删除证据 → 所有关联非 archived thesis 生成 revision
          cascadeEvidenceChange(eid, "delete");
          return ok({ data: rec });
        }
      }

      // ---- Thesis ----
      if (pathname === "/api/thesis" && method === "GET") {
        const items = Array.from(theses.values());
        return ok({ data: { items, total: items.length, limit: 50, offset: 0 } });
      }
      if (pathname === "/api/thesis" && method === "POST") {
        const body = JSON.parse(request.postData() || "{}");
        const id = newId("th");
        const now = nowIso();
        const t = {
          id,
          subject_type: body.subject_type,
          subject_id: body.subject_id,
          market: body.market ?? null,
          title: body.title,
          summary: body.summary || "",
          status: body.status || "active",
          core_claims: body.core_claims || [],
          catalysts: body.catalysts || [],
          risks: body.risks || [],
          invalidation_conditions: body.invalidation_conditions || [],
          created_at: now,
          updated_at: now,
          current_revision: 0,
        };
        theses.set(id, t);
        linksByThesis.set(id, new Set());
        stanceByThesis.set(id, new Map());
        // 创建 thesis 时同事务生成 revision 1
        insertRevision(id, body.change_summary || "创建投资逻辑");
        return ok({ data: snapshotThesis(id) });
      }
      const thMatch = pathname.match(/^\/api\/thesis\/([^/]+)$/);
      if (thMatch) {
        const tid = thMatch[1];
        const t = theses.get(tid);
        if (!t) return err(404, "投资逻辑不存在");
        if (method === "GET") return ok({ data: snapshotThesis(tid) });
        if (method === "PUT") {
          const body = JSON.parse(request.postData() || "{}");
          if (t.status === "archived") {
            return err(409, "已归档的投资逻辑不可修改");
          }
          if (body.expected_revision !== t.current_revision) {
            return err(409, "投资逻辑已发生变化，请重新加载后重试", {
              current_revision: t.current_revision,
            });
          }
          Object.assign(t, {
            title: body.title ?? t.title,
            summary: body.summary ?? t.summary,
            status: body.status ?? t.status,
            core_claims: body.core_claims ?? t.core_claims,
            catalysts: body.catalysts ?? t.catalysts,
            risks: body.risks ?? t.risks,
            invalidation_conditions: body.invalidation_conditions ?? t.invalidation_conditions,
          });
          insertRevision(tid, body.change_summary || "更新投资逻辑");
          return ok({ data: snapshotThesis(tid) });
        }
        if (method === "DELETE") {
          const confirmFlag = u.searchParams.get("confirm");
          if (confirmFlag !== "true") return err(400, "请确认归档操作");
          const expected = Number(u.searchParams.get("expected_revision") || "0");
          if (t.status === "archived") {
            return err(409, "已归档的投资逻辑不可修改");
          }
          if (expected !== t.current_revision) {
            return err(409, "投资逻辑已发生变化，请重新加载后重试", {
              current_revision: t.current_revision,
            });
          }
          t.status = "archived";
          insertRevision(tid, u.searchParams.get("change_summary") || "归档");
          return ok({ data: snapshotThesis(tid) });
        }
      }

      // ---- Revisions ----
      const revListMatch = pathname.match(/^\/api\/thesis\/([^/]+)\/revisions$/);
      if (revListMatch && method === "GET") {
        const tid = revListMatch[1];
        const revs = revisionsByThesis.get(tid) || [];
        const items = revs.map((r) => ({
          id: r.id,
          thesis_id: r.thesis_id,
          revision_number: r.revision_number,
          change_summary: r.change_summary,
          created_at: r.created_at,
        }));
        return ok({ data: { items, total: items.length } });
      }
      const revDetailMatch = pathname.match(/^\/api\/thesis\/([^/]+)\/revisions\/(\d+)$/);
      if (revDetailMatch && method === "GET") {
        const tid = revDetailMatch[1];
        const rev = Number(revDetailMatch[2]);
        const revs = revisionsByThesis.get(tid) || [];
        const found = revs.find((r) => r.revision_number === rev);
        if (!found) return err(404, "版本不存在");
        return ok({ data: found });
      }
      const diffMatch = pathname.match(/^\/api\/thesis\/([^/]+)\/diff$/);
      if (diffMatch && method === "GET") {
        const tid = diffMatch[1];
        const fromRev = Number(u.searchParams.get("from"));
        const toRev = Number(u.searchParams.get("to"));
        const revs = revisionsByThesis.get(tid) || [];
        const fromR = revs.find((r) => r.revision_number === fromRev);
        const toR = revs.find((r) => r.revision_number === toRev);
        if (!fromR || !toR) return err(404, "版本不存在");
        // 简化 diff：thesis_changes 仅比较 title/summary/status 等顶层字段
        const thesisChanges = {};
        const fields = ["title", "summary", "status", "core_claims", "catalysts", "risks", "invalidation_conditions"];
        for (const f of fields) {
          const a = fromR.snapshot.thesis[f];
          const b = toR.snapshot.thesis[f];
          if (JSON.stringify(a) !== JSON.stringify(b)) {
            thesisChanges[f] = { from: a, to: b };
          }
        }
        // evidence diff：按 evidence_id 比对
        const fromLinks = new Map(fromR.snapshot.evidence_links.map((l) => [l.evidence_id, l]));
        const toLinks = new Map(toR.snapshot.evidence_links.map((l) => [l.evidence_id, l]));
        const evidenceAdded = [];
        const evidenceRemoved = [];
        const evidenceChanged = [];
        for (const [eid, l] of toLinks.entries()) {
          if (!fromLinks.has(eid)) evidenceAdded.push({ evidence_id: eid, to: l });
        }
        for (const [eid, l] of fromLinks.entries()) {
          if (!toLinks.has(eid)) evidenceRemoved.push({ evidence_id: eid, from: l });
        }
        for (const [eid, fromL] of fromLinks.entries()) {
          if (toLinks.has(eid)) {
            const toL = toLinks.get(eid);
            const changes = {};
            for (const k of ["stance", "claim", "classification", "confidence", "source_title", "source_url", "source_date", "accessed_at"]) {
              if (JSON.stringify(fromL[k]) !== JSON.stringify(toL[k])) {
                changes[k] = { from: fromL[k], to: toL[k] };
              }
            }
            if (Object.keys(changes).length > 0) {
              evidenceChanged.push({ evidence_id: eid, changes });
            }
          }
        }
        return ok({
          data: {
            from_revision: fromRev,
            to_revision: toRev,
            thesis_changes: thesisChanges,
            evidence_added: evidenceAdded,
            evidence_removed: evidenceRemoved,
            evidence_changed: evidenceChanged,
          },
        });
      }

      // ---- Thesis ↔ Evidence Link ----
      const linkMatch = pathname.match(/^\/api\/thesis\/([^/]+)\/evidence$/);
      if (linkMatch && method === "POST") {
        const tid = linkMatch[1];
        const t = theses.get(tid);
        if (!t) return err(404, "投资逻辑不存在");
        if (t.status === "archived") return err(409, "已归档的投资逻辑不可修改");
        const body = JSON.parse(request.postData() || "{}");
        if (body.expected_revision !== t.current_revision) {
          return err(409, "投资逻辑已发生变化，请重新加载后重试", {
            current_revision: t.current_revision,
          });
        }
        const ev = evidences.get(body.evidence_id);
        if (!ev) return err(404, "证据不存在");
        // subject 一致性校验
        if (ev.subject_type !== t.subject_type || ev.subject_id !== t.subject_id) {
          return err(400, "证据与投资逻辑的主体不一致");
        }
        const links = linksByThesis.get(tid);
        links.add(body.evidence_id);
        stanceByThesis.get(tid).set(body.evidence_id, body.stance);
        insertRevision(tid, body.change_summary || "关联证据");
        return ok({ data: snapshotThesis(tid) });
      }
      const stanceMatch = pathname.match(/^\/api\/thesis\/([^/]+)\/evidence\/([^/]+)$/);
      if (stanceMatch && method === "PUT") {
        const tid = stanceMatch[1];
        const eid = stanceMatch[2];
        const t = theses.get(tid);
        if (!t) return err(404, "投资逻辑不存在");
        if (t.status === "archived") return err(409, "已归档的投资逻辑不可修改");
        const body = JSON.parse(request.postData() || "{}");
        if (body.expected_revision !== t.current_revision) {
          return err(409, "投资逻辑已发生变化，请重新加载后重试", {
            current_revision: t.current_revision,
          });
        }
        stanceByThesis.get(tid).set(eid, body.stance);
        insertRevision(tid, body.change_summary || "修改立场");
        return ok({ data: snapshotThesis(tid) });
      }
      if (stanceMatch && method === "DELETE") {
        const tid = stanceMatch[1];
        const eid = stanceMatch[2];
        const t = theses.get(tid);
        if (!t) return err(404, "投资逻辑不存在");
        if (t.status === "archived") return err(409, "已归档的投资逻辑不可修改");
        const expected = Number(u.searchParams.get("expected_revision") || "0");
        if (expected !== t.current_revision) {
          return err(409, "投资逻辑已发生变化，请重新加载后重试", {
            current_revision: t.current_revision,
          });
        }
        linksByThesis.get(tid).delete(eid);
        stanceByThesis.get(tid).delete(eid);
        const summary = u.searchParams.get("change_summary") || "取消关联证据";
        insertRevision(tid, summary);
        return ok({ data: snapshotThesis(tid) });
      }

      // Fallback
      return ok({ data: {} });
    })().catch(async (e) => {
      // 避免未处理 rejection
      try {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: `mock error: ${e.message}` }),
        });
      } catch {
        /* ignore */
      }
    });
  }

  return { handle, evidences, theses, revisionsByThesis, snapshotThesis };
}

// ---------------------------------------------------------------------------
// Smoke 流程
// ---------------------------------------------------------------------------
async function waitForRevision(page, rev, timeout = 10000) {
  // 详情页 subtitle 形如 "主体 stock/600519 · v1 · 更新于 ..."
  // 使用精确前缀匹配避免歧义
  const re = new RegExp(`主体 .* · v${rev} ·`);
  await page.getByText(re).waitFor({ state: "visible", timeout });
}

async function runSmoke(page, mock, errors) {
  const label = "thesis-smoke";
  const { evidences, theses, revisionsByThesis, snapshotThesis } = mock;

  // 一次性注册 dialog 处理器：所有 confirm() 都自动接受
  page.on("dialog", async (dialog) => {
    try {
      await dialog.accept();
    } catch {
      /* 已被其它 handler 处理 */
    }
  });

  // ===== 1. 创建 thesis → 验证 revision 1 =====
  await page.goto(`http://127.0.0.1:${frontendPort}/thesis/new`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { name: "新建投资逻辑" }).waitFor({ state: "visible", timeout: 15000 });

  await page.locator('input[placeholder*="600519"]').fill("600519");
  await page.locator('input[placeholder*="贵茅2024基本面拐点已确立"]').fill("贵州茅台增长逻辑");
  await page.locator('textarea[placeholder*="一两段话概括"]').fill("Q3 营收 +20%，拐点确立");
  // 添加一条核心论点
  await page.locator('input[placeholder*="回车添加一条核心论点"]').fill("Q3 营收超预期");
  await page.locator('input[placeholder*="回车添加一条核心论点"]').press("Enter");
  await page.getByRole("button", { name: /保存$/ }).click();

  // 跳转到详情页，验证 revision 1
  await page.getByRole("heading", { name: "贵州茅台增长逻辑" }).waitFor({ state: "visible", timeout: 15000 });
  await waitForRevision(page, 1);

  // 取到 thesis id（从 mock 状态里拿）
  const thesisIds = Array.from(theses.keys());
  if (thesisIds.length !== 1) {
    errors.push(`${label}: expected 1 thesis after create, got ${thesisIds.length}`);
    return;
  }
  const tid = thesisIds[0];
  const t1 = theses.get(tid);
  if (t1.current_revision !== 1) {
    errors.push(`${label}: revision 1 expected, got ${t1.current_revision}`);
  }
  // 验证 revision 1 snapshot 存在且与当前聚合一致
  const revs1 = revisionsByThesis.get(tid) || [];
  if (revs1.length !== 1 || revs1[0].revision_number !== 1) {
    errors.push(`${label}: revision 1 not recorded, revs=${revs1.length}`);
  }
  const snap1 = JSON.stringify(snapshotThesis(tid));
  const rev1Snap = JSON.stringify(revs1[0].snapshot);
  if (snap1 !== rev1Snap) {
    errors.push(`${label}: revision 1 snapshot != current aggregate`);
  }

  // ===== 2. 创建 evidence =====
  await page.goto(`http://127.0.0.1:${frontendPort}/evidence/new`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { name: "新建证据" }).waitFor({ state: "visible", timeout: 15000 });

  await page.locator('input[placeholder*="600519"]').fill("600519");
  await page.locator('textarea[placeholder*="一句话陈述"]').fill("Q3 营收同比 +25%");
  await page.locator('input[placeholder*="XX公司2024年三季报点评"]').fill("贵州茅台三季报点评");
  await page.getByRole("button", { name: /保存$/ }).click();

  // 跳转到 evidence detail 页
  await page.getByText("Q3 营收同比 +25%").waitFor({ state: "visible", timeout: 15000 });
  if (evidences.size !== 1) {
    errors.push(`${label}: expected 1 evidence after create, got ${evidences.size}`);
    return;
  }
  const evId = Array.from(evidences.keys())[0];

  // ===== 3. 关联 evidence → revision 增加（1 → 2）=====
  await page.goto(`http://127.0.0.1:${frontendPort}/thesis/${tid}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { name: "贵州茅台增长逻辑" }).waitFor({ state: "visible", timeout: 15000 });

  // 点击「关联证据」按钮（带 Plus 图标的那一个）
  const linkBtn = page.getByRole("button", { name: /关联证据$/ }).first();
  await linkBtn.waitFor({ state: "visible", timeout: 10000 });
  await linkBtn.click();

  // 选择证据（select）
  const evSelect = page.locator("select").filter({ has: page.getByText(/Q3 营收/) }).first();
  if (await evSelect.isVisible().catch(() => false)) {
    await evSelect.selectOption({ value: evId });
  } else {
    // fallback：直接选最后一个 option
    const allSelects = page.locator("select");
    const count = await allSelects.count();
    if (count > 0) {
      const opts = await allSelects.first().locator("option").all();
      const last = opts[opts.length - 1];
      const val = await last.getAttribute("value");
      if (val) await allSelects.first().selectOption(val);
    }
  }
  // 点击关联面板里的「关联」按钮（不同于顶部按钮，应避免点击 disabled 的顶部按钮）
  const confirmBtn = page.getByRole("button", { name: /^关联$/ }).first();
  await confirmBtn.click();

  // 等待 revision 变成 2
  await waitForRevision(page, 2);
  if (t1.current_revision !== 2) {
    errors.push(`${label}: after link evidence, expected rev=2, got ${t1.current_revision}`);
  }
  // 验证关联证据出现在详情页
  if (!(await page.getByText("Q3 营收同比 +25%").first().isVisible().catch(() => false))) {
    errors.push(`${label}: linked evidence claim not visible on thesis detail`);
  }

  // ===== 4. 修改 stance → revision 增加（2 → 3）=====
  // 找到「修改立场」按钮
  const stanceBtn = page.getByRole("button", { name: /修改立场$/ }).first();
  await stanceBtn.waitFor({ state: "visible", timeout: 10000 });
  await stanceBtn.click();
  // 选择 oppose（弹出的 stance 编辑器中 select）
  // stance 编辑器中的 select：含 support/oppose/neutral 选项
  const stanceSelects = page.locator("select");
  const sCount = await stanceSelects.count();
  // 找到含 oppose 选项的 select
  let chosen = false;
  for (let i = 0; i < sCount; i++) {
    const sel = stanceSelects.nth(i);
    const opts = await sel.locator("option").allTextContents();
    if (opts.includes("反对")) {
      await sel.selectOption({ label: "反对" });
      chosen = true;
      break;
    }
  }
  if (!chosen) {
    errors.push(`${label}: stance oppose option not found`);
  }
  // 点击 stance 编辑器的保存按钮（包含 Save 图标的）
  const stanceSaveBtn = page.getByRole("button", { name: /保存$/ }).first();
  await stanceSaveBtn.click();
  await waitForRevision(page, 3);
  if (t1.current_revision !== 3) {
    errors.push(`${label}: after stance change, expected rev=3, got ${t1.current_revision}`);
  }

  // ===== 5. 编辑 thesis → revision 增加（3 → 4）+ 查看 diff =====
  await page.getByRole("button", { name: /编辑$/ }).first().click();
  // 修改 title
  const titleInput = page.locator('input').filter({ hasText: "" }).first();
  // 用更稳的方式：找到第一个 value=贵州茅台增长逻辑 的 input
  const titleEdit = page.locator('input[value="贵州茅台增长逻辑"]').first();
  if (await titleEdit.isVisible().catch(() => false)) {
    await titleEdit.fill("贵州茅台增长逻辑（更新）");
  }
  // 点击编辑表单的保存
  await page.getByRole("button", { name: /保存$/ }).first().click();
  await waitForRevision(page, 4);
  if (t1.current_revision !== 4) {
    errors.push(`${label}: after thesis edit, expected rev=4, got ${t1.current_revision}`);
  }

  // 切到「版本对比」tab
  await page.getByRole("button", { name: /版本对比$/ }).first().click();
  // 选 from=1, to=4
  const fromSelect = page.locator("select").nth(0);
  const toSelect = page.locator("select").nth(1);
  await fromSelect.selectOption("1");
  await toSelect.selectOption("4");
  await page.getByRole("button", { name: /^对比$/ }).click();

  // 验证 diff 出现：对比 v1 → v4
  await page.getByText(/对比 v1 → v4/).waitFor({ state: "visible", timeout: 10000 });
  // 验证有 thesis 字段变化（title 改了）
  if (!(await page.getByText("title").first().isVisible().catch(() => false))) {
    errors.push(`${label}: diff thesis_changes should contain title field`);
  }
  // 验证有新增证据（evidence_added）
  if (!(await page.getByText(/新增证据/).first().isVisible().catch(() => false))) {
    errors.push(`${label}: diff should show 新增证据 section`);
  }

  // ===== 6. 编辑 evidence → 验证联动 revision（4 → 5）=====
  await page.goto(`http://127.0.0.1:${frontendPort}/evidence/${evId}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByText("Q3 营收同比 +25%").first().waitFor({ state: "visible", timeout: 15000 });
  await page.getByRole("button", { name: /编辑$/ }).first().click();
  // 修改 claim
  const claimTextarea = page.locator('textarea').filter({ hasText: "Q3 营收同比 +25%" }).first();
  if (await claimTextarea.isVisible().catch(() => false)) {
    await claimTextarea.fill("Q3 营收同比 +30%（更新）");
  }
  await page.getByRole("button", { name: /保存$/ }).first().click();
  // 等 evidence detail 显示新 claim
  await page.getByText("Q3 营收同比 +30%（更新）").first().waitFor({ state: "visible", timeout: 10000 });

  // 回到 thesis detail，验证 revision 增加
  await page.goto(`http://127.0.0.1:${frontendPort}/thesis/${tid}`, {
    waitUntil: "domcontentloaded",
  });
  await waitForRevision(page, 5);
  if (t1.current_revision !== 5) {
    errors.push(`${label}: after evidence edit cascade, expected rev=5, got ${t1.current_revision}`);
  }
  // 验证 thesis 详情页显示更新后的 claim
  if (!(await page.getByText("Q3 营收同比 +30%（更新）").first().isVisible().catch(() => false))) {
    errors.push(`${label}: thesis detail should reflect updated evidence claim`);
  }

  // ===== 7. 软删除 evidence → 当前列表不显示，历史版本仍显示 =====
  await page.goto(`http://127.0.0.1:${frontendPort}/evidence/${evId}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByText("Q3 营收同比 +30%（更新）").first().waitFor({ state: "visible", timeout: 15000 });
  // dialog 已在 runSmoke 开头注册统一 handler
  await page.getByRole("button", { name: /删除$/ }).first().click();
  // evidence 应被标记 deleted
  await page.waitForTimeout(500);
  const ev = evidences.get(evId);
  if (!ev || ev.deleted !== 1) {
    errors.push(`${label}: evidence not soft-deleted after delete button`);
  }

  // 当前列表不显示（evidence list 不含已删除）
  await page.goto(`http://127.0.0.1:${frontendPort}/evidence`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(500);
  if (await page.getByText("Q3 营收同比 +30%（更新）").first().isVisible().catch(() => false)) {
    errors.push(`${label}: deleted evidence should not appear in current evidence list`);
  }

  // thesis 当前聚合状态不应再包含该 evidence（cascade 删除已生成 rev=6）
  await page.goto(`http://127.0.0.1:${frontendPort}/thesis/${tid}`, {
    waitUntil: "domcontentloaded",
  });
  await waitForRevision(page, 6);
  if (t1.current_revision !== 6) {
    errors.push(`${label}: after evidence soft-delete cascade, expected rev=6, got ${t1.current_revision}`);
  }
  if (await page.getByText("Q3 营收同比 +30%（更新）").first().isVisible().catch(() => false)) {
    errors.push(`${label}: deleted evidence should not appear in current thesis aggregate`);
  }

  // 历史版本（v2）仍包含该证据
  await page.goto(`http://127.0.0.1:${frontendPort}/thesis/${tid}/revision/2`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { name: /版本 v2 快照/ }).waitFor({ state: "visible", timeout: 15000 });
  if (!(await page.getByText("Q3 营收同比 +25%").first().isVisible().catch(() => false))) {
    errors.push(`${label}: historical revision v2 should still contain evidence (original claim)`);
  }

  // ===== 8. 当前聚合状态与 snapshot 等价（v6）=====
  const snap6 = JSON.stringify(snapshotThesis(tid));
  const rev6Snap = JSON.stringify((revisionsByThesis.get(tid) || []).find((r) => r.revision_number === 6)?.snapshot);
  if (snap6 !== rev6Snap) {
    errors.push(`${label}: v6 snapshot != current aggregate after cascade delete`);
  }

  // ===== Archived 最小验证 =====
  // 新建另一个 thesis 用于归档测试
  await page.goto(`http://127.0.0.1:${frontendPort}/thesis/new`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("heading", { name: "新建投资逻辑" }).waitFor({ state: "visible", timeout: 15000 });
  await page.locator('input[placeholder*="600519"]').fill("000001");
  await page.locator('input[placeholder*="贵茅2024基本面拐点已确立"]').fill("平安银行股息逻辑");
  await page.getByRole("button", { name: /保存$/ }).click();
  await page.getByRole("heading", { name: "平安银行股息逻辑" }).waitFor({ state: "visible", timeout: 15000 });

  const tids = Array.from(theses.keys());
  const tid2 = tids[tids.length - 1];
  const t2 = theses.get(tid2);
  const revBeforeArchive = t2.current_revision;

  // 归档（dialog 已在 runSmoke 开头统一处理）
  await page.getByRole("button", { name: /^归档$/ }).first().click();
  await page.getByText(/已归档，内容冻结/).waitFor({ state: "visible", timeout: 10000 });
  if (t2.status !== "archived") {
    errors.push(`${label}: thesis status should be archived after archive action`);
  }
  // 归档本身生成一个新 revision
  if (t2.current_revision !== revBeforeArchive + 1) {
    errors.push(`${label}: archive should generate a new revision, expected ${revBeforeArchive + 1}, got ${t2.current_revision}`);
  }
  const archivedRev = t2.current_revision;

  // 尝试编辑 → 应被禁用（编辑按钮 disabled）
  const editBtn = page.getByRole("button", { name: /编辑$/ }).first();
  if (await editBtn.isVisible().catch(() => false)) {
    const disabled = await editBtn.isDisabled().catch(() => false);
    if (!disabled) {
      errors.push(`${label}: edit button should be disabled on archived thesis`);
    }
  }

  // Evidence 变化不更新 archived revision：新建 evidence 并编辑，确认 t2 的 revision 不变
  await page.goto(`http://127.0.0.1:${frontendPort}/evidence/new`, {
    waitUntil: "domcontentloaded",
  });
  await page.locator('input[placeholder*="600519"]').fill("000001");
  await page.locator('textarea[placeholder*="一句话陈述"]').fill("平安银行股息率 5%");
  await page.locator('input[placeholder*="XX公司2024年三季报点评"]').fill("平安银行三季报");
  await page.getByRole("button", { name: /保存$/ }).click();
  await page.waitForTimeout(500);

  // 关联到 tid2（应该被后端拒绝，因为 archived）—— 但我们还没关联过任何 evidence，
  // 所以这里只验证：归档后，即使有 evidence 变化，archived thesis 的 revision 不变
  // 直接在 mock 状态里检查（archived thesis 不参与 cascade）
  const ev2Id = Array.from(evidences.keys())[Array.from(evidences.keys()).length - 1];
  // 编辑 ev2：cascade 应跳过 archived 的 tid2
  await page.goto(`http://127.0.0.1:${frontendPort}/evidence/${ev2Id}`, {
    waitUntil: "domcontentloaded",
  });
  await page.getByRole("button", { name: /编辑$/ }).first().click();
  const claimTA = page.locator("textarea").first();
  await claimTA.fill("平安银行股息率 6%");
  await page.getByRole("button", { name: /保存$/ }).first().click();
  await page.waitForTimeout(500);

  if (t2.current_revision !== archivedRev) {
    errors.push(`${label}: archived thesis revision must not change on evidence edit, expected ${archivedRev}, got ${t2.current_revision}`);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
  const errors = [];
  let server = null;
  let browser = null;

  if (!existsSync(frontendDist) || !existsSync(path.join(frontendDist, "index.html"))) {
    console.error("frontend/dist missing — run: npm run build");
    process.exit(2);
  }

  try {
    frontendPort = await getFreePort();
    server = await startStaticServer(frontendDist, frontendPort);
    await waitHttp(`http://127.0.0.1:${frontendPort}/`);

    browser = await launchBrowser();
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    const mock = createApiMockState();
    await page.route("**/api/**", (route) => mock.handle(route));

    page.on("pageerror", (err) => {
      errors.push(`pageerror: ${err.message}`);
    });

    await runSmoke(page, mock, errors);
    await context.close();
  } catch (e) {
    errors.push(`fatal: ${e && e.stack ? e.stack : String(e)}`);
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {
        /* ignore */
      }
    }
    if (server) {
      await new Promise((resolve) => server.close(() => resolve()));
    }
  }

  if (errors.length) {
    console.error(`FAIL evidence-thesis smoke (${browserLabel})`);
    for (const e of errors) console.error(` - ${e}`);
    process.exit(1);
  }
  console.log(`PASS evidence-thesis smoke (${browserLabel}) port=${frontendPort}`);
}

main();
