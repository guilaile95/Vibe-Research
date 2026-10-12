/** Full production DailyReview views; exact golden HTTP mocks, not a real DB browser. */
import assert from "node:assert/strict";
import path from "node:path";
import { DAY, HISTORY_DAYS, integratedGolden, golden, aiBasisGolden } from "./next-day-verification.fixture.mjs";

export function observeIntegratedReads() {
  const original = window.fetch.bind(window);
  window.__reviewReads = [];
  window.__reviewHolds = [];
  window.__holdReviewPaths = [];
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const isRead = url.origin === location.origin && method === "GET"
      && ["/api/market/seal-quality", "/api/market/cohort-identity", "/api/market/evidence-readiness",
        "/api/daily-review/history/701", "/api/daily-review/history/702"].includes(url.pathname);
    if (!isRead) return original(input, init);
    const key = url.pathname + url.search;
    const record = { key, aborted: false, parsed: false, held: false };
    const recordIndex = window.__reviewReads.push(record) - 1;
    init?.signal?.addEventListener("abort", () => { record.aborted = true; });
    // Deliver after abort deliberately, proving application ownership, not transport cancellation.
    const response = await original(input, { ...init, signal: undefined });
    const read = response.json.bind(response);
    response.json = async () => { const data = await read(); record.parsed = true; return data; };
    const index = window.__holdReviewPaths.indexOf(key);
    if (index >= 0) {
      window.__holdReviewPaths.splice(index, 1);
      record.held = true;
      await new Promise(resolve => window.__reviewHolds.push({ key, recordIndex, resolve }));
    }
    return response;
  };
}

