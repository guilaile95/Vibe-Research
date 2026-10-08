import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { injectStorageFailure, nativeStorageProbe, scenarios } from "./e2e/nav-storage.browser.mjs";

function fixture(scenario) {
  const values = new Map([["vr-sidebar", "collapsed"]]);
  class Storage {
    getItem(key) { return values.get(key) ?? null; }
    setItem(key, value) { values.set(key, value); }
  }
  const window = { localStorage: new Storage() };
  const scope = vm.createContext({ window, Storage, DOMException });
  vm.runInContext('Object.defineProperty(globalThis, "localStorage", { get: () => window.localStorage })', scope);
  vm.runInContext(`(${injectStorageFailure.toString()})(${JSON.stringify(scenario)})`, scope);
  return { scope, values, probe: () => vm.runInContext(`(${nativeStorageProbe.toString()})()`, scope) };
}
test("read and getter injection are explicit SecurityErrors", () => {
  for (const scenario of ["injected-read", "injected-getter"]) {
    const f = fixture(scenario);
    assert.equal(f.probe(), "SecurityError");
    assert.equal(f.values.get("vr-sidebar"), "collapsed");
  }
});
test("write failure leaves readable prior state intact", () => {
  for (const [scenario, name] of [["injected-write-security", "SecurityError"], ["injected-write-quota", "QuotaExceededError"]]) {
    const f = fixture(scenario);
    assert.equal(f.probe(), "available");
    assert.throws(() => vm.runInContext('localStorage.setItem("vr-sidebar", "expanded")', f.scope), { name });
    assert.equal(f.values.get("vr-sidebar"), "collapsed");
  }
});
test("native policy mode does not inject denial; browser must independently prove it", () => {
  for (const scenario of ["native-policy", "normal", "default", "invalid"]) {
    const f = fixture(scenario);
    assert.equal(f.probe(), "available");
    vm.runInContext('localStorage.setItem("vr-sidebar", "expanded")', f.scope);
    assert.equal(f.values.get("vr-sidebar"), "expanded");
  }
  assert.equal(scenarios.length, 8);
  assert.equal(new Set(scenarios).size, 8);
});
