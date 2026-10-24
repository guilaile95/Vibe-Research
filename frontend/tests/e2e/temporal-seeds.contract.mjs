/** Execute the browser's exact embedded seed functions/env, without a browser. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { createTemporalClock } from "./temporal.fixture.mjs";
import { seedActiveCampaign } from "./campaign-active-fixture.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(__dirname, "../../../backend");
const tempDataDir = process.env.VR_DATA_DIR;
const clock = createTemporalClock(tempDataDir);
const mode = process.argv[2];
const source = readFileSync(join(__dirname, mode === "active" ? "decision-challenge.browser.mjs" : "formal-outcome.browser.mjs"), "utf8");
const envStart = source.indexOf("    const env = {");
const envEnd = source.indexOf("\n    };", envStart) + "\n    };".length;
assert.ok(envStart > 0 && envEnd > envStart, "browser environment block must exist");
const context = { process, clock, tempDataDir, frontend: "http://127.0.0.1:39999", __dirname, backendDir, path, join, assert, spawnSync };
const env = runInNewContext(`${source.slice(envStart, envEnd)}\nenv;`, context);
if (mode === "active") {
  assert.equal(env.PYTHONPATH, undefined, "active seed must not need a caller-provided PYTHONPATH");
  seedActiveCampaign(backendDir, env, process.env.TEMPORAL_CAMPAIGN_ID);
  console.log(JSON.stringify({ clock: clock.env.E2E_CLOCK_FILE, status: "ACTIVE_SEED_OK" }));
} else {
  assert.equal(mode, "history");
  const extract = (name) => {
    const start = source.indexOf(`function ${name}(`);
    const following = /\n(?:async )?function /.exec(source.slice(start + 1));
    const end = following ? start + 1 + following.index : -1;
    assert.ok(start > 0 && end > start, `exact ${name} function must exist`);
    return source.slice(start, end);
  };
  clock.set("2026-08-28T09:00:00.000000Z");
  const template = JSON.parse(process.env.TEMPORAL_DECISION_TEMPLATE);
  const python = { cmd: process.env.PYTHON, args: [] };
  const script = `${extract("createOutcomeHistoryFillers")}\n${extract("createHistoricalActionFixtures")}\nJSON.stringify({ fillers: createOutcomeHistoryFillers(env, python, template), actions: createHistoricalActionFixtures(env, python, template, [{ next_best_action: "WAIT", review_by: "2026-09-11T10:00:00Z", strategy: "SWING" }]) });`;
  const result = JSON.parse(runInNewContext(script, { ...context, env, python, template }));
  // Reads the seed subprocess's latest phase, not a stale JS cached time.
  const thirdPhase = clock.advance();
  console.log(JSON.stringify({ ...result, thirdPhase, clock: clock.env.E2E_CLOCK_FILE }));
}
