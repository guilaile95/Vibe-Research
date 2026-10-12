import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { COHORT_PATH, COHORT_DAY_A as dayA, COHORT_DAY_B as dayB, COHORT_CLOCK,
  cohortReply, cohortUnavailable, validCohortQuery, validCohortStaticRequest,
  observeCohortReads } from "./e2e/cohort-identity.fixture.mjs";

test("cohort fixtures contain individual two-date evidence, never inferred performance summaries", () => {
  for (const day of [dayA, dayB]) {
    const result = cohortReply(day);
    assert.equal(result.trade_date, day);
    assert.equal(result.evidence.current.trade_date, day);
    assert.equal(result.evidence.previous.trade_date, result.previous_trade_date);
    assert.equal(result.selection_mode, "CURRENT_STORED_POSTHOC");
    assert.equal(result.point_in_time_claim, "NONE");
    assert.equal(result.research_only, true);
    assert.deepEqual(Object.keys(result.projection), ["rows"]);
    assert.equal(result.projection.rows.length, result.evidence.previous.row_count);
    assert.equal(result.projection.rows[0].present_today, false);
    assert.equal(result.projection.rows[0].current_boards, null);
    assert.equal(result.projection.rows[0].current_source_code, null);
    assert.equal(result.projection.rows[1].present_today, true);
    for (const key of ["metrics", "groups", "transitions", "rate", "promotion_rate", "performance", "returns"]) {
      assert.equal(result[key], undefined); assert.equal(result.projection[key], undefined);
    }
    const unknown = cohortReply(day, "unavailable");
    assert.equal(unknown.status, "unavailable");
    assert.equal(unknown.projection, null); assert.equal(unknown.evidence, null);
  }
  assert.equal(cohortUnavailable(dayA).previous_trade_date, null);
  assert.throws(() => cohortReply("2026-10-12"), /not whitelisted/);
  assert.equal(COHORT_CLOCK, "2026-07-30T08:00:00Z");
  const changed = cohortReply(dayA); changed.projection.rows[0].current_boards = 0;
  assert.equal(cohortReply(dayA).projection.rows[0].current_boards, null);
});

test("cohort fixture accepts only exact GET, path and two literal dates", () => {
  for (const date of [dayA, dayB]) assert.equal(validCohortQuery("GET", COHORT_PATH, `?trade_date=${date}`), true);
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "get"]) {
    assert.equal(validCohortQuery(method, COHORT_PATH, `?trade_date=${dayA}`), false);
  }
  for (const query of ["", "?", "?trade_date=2026-07-28", "?trade_date=2026-10-12", "?trade_date=2026-07-30T00:00:00Z",
    "?trade_date=2026%2D07%2D30", `?trade_date=${dayA}&trade_date=${dayA}`, `?trade_date=${dayA}&trade_date=${dayB}`,
    `?date=${dayA}`, `?trade_date=${dayA}&as_of=x`, `?trade_date=${dayA}&observed_at=x`, `?trade_date=${dayA}&root=/tmp`,
    `?trade_date=${dayA}&refresh=1`, `?trade_date=${dayA}&`, `?trade_date=${dayA}%20`]) {
    assert.equal(validCohortQuery("GET", COHORT_PATH, query), false, query);
  }
  for (const path of [`${COHORT_PATH}/`, `${COHORT_PATH}/refresh`, "/api/market/seal-quality", "/api/agent-runtime/status", "/api/chat", "/api/quotes"]) {
    assert.equal(validCohortQuery("GET", path, `?trade_date=${dayA}`), false, path);
  }
});

test("cohort static fixture cannot pass API, write, unknown, nested or external assets", () => {
  for (const path of ["/", "/index.html", "/favicon.ico", "/assets/index-ab12.js", "/assets/index-xy.css"]) {
    assert.equal(validCohortStaticRequest("GET", path, ""), true);
    assert.equal(validCohortStaticRequest("POST", path, ""), false);
    assert.equal(validCohortStaticRequest("GET", path, "?v=1"), false);
  }
  for (const path of [COHORT_PATH, "/api/unknown", "/assets/../index.js", "/assets/sub/index.js", "/assets/font.woff2", "/secret.txt", "https://provider.example/script.js"]) {
    assert.equal(validCohortStaticRequest("GET", path, ""), false, path);
  }
});

