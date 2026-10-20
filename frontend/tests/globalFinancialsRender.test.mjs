import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import ts from "typescript";

const filename = fileURLToPath(new URL("../src/pages/StockData.tsx", import.meta.url));
const source = ts.createSourceFile(filename, readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const cards = [];
const declarations = new Map();
function visit(node) {
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === "GlassCard" && node.getText(source).includes("东财 GMAININDICATOR，最新报告期")) cards.push(node.getText(source));
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) declarations.set(node.name.text, node.initializer.getText(source));
  ts.forEachChild(node, visit);
}
visit(source);
assert.equal(cards.length, 1);
const helpers = ["round2", "curOf", "bigMoney", "mktName", "pctStr"].map(name => {
  assert.ok(declarations.has(name), name);
  return `const ${name} = ${declarations.get(name)};`;
}).join("\n");
const bundle = await build({ stdin: { contents: `
  import { GlassCard } from "./src/components/ui/GlassCard";
  import { BarChart3 } from "lucide-react";
  import { financialAmount, financialEps } from "./src/lib/globalFinancials";
  ${helpers}
  export function Card({gstock}) { return (${cards[0]}); }
  export function context(gstock) { return (${declarations.get("gAiContext")}); }
`, resolveDir: fileURLToPath(new URL("../", import.meta.url)), loader: "tsx" }, bundle: true, write: false, format: "esm", platform: "node", tsconfig: fileURLToPath(new URL("../tsconfig.json", import.meta.url)) });
const { Card, context } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
const base = { code: "00001", name: "Synthetic", market: "HK", quote: { price: 10, change_pct: 0, mcap: 1e8 }, metrics: { report_date: "2026-06-30", reporting_currency: "CNY", amount_unit: "PROVIDER_RAW_SCALE_UNVERIFIED", amount_scale_to_currency_units: null, revenue: 1e8, net_profit: 0, eps: 2, roe: 3 } };
test("actual production financial card and AI expression agree on report currency and raw scale", () => {
  const html = renderToStaticMarkup(createElement(Card, { gstock: base }));
  const ai = context(base);
  for (const output of [html, ai]) {
    assert.match(output, /人民币，原始值；金额单位比例未验证/);
    assert.match(output, /0（人民币，原始值/);
    assert.match(output, /2.00 人民币\/股/);
    assert.doesNotMatch(output, /亿人民币/);
  }
  assert.match(ai, /总市值 1 亿港元/);
});
test("old financial response with no currency or scale renders unknown in both actual sinks", () => {
  const gstock = { ...base, metrics: { ...base.metrics, reporting_currency: undefined, amount_unit: undefined } };
  for (const output of [renderToStaticMarkup(createElement(Card, { gstock })), context(gstock)]) {
    assert.match(output, /报告币种未知/);
    assert.match(output, /金额单位比例未验证/);
  }
});
