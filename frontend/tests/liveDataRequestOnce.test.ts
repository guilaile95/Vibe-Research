/**
 * 动态数据：展开时单次请求；state updater 外触发 load。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

/** 与 SectorResearchLiveData 同构的请求门闩逻辑（纯函数可测） */
function createLoadGate() {
  let inflight = false;
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    async load(fn: () => Promise<void>) {
      if (inflight) return;
      inflight = true;
      calls += 1;
      try {
        await fn();
      } finally {
        inflight = false;
      }
    },
  };
}

describe("live data single request gate", () => {
  it("concurrent load only runs once while inflight", async () => {
    const gate = createLoadGate();
    let resolve!: () => void;
    const p = new Promise<void>((r) => {
      resolve = r;
    });
    const a = gate.load(() => p);
    const b = gate.load(() => p);
    assert.equal(gate.calls, 1);
    resolve();
    await Promise.all([a, b]);
    assert.equal(gate.calls, 1);
  });

  it("second load after finish is allowed", async () => {
    const gate = createLoadGate();
    await gate.load(async () => {});
    await gate.load(async () => {});
    assert.equal(gate.calls, 2);
  });

  it("toggle expand loads only when opening without data", () => {
    let loads = 0;
    let expanded = false;
    let data: unknown = null;
    const loading = false;
    const onToggle = () => {
      const next = !expanded;
      expanded = next;
      if (next && !data && !loading) loads += 1;
    };
    onToggle(); // open
    assert.equal(expanded, true);
    assert.equal(loads, 1);
    onToggle(); // close
    onToggle(); // open again without data -> load again
    assert.equal(loads, 2);
    data = { ok: true };
    onToggle(); // close
    onToggle(); // open with data -> no load
    assert.equal(loads, 2);
  });
});
