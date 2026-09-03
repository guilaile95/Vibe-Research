import assert from "node:assert/strict";
import { chromium } from "playwright";

const FRONTEND_URL = process.env.VIBE_FRONTEND_URL || "http://127.0.0.1:5899";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  // Mock native intel responses for stable UI verification
  await page.route("**/api/native-intel/hotlist*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "normal",
        sources: [
          {
            source_id: "hotlist-cls-hot",
            name: "财联社热门",
            hint: "macro",
            enabled: true,
            origin: "system",
            last_run_status: "ok",
          },
        ],
        items: [
          {
            item_id: 101,
            title: "科技股全线走强",
            url: "https://cls.cn/101",
            source_id: "hotlist-cls-hot",
            source_name: "财联社热门",
            hint: "macro",
            first_seen_at: "2026-09-03T08:00:00Z",
            last_seen_at: "2026-09-03T10:00:00Z",
            observation_count: 2,
            rank: 1,
            previous_rank: 3,
            rank_delta: 2,
            current_state: "ON_LIST",
          },
        ],
      }),
    });
  });

  await page.route("**/api/native-intel/sources*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "normal",
        sources: [
          {
            source_id: "hotlist-cls-hot",
            name: "财联社热门",
            hint: "macro",
            url: "https://newsnow.busiyi.world/api/s?id=cls-hot&latest",
            source_type: "hotlist",
            has_real_rank: true,
            enabled: true,
            origin: "system",
          },
        ],
      }),
    });
  });

  try {
    // 1. 验证热榜面板渲染
    await page.goto(`${FRONTEND_URL}/intel`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);

    const hotlistTab = page.locator("button", { hasText: "实时热榜" });
    if (await hotlistTab.isVisible()) {
      await hotlistTab.click();
      await page.waitForSelector("[data-testid='native-intel-hotlist-panel']", { timeout: 5000 });
      const itemTitle = page.locator("text=科技股全线走强");
      await itemTitle.waitFor({ timeout: 5000 });
      console.log("Hotlist Panel verification: PASS");
    }

    // 2. 验证设置页资讯源管理
    await page.goto(`${FRONTEND_URL}/settings`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    const sourceSection = page.locator("text=资讯源与热榜管理");
    await sourceSection.waitFor({ timeout: 5000 });
    const clsSource = page.locator("text=财联社热门");
    await clsSource.waitFor({ timeout: 5000 });
    console.log("Settings Source Registry verification: PASS");
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("Hotlist E2E verification failed:", err);
  process.exit(1);
});
