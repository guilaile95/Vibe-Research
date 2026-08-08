import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const dailyReview = readFileSync(new URL("../src/pages/DailyReview.tsx", import.meta.url), "utf8");
const aiCard = readFileSync(new URL("../src/components/dailyReview/DailyReviewAiCard.tsx", import.meta.url), "utf8");
const lazyMarkdown = readFileSync(new URL("../src/components/ui/LazyMarkdownContent.tsx", import.meta.url), "utf8");

test("Daily Review keeps the one-second AI clock outside the page root", () => {
  assert.doesNotMatch(dailyReview, /setInterval\(.*setTaskNow/);
  assert.doesNotMatch(dailyReview, /useDailyReviewAiTaskStore/);
  assert.match(aiCard, /function DailyReviewAiProgress/);
  assert.match(aiCard, /window\.setInterval\(\(\) => setNow/);
});

test("Daily Review loads markdown rendering only when AI content exists", () => {
  assert.doesNotMatch(dailyReview, /react-markdown|remark-gfm/);
  assert.match(lazyMarkdown, /lazy\(\(\) => import\("@\/components\/ui\/MarkdownContent"\)\)/);
  assert.match(lazyMarkdown, /if \(!content\) return null/);
});

test("market overview keeps the approved strip and uses real global trend data", () => {
  assert.match(dailyReview, /aria-labelledby="market-overview-title"/);
  assert.match(dailyReview, /<GlobalMarketTrendChart trends=\{globalTrends\} \/>/);
  assert.match(dailyReview, /workspace-table hidden min-w-full lg:table/);
  assert.doesNotMatch(dailyReview, /sparklineData|Math\.(?:sin|cos|random)/);
});

test("Daily Review watchlist input has a programmatic label", () => {
  assert.match(dailyReview, /htmlFor="daily-review-watch-codes"/);
  assert.match(dailyReview, /id="daily-review-watch-codes"/);
});
