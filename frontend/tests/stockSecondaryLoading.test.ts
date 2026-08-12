import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");

test("secondary stock requests wait until their section approaches the viewport", () => {
  assert.match(source, /new IntersectionObserver/);
  assert.match(source, /rootMargin: "400px 0px"/);
  assert.match(source, /if \(!secondaryReady[^\n]+secondaryLoadedCodeRef/);
  assert.match(source, /optional\("融资融券", api\.margin\(codeToLoad\), setMargin\)/);
  assert.match(source, /optional\("投资者互动", api\.investorQa\(codeToLoad\), setQa\)/);
});

test("secondary stock request failures are surfaced instead of silently swallowed", () => {
  assert.match(source, /setSecondaryFailures\(failures\)/);
  assert.match(source, /部分扩展数据暂不可用/);
  assert.doesNotMatch(source, /api\.margin\(c\)\.then\([^\n]+\.catch\(\(\) => \{\}\)/);
});
