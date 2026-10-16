import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/AiTaskBudgetNotice.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports, require: (name) => {
  if (name === "react/jsx-runtime") return jsx;
  throw Error(`unexpected dependency ${name}`);
} });

for (const [task, rounds, calls, seconds, characters, preparation] of [
  ["daily", 1, 1, 90, 12000, "复盘数据准备"],
  ["debate", 1, 3, 180, 36000, "底稿采集"],
  ["debate", 2, 5, 180, 60000, "底稿采集"],
]) {
  test(`production notice renders ${task}/${rounds} local limits and provider distinctions`, () => {
    const markup = renderToStaticMarkup(createElement(exports.AiTaskBudgetNotice, { task, rounds }));
    assert.match(markup, new RegExp(`本地等待预算为 ${seconds} 秒，${preparation}时间另计`));
    assert.match(markup, new RegExp(`API 最多 ${calls} 次请求，每次请求限制输出 2500 token`));
    assert.match(markup, new RegExp(`本地累计输出上限 ${characters} 字符`));
    assert.match(markup, new RegExp(`Codex Subscription 最多 ${calls} 次运行时调用`));
    assert.match(markup, /不能限制或核验服务端模型调用、token 或费用/);
    assert.match(markup, /远端停止与清理完成时间无法保证/);
    assert.match(markup, /未完成内容不能保存为完整结果/);
    assert.match(markup, /实际费用未知，不代表免费/);
  });
}

test("actual pages wire a pre-action notice and do not start requests from disclosure", () => {
  const daily = readFileSync(new URL("../src/pages/DailyReview.tsx", import.meta.url), "utf8");
  const debate = readFileSync(new URL("../src/pages/Debate.tsx", import.meta.url), "utf8");
  assert.match(daily, /<AiTaskBudgetNotice task="daily" \/>/);
  assert.match(debate, /<AiTaskBudgetNotice task="debate" rounds=\{rounds\} \/>/);
  assert.doesNotMatch(debate, /省额度可用 Codex Subscription|不消耗 token|约 6 万字/);
  assert.doesNotMatch(source, /fetch\(|useEffect|localStorage|setInterval/);
});
