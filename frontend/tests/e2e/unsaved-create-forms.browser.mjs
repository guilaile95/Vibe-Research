// Synthetic API fixtures verify form/navigation behavior, not market or model quality.
// Run after npm run build: node tests/e2e/unsaved-create-forms.browser.mjs
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createReadStream, existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dist = fileURLToPath(new URL("../../dist/", import.meta.url));
assert.ok(existsSync(path.join(dist, "index.html")), "Build frontend before running this test");
const server = createServer((req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;
  const target = path.resolve(dist, `.${pathname}`);
  if (!target.startsWith(`${path.resolve(dist)}${path.sep}`)) { res.writeHead(403); res.end(); return; }
  const file = existsSync(target) && path.extname(target) ? target : path.join(dist, "index.html");
  res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" }[path.extname(file)] || "application/octet-stream");
  createReadStream(file).pipe(res);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const chromiumRoot = path.join(process.env.LOCALAPPDATA || "", "ms-playwright");
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || (existsSync(chromiumRoot)
  ? readdirSync(chromiumRoot).map((name) => path.join(chromiumRoot, name, "chrome-win64", "chrome.exe")).find(existsSync) : undefined);
let browser;
let checks = 0;
const check = (message) => { checks++; console.log(`PASS ${message}`); };
const waitFor = async (predicate) => {
  for (let i = 0; i < 250; i++) { if (predicate()) return; await new Promise((resolve) => setTimeout(resolve, 20)); }
  throw new Error("Timed out waiting for synthetic request");
};
async function scenario(kind, campaign = false, returnTo = "") {
  const context = await browser.newContext();
  const state = { mode: "success", creates: 0, body: null, release: null, failSetup: false };
  const fulfill = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(status === 200 ? { data } : { detail: "synthetic save failure" }) });
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== base) return route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const endpoint = url.pathname.slice(4);
    if (endpoint === `/campaigns/test-campaign`) return fulfill(route, { campaign_id: "test-campaign", security_code: "600519", strategy: "SWING" });
    if (endpoint === `/${kind}` && route.request().method() === "POST") {
      state.creates++;
      state.body = route.request().postDataJSON();
      if (state.mode === "hold") await new Promise((resolve) => { state.release = resolve; });
      if (state.mode === "fail") return fulfill(route, {}, 500);
      return fulfill(route, kind === "evidence" ? { id: "test-evidence" } : { thesis: { id: "test-thesis", ...state.body } });
    }
    if (endpoint.endsWith("/begin-formalization") && state.failSetup) return fulfill(route, {}, 500);
    if (endpoint.startsWith("/thesis/test-thesis")) return fulfill(route, { thesis: { id: "test-thesis", ...state.body, status: "active", current_revision: 1, formal_state: "draft" }, evidence_links: [], revisions: [] });
    return fulfill(route, { items: [], records: [], total: 0 });
  });
  const page = await context.newPage();
  const query = campaign ? "?campaign_id=test-campaign&security_code=600519&strategy=SWING" : "?subject_id=600519";
  const target = `${base}/${kind}/new${query}${returnTo ? `&return_to=${encodeURIComponent(returnTo)}` : ""}`;
  await page.goto(`${base}/notes`);
  await page.goto(target);
  await page.locator("fieldset").waitFor();
  if (campaign) await page.locator('input[type="number"]').first().waitFor();
  const cancel = page.locator("fieldset a");
  const save = page.locator("fieldset > div").last().locator("button").first();
  const dirtyField = kind === "evidence" ? page.locator("fieldset textarea").first() : page.locator("fieldset input").nth(campaign ? 4 : 1);
  return { context, page, state, target, cancel, save, dirtyField };
}
try {
  browser = await chromium.launch({ headless: true, executablePath });
  for (const kind of ["evidence", "thesis"]) {
    const clean = await scenario(kind);
    await clean.cancel.click();
    await clean.page.waitForURL(`${base}/${kind}`);
    assert.equal(await clean.page.locator("dialog[open]").count(), 0);
    check(`${kind}: query prefill leaves without false dirty`);
    await clean.context.close();

    const s = await scenario(kind);
    await s.cancel.click();
    await s.page.waitForURL(`${base}/${kind}`);
    await s.page.locator(`a[href="/${kind}/new"]`).click();
    await s.page.locator("fieldset input").first().fill("600519");
    await s.dirtyField.fill("synthetic unsaved input");
    await s.cancel.click();
    await s.page.getByRole("dialog").waitFor();
    await s.page.getByRole("button", { name: "留在此页", exact: true }).click();
    assert.equal(await s.dirtyField.inputValue(), "synthetic unsaved input");
    check(`${kind}: cancel navigation retains input`);
    const back = s.page.goBack({ timeout: 1000 }).catch((error) => assert.match(error.message, /Timeout/));
    await s.page.getByRole("dialog").waitFor();
    await back;
    await s.page.keyboard.press("Escape");
    assert.equal(await s.dirtyField.inputValue(), "synthetic unsaved input");
    check(`${kind}: Back/Escape retains input`);
    let unloads = 0;
    s.page.on("dialog", async (dialog) => { assert.equal(dialog.type(), "beforeunload"); unloads++; await dialog.dismiss(); });
    await s.page.reload({ timeout: 1500 }).catch((error) => assert.match(error.message, /ERR_ABORTED|Timeout/));
    assert.equal(unloads, 1);
    assert.equal(await s.dirtyField.inputValue(), "synthetic unsaved input");
    check(`${kind}: refresh rejected by native beforeunload`);
    if (kind === "evidence") await s.page.locator("fieldset input").nth(1).fill("Synthetic source");
    s.state.mode = "fail";
    await s.save.click();
    await waitFor(() => s.state.creates === 1);
    await s.page.getByText("synthetic save failure", { exact: true }).waitFor();
    await s.cancel.click();
    await s.page.getByRole("dialog").waitFor();
    await s.page.getByRole("button", { name: "留在此页", exact: true }).click();
    assert.equal(await s.dirtyField.inputValue(), "synthetic unsaved input");
    check(`${kind}: failed save remains dirty`);
    s.state.mode = "hold";
    await s.save.click();
    await waitFor(() => Boolean(s.state.release));
    assert.equal(await s.dirtyField.isDisabled(), true);
    await s.save.evaluate((button) => { button.click(); button.click(); });
    assert.equal(s.state.creates, 2);
    await s.cancel.click();
    await s.page.getByRole("dialog").waitFor();
    assert.equal(await s.page.getByRole("button", { name: "放弃未保存内容并离开", exact: true }).isDisabled(), true);
    assert.match(await s.page.getByRole("dialog").innerText(), /关闭或刷新页面无法保证取消保存/);
    s.state.release();
    await s.page.waitForURL(kind === "evidence" ? `${base}/evidence/test-evidence` : `${base}/thesis/test-thesis`);
    assert.equal(s.state.creates, 2);
    check(`${kind}: pending save locks edits/duplicate submits/leave; completion bypasses blocked navigation`);
    await s.context.close();
    const switched = await scenario(kind, false, `/${kind}/new?subject_id=000001`);
    await switched.dirtyField.fill("Discard this old-subject draft");
    await switched.cancel.click();
    await switched.page.getByRole("dialog").waitFor();
    await switched.page.getByRole("button", { name: "放弃未保存内容并离开", exact: true }).click();
    await switched.page.waitForURL(`${base}/${kind}/new?subject_id=000001`);
    assert.equal(await switched.page.locator("fieldset input").first().inputValue(), "000001");
    assert.equal(await switched.dirtyField.inputValue(), "");
    await switched.cancel.click();
    await switched.page.waitForURL(`${base}/${kind}`);
    check(`${kind}: same-path subject switch discards old inputs and resets baseline`);
    await switched.context.close();
  }
  const pending = await scenario("thesis");
  for (let i = 0; i < 4; i++) {
    await pending.page.locator("fieldset input").nth(i + 2).fill(`pending-${i}`);
    assert.equal(await pending.page.locator("fieldset input").nth(i + 2).inputValue(), `pending-${i}`, "ArrayEditor input was accepted before navigation");
    await pending.cancel.click();
    await pending.page.getByRole("dialog").waitFor();
    await pending.page.getByRole("button", { name: "留在此页", exact: true }).click();
    await pending.page.getByRole("dialog").waitFor({ state: "hidden" });
    assert.equal(await pending.page.locator("fieldset input").nth(i + 2).inputValue(), `pending-${i}`);
  }
  await pending.dirtyField.fill("Synthetic thesis");
  await pending.save.click();
  await pending.page.waitForURL(`${base}/thesis/test-thesis`);
  for (const [i, field] of ["core_claims", "catalysts", "risks", "invalidation_conditions"].entries()) assert.deepEqual(pending.state.body[field], [`pending-${i}`]);
  check("thesis: all four pending ArrayEditor inputs are protected and included in Save");
  await pending.context.close();
  const cleanCampaign = await scenario("thesis", true);
  await cleanCampaign.cancel.click();
  await cleanCampaign.page.waitForURL(`${base}/thesis`);
  check("thesis: automatic Campaign hydration leaves without false dirty");
  await cleanCampaign.context.close();
  const partial = await scenario("thesis", true);
  partial.state.failSetup = true;
  await partial.dirtyField.fill("Synthetic formal thesis");
  await partial.save.click();
  await partial.page.waitForURL(/\/thesis\/test-thesis\?.*setup_error=1/);
  assert.equal(partial.state.creates, 1);
  assert.equal(await partial.page.locator("dialog[open]").count(), 0);
  check("thesis: partial create/setup failure navigates existing ID with setup_error without duplicate create");
  await partial.context.close();
  console.log(JSON.stringify({ checks, fixtureOnly: true, completedAt: new Date().toISOString() }));
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