export async function runIntegratedReview({ page, fixture, viewport, evidenceDir, results, captures, shot }) {
  const journal = page.getByTestId("next-day-verification");
  const seal = page.getByTestId("seal-quality-card");
  const cohort = page.getByTestId("cohort-identity-card");
  const readiness = page.getByTestId("evidence-readiness-card");
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const archivePath = (kind, day) => `/api/market/${kind}?trade_date=${day}`;
  const hold = async keys => page.evaluate(keys => { window.__holdReviewPaths.push(...keys); }, keys);
  const held = async keys => page.waitForFunction(keys => keys.every(key => window.__reviewHolds.some(item => item.key === key)), keys);
  const release = async keys => {
    const indices = await page.evaluate(keys => {
      const indices = [];
      for (const key of keys) {
        const index = window.__reviewHolds.findIndex(item => item.key === key);
        if (index < 0) throw Error(`Held response missing: ${key}`);
        const held = window.__reviewHolds.splice(index, 1)[0];
        indices.push(held.recordIndex);
        held.resolve();
      }
      return indices;
    }, keys);
    await page.waitForFunction(indices => indices.every(index => window.__reviewReads[index]?.parsed), indices);
    await settle();
  };
  const openHistory = day => page.getByRole("row").filter({ has: page.getByRole("cell", { name: day, exact: true }) })
    .getByRole("button", { name: "查看", exact: true }).click();
  const journalOwned = async () => {
    assert.equal(await journal.getByLabel("验证复盘交易日").inputValue(), DAY);
    assert.equal(await journal.getByLabel("涨停家数理由").inputValue(), "INDEPENDENT_UNSAVED_JOURNAL");
    assert.equal(await journal.getByLabel("涨停家数方向").inputValue(), "up");
    assert.equal(fixture.writes.length, 0, "history navigation and archive retry never save the journal");
  };
  const ready = async day => {
    await seal.getByText(`交易日：${day} · 只读已连接的本地证据，不启动采集或请求行情`, { exact: true }).waitFor();
    await seal.getByTestId("seal-never_broken_ratio").waitFor();
    await cohort.getByText(`前一交易日 ${integratedGolden[day]["cohort-identity"].previous_trade_date} → 所选交易日 ${day}`, { exact: true }).waitFor();
    await cohort.getByTestId("cohort-members-table").waitFor();
    await readiness.getByText(`所选交易日：${day} · 只读检查现有归档，不请求行情或导入数据`, { exact: true }).waitFor();
    for (const feature of ["seal_quality", "cohort_identity", "next_day_verification"]) {
      await readiness.getByTestId(`readiness-${feature}`).getByText(/现有证据可读取/).waitFor();
    }
    assert.equal(await readiness.count(), 1);
    assert.equal(await seal.count(), 1, "actual current or history view owns exactly one seal card");
    assert.equal(await cohort.count(), 1);
    assert.equal(await cohort.locator("tbody tr").count(), 2);
    assert.match(await cohort.innerText(), /今日所选名单未出现/);
    assert.match(await cohort.innerText(), /未知/);
    assert.equal(await seal.getByTestId("seal-never_broken_ratio").innerText(), "0.0%");
    assert.ok((await seal.textContent()).includes(integratedGolden[day]["seal-quality"].archive_identity.publication_id), "seal source identity belongs to the selected snapshot date");
    assert.ok((await cohort.textContent()).includes(integratedGolden[day]["cohort-identity"].evidence.current.envelope_sha256), "cohort source identity belongs to the selected snapshot date");
  };
  const crop = (card, name) => captureIntegratedCard({ page, card, name, viewport, evidenceDir, captures });
  const capture = async label => {
    await ready(label.includes("current") ? DAY : HISTORY_DAYS[label.includes("second") ? 1 : 0]);
    await crop(seal, `${label}-seal`);
    await crop(cohort, `${label}-cohort`);
    await crop(readiness, `${label}-readiness`);
    await journalOwned();
    results.push(`${viewport.label}-${label}`);
  };

  await journal.getByText(/可记录，下一交易日/).waitFor();
  await journal.getByLabel("涨停家数方向").selectOption("up");
  await journal.getByLabel("涨停家数理由").fill("INDEPENDENT_UNSAVED_JOURNAL");
  await page.locator("#market-detail-short-history > summary").click();
  await capture("09-current-valid-paired-archives");
  await runSavedAiBasis({ page, viewport, evidenceDir, results, captures, mode: "v2" });
  const aiReadsBeforeHistory = fixture.requests.filter(r => r.url.includes("/api/ai-results/daily_review_ai")).length;
  fixture.malformedReadiness(DAY, { ...structuredClone(integratedGolden[DAY]["evidence-readiness"]), trade_date: HISTORY_DAYS[0] });
  await readiness.getByRole("button", { name: "重新检查已有归档", exact: true }).click();
  await readiness.getByRole("alert").waitFor();
  assert.equal(await readiness.getByTestId("readiness-seal_quality").count(), 0);
  await crop(readiness, "09b-readiness-wrong-date-rejected");
  await readiness.getByRole("button", { name: "重新检查已有归档", exact: true }).click();
  await ready(DAY);
  await journalOwned();
  results.push(`${viewport.label}-09c-readiness-explicit-retry-recovery`);
  await page.getByRole("tab", { name: "历史复盘", exact: true }).click();
  await openHistory(HISTORY_DAYS[0]);
  await capture("10-history-first-valid-paired-archives");
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await seal.waitFor({ state: "detached" });
  await cohort.waitFor({ state: "detached" });
  await readiness.waitFor({ state: "detached" });
  await journalOwned();
  await openHistory(HISTORY_DAYS[0]);
  await ready(HISTORY_DAYS[0]);

  // Hold both real card reads, then change snapshot. They must not overwrite the new date.
  const firstPaths = ["seal-quality", "cohort-identity", "evidence-readiness"].map(kind => archivePath(kind, HISTORY_DAYS[0]));
  await hold(firstPaths);
  await seal.getByRole("button", { name: "重新读取归档", exact: true }).click();
  await cohort.getByRole("button", { name: "重新读取归档", exact: true }).click();
  await readiness.getByRole("button", { name: "重新检查已有归档", exact: true }).click();
  await held(firstPaths);
  await seal.getByText("正在读取这一天的归档…", { exact: true }).waitFor();
  await cohort.getByText("正在读取两日名单…", { exact: true }).waitFor();
  await readiness.getByText("正在检查归档证据…", { exact: true }).waitFor();
  assert.equal(await readiness.getByTestId("readiness-seal_quality").count(), 0);
  assert.equal(await seal.getByTestId("seal-never_broken_ratio").count(), 0);
  assert.equal(await cohort.getByTestId("cohort-members-table").count(), 0);
  await openHistory(HISTORY_DAYS[1]);
  await ready(HISTORY_DAYS[1]);
  await release(firstPaths);
  for (const key of firstPaths) assert.equal(await page.evaluate(key => window.__reviewReads.find(item => item.key === key && item.held).aborted, key), true);
  await capture("11-history-second-rejects-late-paired-reads");

  // History detail itself has an independent generation guard (no transport abort).
  const firstSnapshot = "/api/daily-review/history/701";
  await hold([firstSnapshot]);
  await openHistory(HISTORY_DAYS[0]);
  await held([firstSnapshot]);
  await page.getByText("加载详情…", { exact: true }).waitFor();
  await openHistory(HISTORY_DAYS[1]);
  await ready(HISTORY_DAYS[1]);
  await release([firstSnapshot]);
  await ready(HISTORY_DAYS[1]);
  await journalOwned();
  results.push(`${viewport.label}-12-rapid-history-snapshot-ownership`);

  // Closing a pending detail and reopening must not allow the old generation back.
  await hold([firstSnapshot]);
  await openHistory(HISTORY_DAYS[0]);
  await held([firstSnapshot]);
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await release([firstSnapshot]);
  assert.equal(await seal.count(), 0);
  assert.equal(await cohort.count(), 0);
  assert.equal(await readiness.count(), 0);
  await openHistory(HISTORY_DAYS[0]);
  await capture("13-history-first-close-reopen-ownership");
  await page.getByRole("tab", { name: "当前市场", exact: true }).click();
  await page.locator("#market-detail-short-history > summary").click();
  await capture("14-current-return-preserves-journal-draft");
  await shot("14b-independent-journal-after-history", "可记录，下一交易日");
  await runSavedAiBasis({ page, viewport, evidenceDir, results, captures, mode: "v2", label: "history-return" });
  assert.equal(fixture.requests.filter(r => r.url.includes("/api/ai-results/daily_review_ai")).length, aiReadsBeforeHistory, "history navigation does not refetch or relabel the saved current AI result");

  // Fail closed on malformed success envelopes, then reread the same valid date.
  const malformed = [
    { ...structuredClone(golden.open_empty), items: null },
    { ...structuredClone(golden.open_empty), trade_date: HISTORY_DAYS[0] },
    { ...structuredClone(golden.open_empty), state: "OPEN", editable: true, revision: -1 },
  ];
  for (let index = 0; index < malformed.length; index++) {
    fixture.malformedGet(DAY, malformed[index]);
    await journal.getByRole("button", { name: /重新读取/ }).click();
    await journal.getByText(/验证记录响应未通过校验，请重新读取/).waitFor();
    assert.equal(await journal.getByLabel("涨停家数方向").count(), 0, "malformed data hides editor");
    assert.equal(await journal.getByRole("button", { name: /保存整晚|保存为空/ }).count(), 0);
    assert.equal(fixture.writes.length, 0);
    await journal.getByRole("button", { name: /重新读取/ }).click();
    await journal.getByText(/可记录，下一交易日/).waitFor();
    assert.equal(await journal.getByLabel("验证复盘交易日").inputValue(), DAY);
    results.push(`${viewport.label}-15-malformed-journal-${index}-recovery`);
  }
  await shot("15b-malformed-journal-recovery", "可记录，下一交易日");

  // The server may have accepted a write even when its response is malformed.
  // Preserve the input, prevent blind retry, and explicitly reread the new revision.
  await journal.getByLabel("涨停家数方向").selectOption("up");
  await journal.getByLabel("涨停家数理由").fill("Synthetic prior condition");
  fixture.expectSave({ revision: 0, items: [{ metric: "limit_up_count", direction: "up", reason: "Synthetic prior condition" }] },
    "open_saved", 200, { items: null });
  await journal.getByRole("button", { name: "保存整晚条件", exact: true }).click();
  await journal.getByText("保存响应未通过校验，保存结果尚未确认。输入已保留；可重新读取确认最新记录", { exact: true }).waitFor();
  assert.equal(await journal.getByLabel("涨停家数理由").inputValue(), "Synthetic prior condition");
  assert.equal(await journal.getByLabel("涨停家数方向").isDisabled(), true);
  const save = journal.getByRole("button", { name: "保存整晚条件", exact: true });
  assert.equal(await save.isDisabled(), true);
  await save.evaluate(element => element.click());
  assert.equal(fixture.writes.length, 1, "malformed response never triggers a blind second write");
  await shot("16a-malformed-write-retains-locked-input", "保存响应未通过校验");
  await journal.getByRole("button", { name: /重新读取/ }).click();
  await journal.getByText(/条件版本：1/).waitFor();
  assert.equal(await journal.getByLabel("涨停家数方向").isDisabled(), false);
  assert.equal(await journal.getByLabel("涨停家数理由").inputValue(), "Synthetic prior condition");
  assert.equal(fixture.writes.length, 1);
  await shot("16b-malformed-write-explicit-reread", "条件版本：1");
  const provenance = journal.getByTestId("verification-evidence-limit_up_count");
  await provenance.getByText("查看事前与收盘观察来源", { exact: true }).click();
  const prior = integratedGolden[DAY]["journal-saved"].items[0].prior_evidence;
  for (const value of [prior.fetched_at, prior.snapshot_at, prior.stored_at, ...prior.source_ids]) {
    assert.ok((await provenance.innerText()).includes(value), "saved journal discloses the exact frozen source identity and timestamps");
  }
  await provenance.getByText("未提供合格证据；不代表读数为零或条件不成立", { exact: true }).waitFor();
  await crop(provenance, "16c-journal-frozen-prior-and-unknown-target-provenance");
  assert.equal(fixture.writes.length, 1);
}

