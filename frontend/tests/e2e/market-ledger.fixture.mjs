import assert from "node:assert/strict";
import { aiComputingResearch } from "../../src/data/sectorResearch/ai-computing.ts";

// Expected contract comes from the actual checked-in content, never a replacement
// browser mapping. Explicit original-bug assertions prevent a stale metadata label
// from becoming its own expected answer.
export const research = aiComputingResearch;
export const industry = research.tags.find(tag => tag.slug === "industry");
assert.equal(industry.label, "芯片、服务器、网络、散热产业格局");
assert.equal(industry.status, "draft");
assert.match(industry.blocks.find(block => block.type === "paragraph").text, /AI算力产业格局/);
export const contextFor = tag => [
  `板块：${research.fullName}`, `定位：${research.tagline}`,
  `研究栏目：${research.tags.map(t => t.label).join("、")}`,
  `当前栏目：${tag.label}`, `内容状态：${tag.status}`,
  "说明：仅根据当前页面已展示的栏目名称与占位说明回答，不要编造未展示的数字、研报结论或产业判断。",
].join("\n");
export function marketReply(method, path, search) {
  if (method !== "GET") return null;
  if (path === "/api/myreports" && !search) return [];
  if (path === "/api/sector-research/market-context" && search === "?sector_key=ai-computing") return { items: [] };
  return null;
}
export function canonicalPath(url) {
  const parsed = new URL(url, "http://synthetic.invalid"); parsed.searchParams.sort();
  return parsed.pathname + parsed.search;
}
export const rows = (marker, stage = "schema") => ({ status: 200, json: { items: marker ? [{
  entry_id: marker, signal_type: marker, stage, severity: "info", code: null,
  payload_json: { marker }, created_at: "2026-10-08T00:00:00Z",
}] : [], total: marker ? 1 : 0, limit: 100, offset: 0 } });
export const failure = marker => ({ status: 503, json: { detail: marker } });
export const oldDetail = () => ({ status: 200, json: {
  run: { decision_run_id: "SYNTHETIC_OLD_RUN", trade_date: "2026-10-08", generated_at: "2026-10-08T00:00:00Z", trace_status: "archived" },
  signal_entries: rows("SYNTHETIC_OLD_DETAIL").json.items,
  decision_outcomes: [{ outcome_id: "synthetic-old-outcome", code: "000001", action: "hold", reason: "SYNTHETIC_OLD_OUTCOME", constraints_applied_json: [] }],
} });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { resolve, promise }; };
export function ledgerFixture() {
  const queue = [], all = [], requests = [], unexpected = [];
  return { queue, all, requests, unexpected, failures: 0,
    expect(url, reply) {
      const gate = deferred(), started = deferred();
      const slot = { url: canonicalPath(url), reply, started: started.promise, release: () => gate.resolve(reply), markStarted: started.resolve, response: gate.promise };
      queue.push(slot); all.push(slot); return slot;
    },
    async reply(method, url) {
      const path = canonicalPath(url); requests.push(`${method} ${path}`);
      const slot = queue.shift();
      if (method !== "GET" || !slot || slot.url !== path) {
        unexpected.push(`${method} ${path}`); return failure("UNEXPECTED_SYNTHETIC_REQUEST");
      }
      slot.markStarted(); const reply = await slot.response;
      if (reply.status >= 400) this.failures++;
      return reply;
    },
    cleanup() { all.forEach(slot => slot.release()); },
  };
}
export function observeLedgerReads() {
  const nativeFetch = window.fetch.bind(window); window.__ledgerReads = [];
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.startsWith("/api/signal-ledger")) return nativeFetch(input, init);
    const row = { path: url.pathname + url.search, parsed: false, status: null };
    window.__ledgerReads.push(row);
    const response = await nativeFetch(input, init); row.status = response.status;
    const json = response.json.bind(response);
    response.json = async () => { const value = await json(); row.parsed = true; return value; };
    return response;
  };
}
