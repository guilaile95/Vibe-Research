import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const srcRoot = join(import.meta.dirname, "..", "src");
const source = (path: string) => readFileSync(join(srcRoot, path), "utf8");

test("interactive GlassCard supports keyboard activation", () => {
  const card = source("components/ui/GlassCard.tsx");
  assert.ok(card.includes('role ?? "button"'));
  assert.ok(card.includes('event.key !== "Enter" && event.key !== " "'));
  assert.ok(card.includes("event.currentTarget.click()"));
});

test("settings access mode uses a native radio group", () => {
  const settings = source("pages/Settings.tsx");
  assert.ok(settings.includes("<fieldset"));
  assert.ok(settings.includes('type="radio"'));
  assert.ok(settings.includes('name="ai-access-mode"'));
});

test("data health sources have a keyboard-operable details control", () => {
  const dataHealth = source("pages/DataHealth.tsx");
  assert.ok(dataHealth.includes('aria-label={`查看 ${it.display_name} 的详情`}'));
  assert.ok(dataHealth.includes('className="absolute inset-0'));
});

test("stock search input has a programmatic label", () => {
  const stockData = source("pages/StockData.tsx");
  assert.ok(stockData.includes('htmlFor="stock-code"'));
  assert.ok(stockData.includes('id="stock-code"'));
});

test("privacy and AI panel preferences tolerate unavailable localStorage", () => {
  const privacyMode = source("hooks/usePrivacyMode.ts");
  const askAiButton = source("components/ui/AskAiButton.tsx");
  assert.match(privacyMode, /try\s*\{[\s\S]*?localStorage\.getItem/);
  assert.match(privacyMode, /try\s*\{[\s\S]*?localStorage\.setItem/);
  assert.match(askAiButton, /try\s*\{[\s\S]*?localStorage\.getItem/);
  assert.match(askAiButton, /try\s*\{[\s\S]*?localStorage\.setItem/);
});

test("AccessibleDialog owns the complete modal keyboard and focus contract", () => {
  const dialog = source("components/ui/AccessibleDialog.tsx");
  assert.ok(dialog.includes('role="dialog"'));
  assert.ok(dialog.includes('aria-modal="true"'));
  assert.ok(dialog.includes("aria-labelledby={titleId}"));
  assert.ok(dialog.includes('event.key === "Escape"'));
  assert.ok(dialog.includes('event.key !== "Tab"'));
  assert.ok(dialog.includes("last.focus()"));
  assert.ok(dialog.includes("first.focus()"));
  assert.ok(dialog.includes("triggerRef.current.focus()"));
  assert.ok(dialog.includes("closeOnOverlay = false"));
  assert.ok(dialog.includes("closeOnOverlay && event.target === event.currentTarget"));
  assert.ok(dialog.includes("createPortal("));
  assert.ok(dialog.includes("document.body"));
});

test("only dialogs that historically supported backdrop dismissal opt in", () => {
  const portfolio = source("pages/Portfolio.tsx");
  const evidence = source("pages/DecisionEvidence.tsx");
  const trades = source("pages/Trades.tsx");
  const feedback = source("pages/DecisionFeedback.tsx");

  assert.equal((portfolio.match(/closeOnOverlay/g) ?? []).length, 3);
  assert.equal((evidence.match(/closeOnOverlay/g) ?? []).length, 1);
  assert.doesNotMatch(trades, /closeOnOverlay/);
  assert.doesNotMatch(feedback, /closeOnOverlay/);
});

test("ledger and portfolio modals use one labelled AccessibleDialog primitive", () => {
  const pages = [
    ["pages/Trades.tsx", 3],
    ["pages/Portfolio.tsx", 3],
    ["pages/DecisionFeedback.tsx", 3],
    ["pages/DecisionEvidence.tsx", 1],
  ] as const;

  for (const [path, expectedDialogs] of pages) {
    const page = source(path);
    const labels = Array.from(page.matchAll(/labelledBy="([^"]+)"/g), (match) => match[1]);
    assert.equal((page.match(/<AccessibleDialog\b/g) || []).length, expectedDialogs, path);
    assert.equal(labels.length, expectedDialogs, path);
    assert.equal((page.match(/id="[^"]+-dialog-title"/g) || []).length, expectedDialogs, path);
    for (const label of labels) {
      assert.ok(page.includes(`id="${label}"`), `${path}: missing title ${label}`);
    }
    assert.ok(!page.includes('<div className="fixed inset-0 z-50'), path);
  }
});
