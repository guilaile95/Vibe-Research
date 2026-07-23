/**
 * 板块动态数据渲染逻辑测试（node:test，不依赖 vitest / 真实 API）
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { SectorDynamicData } from "../src/lib/api.ts";

function panelOkCount(panels: Record<string, { status?: string } | undefined> | undefined): { ok: number; total: number } {
  if (!panels) return { ok: 0, total: 0 };
  let ok = 0;
  let total = 0;
  for (const k of Object.keys(panels)) {
    total++;
    if (panels[k]?.status === "ok") ok++;
  }
  return { ok, total };
}

function statusFromCounts(ok: number, total: number): "normal" | "partial" | "unavailable" {
  if (total === 0 || ok === 0) return "unavailable";
  if (ok === total) return "normal";
  return "partial";
}

describe("SectorDynamicData rendering logic", () => {
  it("counts ok panels correctly", () => {
    const panels = {
      individual_info: { status: "ok" },
      profit_forecast: { status: "ok" },
      announcements: { status: "error" },
    };
    const { ok, total } = panelOkCount(panels);
    assert.equal(ok, 2);
    assert.equal(total, 3);
    assert.equal(statusFromCounts(ok, total), "partial");
  });

  it("empty panels => unavailable", () => {
    const { ok, total } = panelOkCount({});
    assert.equal(ok, 0);
    assert.equal(total, 0);
    assert.equal(statusFromCounts(ok, total), "unavailable");
  });

  it("all ok => normal", () => {
    const panels = {
      a: { status: "ok" },
      b: { status: "ok" },
    };
    const { ok, total } = panelOkCount(panels);
    assert.equal(statusFromCounts(ok, total), "normal");
  });

  it("accepts summary-shaped panel contract", () => {
    const data: SectorDynamicData = {
      sector_key: "pcb",
      source: "a-stock-data",
      fetched_at: "2026-07-24T00:00:00Z",
      status: "partial",
      warnings: ["x"],
      companies: [{
        code: "002463",
        name: "沪电股份",
        panels: {
          individual_info: { status: "ok", summary: { name: "沪电股份" }, error: null },
          profit_forecast: { status: "error", summary: {}, error: "依赖未安装" },
        },
      }],
    };
    assert.equal(data.status, "partial");
    const p = data.companies[0].panels;
    assert.equal(p.individual_info?.summary?.name, "沪电股份");
    assert.equal(typeof p.profit_forecast?.error, "string");
  });
});
