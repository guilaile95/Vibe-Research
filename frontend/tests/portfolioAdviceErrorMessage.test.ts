import assert from "node:assert/strict";
import test from "node:test";
import { getPortfolioAdviceErrorMessage } from "../src/lib/portfolioAdviceErrors.ts";

function apiError(message: string, status: number) {
  return Object.assign(new Error(message), { status });
}

test("maps 409 / 503 / 500 business statuses", () => {
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("当前没有持仓，无法生成持仓操作建议", 409)),
    "当前没有持仓，无法生成持仓操作建议",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("市场核心数据暂不可用，无法生成可靠的持仓操作建议", 503)),
    "市场核心数据暂不可用，无法生成可靠的持仓操作建议",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("持仓操作建议生成失败", 500)),
    "持仓操作建议生成失败",
  );
});

test("passes through classified 502 model messages", () => {
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("持仓建议模型调用失败", 502)),
    "持仓建议模型调用失败",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("持仓建议模型输出无效", 502)),
    "持仓建议模型输出无效",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(
      apiError("持仓建议模型鉴权失败，请检查 API Key 或重新登录 CLI", 502),
    ),
    "持仓建议模型鉴权失败，请检查 API Key 或重新登录 CLI",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(
      apiError("持仓建议模型网络调用失败，请检查网络后重试", 502),
    ),
    "持仓建议模型网络调用失败，请检查网络后重试",
  );
});

test("does not show opaque or leaky 502 as 参数无效", () => {
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("something upstream leaked sk-xxx", 502)),
    "持仓建议生成失败，请重试",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("请求参数无效", 502)),
    "持仓建议生成失败，请重试",
  );
});

test("maps 400 missing AI config clearly", () => {
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("缺少模型配置，请先在「接入 AI」里选择", 400)),
    "缺少模型配置，请先在「接入 AI」里选择",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(apiError("缺少 Base URL 或 API Key，请先在「接入 AI」里填写", 400)),
    "缺少 Base URL 或 API Key，请先在「接入 AI」里填写",
  );
  assert.equal(
    getPortfolioAdviceErrorMessage(
      apiError("未检测到「claude」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。", 400),
    ),
    "未检测到「claude」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。",
  );
});

test("non-status error falls back", () => {
  assert.equal(getPortfolioAdviceErrorMessage(new Error("boom")), "持仓建议生成失败，请重试");
});