export async function captureIntegratedCard({ page, card, name, viewport, evidenceDir, captures }) {
    await card.evaluate(element => element.scrollIntoView({ block: "start", behavior: "instant" }));
    await page.evaluate(async () => { await document.fonts.ready; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); });
    const state = await card.evaluate(element => {
      const b = element.getBoundingClientRect(), m = element.closest("main")?.getBoundingClientRect() || { top: 0, bottom: innerHeight, left: 0, right: innerWidth };
      const x = Math.max(0, b.left, m.left), y = Math.max(0, b.top, m.top);
      return { text: element.innerText, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, left: b.left, right: b.right,
        clip: { x, y, width: Math.min(innerWidth, b.right, m.right) - x, height: Math.min(innerHeight, b.bottom, m.bottom) - y } };
    });
    assert.ok(state.left >= -1 && state.right <= viewport.width + 1, `${name} fits actual viewport`);
    assert.ok(state.scrollWidth <= state.clientWidth + 1, `${name} does not overflow`);
    assert.ok(state.clip.width > 100 && state.clip.height > 48, `${name} has useful painted content`);
    const filename = `${viewport.label}-${name}.png`;
    await page.screenshot({ path: path.join(evidenceDir, filename), clip: state.clip, animations: "disabled", caret: "hide" });
    captures.push({ name, viewport, ...state, files: [filename] });
}

