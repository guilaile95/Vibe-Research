import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import ts from "typescript";

// Compile the actual production JSX branch, including its actual GlassCard.
// Do not restate the condition here: removing !gstock must break this test.
// Browser CI separately exercises full-component request/history transitions.
const filename = fileURLToPath(new URL("../src/pages/StockData.tsx", import.meta.url));
const source = ts.createSourceFile(filename, readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const prompt = "输入一个 6 位股票代码，拉取它的行情、估值、研报与新闻。";
const matches = [];
function visit(node) {
  if (ts.isJsxExpression(node) && node.getText(source).includes(prompt)) matches.push(node.getText(source));
  ts.forEachChild(node, visit);
}
visit(source);
assert.equal(matches.length, 1, "Find exactly one production initial-guidance JSX expression");
const bundle = await build({ stdin: {
  contents: `import { GlassCard } from "./src/components/ui/GlassCard"; export function InitialGuidance({val, gstock, err, loading}) { return <>${matches[0]}</>; }`,
  resolveDir: fileURLToPath(new URL("../", import.meta.url)), loader: "tsx",
}, bundle: true, write: false, format: "esm", platform: "node", tsconfig: fileURLToPath(new URL("../tsconfig.json", import.meta.url)) });
const { InitialGuidance } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
const empty = { val: null, gstock: null, err: null, loading: false };
for (const [name, state, visible] of [
  ["unqueried entry", empty, true],
  ["loading overseas query", { ...empty, loading: true }, false],
  ["failed query", { ...empty, err: "Synthetic failure" }, false],
  ["A-share quote", { ...empty, val: { code: "000001" } }, false],
  ...["AAPL", "00700", "005930.KS"].flatMap(code => [
    [`${code} with financials`, { ...empty, gstock: { code, metrics: { report_date: "2026-06-30" } } }, false],
    [`${code} without financials`, { ...empty, gstock: { code, metrics: null } }, false],
  ]),
  ["retry loading", { ...empty, loading: true }, false],
  ["cleared entry after Back", empty, true],
]) {
  test(`MARKET-02 production guidance: ${name}`, () => {
    const html = renderToStaticMarkup(createElement(InitialGuidance, state));
    assert.equal(html.includes(prompt), visible);
    if (!visible) assert.equal(html, "", "Do not leave a blank guidance card");
  });
}
