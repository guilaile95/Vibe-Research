import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import ts from "typescript";

// Compile the production dividend JSX branch rather than restating its null guard.
// The Metric stub exposes its actual label and value; this is not browser QA.
const filename = fileURLToPath(new URL("../src/pages/StockData.tsx", import.meta.url));
const source = ts.createSourceFile(filename, readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const matches = [];
function visit(node) {
  if (ts.isJsxExpression(node) && node.getText(source).startsWith('{dividend[0] && <Metric')) matches.push(node.getText(source));
  ts.forEachChild(node, visit);
}
visit(source);
assert.equal(matches.length, 1, "Find exactly one production dividend JSX expression");
const bundle = await build({ stdin: {
  contents: `import React from "react"; function Metric({k, v, sub}) { return <div>{k}:{v}:{sub}</div>; } export function Dividend({dividend}) { return <>${matches[0]}</>; }`,
  resolveDir: fileURLToPath(new URL("../", import.meta.url)), loader: "tsx",
}, bundle: true, write: false, format: "esm", platform: "node", tsconfig: fileURLToPath(new URL("../tsconfig.json", import.meta.url)) });
const { Dividend } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
for (const [name, value, expected] of [
  ["zero", 0, "0 元"], ["fractional", 0.125, "0.125 元"],
  ["raw ten-share amount", 12.5, "12.5 元"], ["null", null, "未知"], ["absent", undefined, "未知"],
]) {
  test(`production dividend metric: ${name}`, () => {
    const html = renderToStaticMarkup(createElement(Dividend, {dividend: [{bonus_rmb: value, date: "2026-09-01"}]}));
    assert.ok(html.includes("最近税前派息(每10股)"));
    assert.ok(html.includes(expected));
    assert.ok(!html.includes("null") && !html.includes("undefined"));
  });
}
test("production dividend metric preserves empty array", () => {
  assert.equal(renderToStaticMarkup(createElement(Dividend, {dividend: []})), "");
});

const calendarFilename = fileURLToPath(new URL("../src/components/campaign/ResearchEventCalendar.tsx", import.meta.url));
const calendarSource = ts.createSourceFile(calendarFilename, readFileSync(calendarFilename, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const detailsFunction = calendarSource.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === "detailEntries");
assert.ok(detailsFunction, "Use production calendar detail formatter");
const compiled = ts.transpileModule(`export ${detailsFunction.getText(calendarSource)}`, {compilerOptions: {module: ts.ModuleKind.ESNext}});
const {detailEntries} = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
for (const amount of [0, 0.125, 12.5]) {
  test(`calendar cash dividend explicitly uses per-10-share unit: ${amount}`, () => {
    assert.deepEqual(detailEntries({details: {bonus_rmb: amount, bonus_rmb_unit: "CNY/10_shares"}}), [["税前派息（元/每10股）", String(amount)]]);
  });
}
test("calendar does not fabricate cash for missing dividend amount", () => {
  assert.deepEqual(detailEntries({details: {bonus_rmb: null}}), []);
  assert.deepEqual(detailEntries({details: {}}), []);
});
