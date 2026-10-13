import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import ts from "typescript";

const root = fileURLToPath(new URL("../", import.meta.url));
const bundle = await build({
  entryPoints: [`${root}src/components/dailyReview/TodayResearchLeads.tsx`],
  bundle: true, write: false, format: "esm", platform: "node", tsconfig: `${root}tsconfig.json`,
  plugins: [{ name: "isolate-navigation-only", setup(build) {
    build.onResolve({ filter: /^(react-router-dom|\.\/LeadAnalysisButton)$/ }, args => ({ path: args.path, namespace: "navigation-fixture" }));
    build.onLoad({ filter: /.*/, namespace: "navigation-fixture" }, () => ({
      contents: "export const Link = ({children}) => children; export const LeadAnalysisButton = () => null;", loader: "js",
    }));
  } }],
});
const { TodayResearchLeads } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
const render = emotion => renderToStaticMarkup(createElement(TodayResearchLeads, {
  review: { short_term_emotion: { status: "partial", data: emotion } }, loading: false, onOpenDetail() {},
}));

test("lead keeps inferred date visible while unknown counts remain unknown", () => {
  const html = render({ date: "2026-10-09", date_verified: false, zt_count: 3, dt_count: null, max_boards: null });
  assert.match(html, /请求交易日（来源日期未核实）/);
  assert.match(html, /2026-10-09/);
  assert.match(html, /涨停 3 家 · 跌停 — 家 · 最高 — 板/);
  assert.match(html, /数据不完整/);
  assert.doesNotMatch(html, /跌停 0 家/);
});

test("old saved review without provenance retains numeric zero and legacy date label", () => {
  const emotion = { date: "2026-09-30", zt_count: 0, dt_count: 0, max_boards: 0 };
  const before = JSON.stringify(emotion);
  const html = render(emotion);
  assert.match(html, /涨停 0 家 · 跌停 0 家 · 最高 0 板/);
  assert.match(html, /数据日期 2026-09-30/);
  assert.doesNotMatch(html, /来源日期未核实/);
  assert.equal(JSON.stringify(emotion), before);
});

// Execute the actual production empty-list JSX rather than restating its rule.
const filename = `${root}src/pages/DailyReview.tsx`;
const source = ts.createSourceFile(filename, readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const expressions = [];
function visit(node) {
  if (ts.isConditionalExpression(node) && node.getText(source).includes("连板股数据暂不可用") && !node.getText(source).includes("<table")) expressions.push(node.getText(source));
  ts.forEachChild(node, visit);
}
visit(source);
assert.equal(expressions.length, 1);
const emptyBundle = await build({ stdin: { contents: `export function Empty({emotion}) { return <p>{${expressions[0]}}</p>; }`, loader: "tsx", resolveDir: root },
  bundle: true, write: false, format: "esm", platform: "node", tsconfig: `${root}tsconfig.json` });
const { Empty } = await import(`data:text/javascript;base64,${Buffer.from(emptyBundle.outputFiles[0].text).toString("base64")}`);

test("empty ladder distinguishes unavailable from observed zero without rewriting history", () => {
  assert.match(renderToStaticMarkup(createElement(Empty, { emotion: { lianban_count: null } })), /数据暂不可用/);
  assert.match(renderToStaticMarkup(createElement(Empty, { emotion: { lianban_count: 0 } })), /该池未见 2 板以上个股/);
});