test("race instrument observes actual abort and parsing while preserving unrelated requests", async () => {
  const calls = [];
  const window = { fetch: async (input, init) => { calls.push({ input, init }); return { json: async () => ({ data: cohortReply(dayA) }) }; } };
  vm.runInNewContext(`(${observeCohortReads.toString()})()`, { window, URL, location: { href: "http://127.0.0.1/" } });
  const controller = new AbortController();
  const response = await window.fetch(`${COHORT_PATH}?trade_date=${dayA}`, { signal: controller.signal });
  assert.equal(window.__cohortReads[0].parsed, false);
  controller.abort(); await response.json();
  assert.equal(calls[0].init.signal, undefined);
  assert.equal(window.__cohortReads[0].aborted, true); assert.equal(window.__cohortReads[0].parsed, true);
  await window.fetch("/api/unrelated", { signal: controller.signal });
  assert.equal(calls[1].init.signal, controller.signal);
  assert.equal(window.__cohortReads.length, 1);
});

test("production current/history page owns dates and adapter imports only the real card", () => {
  const page = readFileSync(new URL("../src/pages/DailyReview.tsx", import.meta.url), "utf8");
  assert.match(page, /<CohortIdentityCard tradeDate=\{dr\?\.trade_date \?\? null\}/);
  assert.match(page, /<CohortIdentityCard tradeDate=\{snap\.trade_date \?\? null\}/);
  const component = readFileSync(new URL("../src/components/dailyReview/CohortIdentityCard.tsx", import.meta.url), "utf8");
  assert.match(component, /api\.cohortIdentity\(tradeDate, controller\.signal\)/);
  assert.match(component, /state\?\.date === tradeDate/);
  assert.match(component, /generation\.current !== request/);
  assert.match(component, /controller\.abort\(\)/);
  assert.doesNotMatch(component, /Date\.now|new Date|localStorage|setInterval/);
  const adapter = readFileSync(new URL("./e2e/cohort-identity-adapter/main.tsx", import.meta.url), "utf8");
  assert.match(adapter, /import \{ CohortIdentityCard \} from "@\/components\/dailyReview\/CohortIdentityCard"/);
  assert.doesNotMatch(adapter, /fetch\(|<table|projection|present_today/);
});

test("dedicated offline CI harness exits build-only before server or browser and fixes its clock", () => {
  const browser = readFileSync(new URL("./e2e/cohort-identity.browser.mjs", import.meta.url), "utf8");
  assert.ok(browser.indexOf('process.argv.includes("--build-only")') < browser.indexOf("const server = createServer"));
  assert.ok(browser.indexOf('process.argv.includes("--build-only")') < browser.indexOf("chromium.launch"));
  assert.ok(browser.indexOf("page.clock.setFixedTime(new Date(COHORT_CLOCK))") < browser.indexOf("await page.goto("));
  assert.match(browser, /for \(const width of \[1440, 390\]\)/);
  assert.match(browser, /validCohortQuery\(request\.method\(\), url\.pathname, url\.search\)/);
  assert.match(browser, /validCohortStaticRequest\(request\.method\(\), url\.pathname, url\.search\)/);
  assert.match(browser, /url\.origin !== origin/);
  assert.match(browser, /serviceWorkers: "block"/);
  assert.match(browser, /routeWebSocket/);
  for (const key of ["external", "unexpected", "errors"]) assert.ok(browser.includes(`assert.deepEqual(audit.${key}, [])`));
  assert.match(browser, /assert\.equal\(results\.length, 20\)/);
  assert.match(browser, /layout\.documentWidth <= layout\.viewport \+ 1/);
  assert.doesNotMatch(browser, /child_process|spawn\(|execFile|fonts\.googleapis|route\.fallback|backendPort/);
  const html = readFileSync(new URL("./e2e/cohort-identity-adapter/index.html", import.meta.url), "utf8");
  assert.doesNotMatch(html, /https?:|preconnect|dns-prefetch/);
  const ci = readFileSync(new URL("../../.github/workflows/ci.yml", import.meta.url), "utf8");
  assert.match(ci, /tests\/e2e\/cohort-identity\.browser\.mjs/);
  assert.match(ci, /name: cohort-identity-evidence/);
});