export async function runSavedAiBasis({ page, viewport, evidenceDir, results, captures, mode, label = "initial" }) {
  const container = page.getByTestId("today-ai-review");
  await container.waitFor();
  await container.locator(":scope > summary").click();
  const card = page.getByTestId("daily-review-ai-basis");
  await card.waitFor();
  await card.locator(":scope > summary").click();
  const content = container.getByText(`SYNTHETIC_SAVED_REVIEW_${mode === "v1" ? "v1" : "v2"}`, { exact: true });
  await content.waitFor();
  await card.getByText("当前页面与结果依据日期或截止时间不同；当前页面数据不能为旧结果补证。", { exact: true }).waitFor();
  if (mode === "v1") {
    await card.getByText("此历史版本未记录生成输入的组件状态和缺口快照，无法从当前页面追溯补齐。", { exact: true }).waitFor();
    assert.doesNotMatch(await card.innerText(), /上下文身份 SHA-256：|输入警告/);
  } else if (mode === "malformed_v2") {
    await card.getByText("生成输入依据不可核对；不使用当前页面替代，不将此结果标为已验证事实。", { exact: true }).waitFor();
    assert.doesNotMatch(await card.innerText(), /上下文身份 SHA-256：|此历史版本未记录/);
  } else {
    const b = aiBasisGolden.v2.payload.input_basis;
    await card.getByText(`生成时整体状态：部分缺失 · 输入警告 ${b.warning_count} 条 · 未知项 ${b.unknown_count} 条`, { exact: true }).waitFor();
    await card.getByText(`上下文身份 SHA-256：${b.context_sha256}`, { exact: true }).waitFor();
    assert.match(await card.innerText(), /哈希不证明数据真实、完整或结论正确/);
  }
  await captureIntegratedCard({ page, card, name: `17-ai-basis-${mode}-${label}`, viewport, evidenceDir, captures });
  results.push(`${viewport.label}-17-ai-basis-${mode}-${label}`);
}
