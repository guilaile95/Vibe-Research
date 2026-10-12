// Navigation commits and mode-effect cleanup can follow the URL change.
// Wait for owned DOM state, without forcing clicks or sleeping a fixed interval.
const readiness = { state: "visible", timeout: 10000 };

export async function waitForScreenerMode(page, mode) {
  const id = { candidate: "candidate-pool-tab", "full-market": "full-market-tab" }[mode];
  if (!id) throw new Error(`Unsupported screener readiness mode: ${mode}`);
  await page.waitForURL(url => url.searchParams.get("mode") === mode, { timeout: 10000 });
  await page.locator(`[data-testid="${id}"][aria-selected="true"]`).waitFor(readiness);
  const panel = mode === "candidate"
    ? page.getByPlaceholder("000001 600519", { exact: true })
    : page.getByTestId("full-market-form");
  await panel.waitFor(readiness);
}

export async function waitForFullMarketLoading(page, loading) {
  await page.locator(`[data-testid="run-full-market"]:${loading ? "disabled" : "enabled"}`).waitFor(readiness);
  await page.getByRole("button", { name: loading ? "查询中…" : "运行全市场筛选", exact: true }).waitFor(readiness);
}
