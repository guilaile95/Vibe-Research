/** Runs only inside the existing GitHub CI offline browser acceptance. */
import assert from "node:assert/strict";
import path from "node:path";
export async function runObservationWorkflows({ page, fixture, viewport, evidenceDir, results, captures }) {
  const card = page.getByTestId("observation-workflows");
  await card.getByText("暂无已记录异动；未采集不代表没有异动").waitFor();
  assert.equal(await card.getByLabel("观察交易日").inputValue(), "2026-07-31");
  assert.equal(await card.getByLabel("观察交易日").isDisabled(), true, "embedded review date belongs to the parent page");
  assert.equal(await card.locator('[data-testid^="observation-slot-"]').count(), 6);
  await card.getByRole("button", { name: "查看离线合成演示", exact: true }).click();
  await card.getByText(/纯合成离线演示 · 不写真实归档 · 非实盘验收/).waitFor();
  for (const slot of ["09:25", "09:35", "10:00", "11:30", "14:00", "15:00"]) {
    assert.match(await card.getByTestId(`observation-slot-${slot}`).innerText(), /已取样/);
  }
  assert.equal(await card.getByRole("button", { name: /仅运行本地任务/ }).count(), 0, "demo cannot mutate the real task store");
  await card.getByTestId("observation-slot-09:25").getByText("逐股来源与供应商时间").click();
  await card.getByTestId("observation-slot-09:25").getByText(/sh600000.*SYNTHETIC_FIXTURE/).waitFor();
  await card.evaluate(el => el.scrollIntoView({ block: "start", behavior: "instant" }));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const state = await card.evaluate(el => {
    const b = el.getBoundingClientRect();
    return { left: b.left, right: b.right, width: b.width, clientWidth: el.clientWidth, scrollWidth: el.scrollWidth, text: el.innerText };
  });
  assert.ok(state.left >= -1 && state.right <= viewport.width+1 && state.scrollWidth <= state.clientWidth+1, "observation card fits actual viewport");
  const filename = `${viewport.label}-observation-six-slot-preview.png`;
  await page.screenshot({ path: path.join(evidenceDir, filename), fullPage: false, animations: "disabled" });
  captures.push({ name: "observation-six-slot-preview", viewport, ...state, files: [filename] });
  fixture.malformedObservation("2026-07-31", { slots: null });
  await card.getByRole("button", { name: "返回真实归档", exact: true }).click();
  await card.getByText("观察资料日期或身份校验失败").waitFor();
  assert.equal(await card.locator('[data-testid^="observation-slot-"]').count(), 0, "malformed response does not render stale slots");
  await card.getByRole("button", { name: "重新读取", exact: true }).click();
  await card.getByText("暂无已记录异动；未采集不代表没有异动").waitFor();
  assert.equal(fixture.writes.length, 0);
  assert.equal(fixture.requests.filter(r => r.method !== "GET").length, 0);
  results.push(`${viewport.label}-observation-six-slots-preview-malformed-recovery`);
}
