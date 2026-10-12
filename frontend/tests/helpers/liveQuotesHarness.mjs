import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Execute the actual hook with deterministic hooks, clock, visibility and timers.
// No API module or browser/network runtime is imported.
const source = readFileSync(new URL('../../src/hooks/useLiveQuotes.ts', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const helper = readFileSync(new URL('../../src/lib/quoteSnapshot.ts', import.meta.url), 'utf8').replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const compiled = ts.transpileModule(helper + '\n' + source + '\nglobalThis.hook = useLiveQuotes;', {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;
export const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
export function harness({ enabled = false, codes = ['000001'], trading = true } = {}) {
  const slots = [], effects = [], pendingEffects = [], requests = [], timers = new Map(), listeners = new Set();
  let index = 0, timerId = 0, result, now = 1791770400000;
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const useState = (initial) => {
    const i = index++;
    if (!(i in slots)) slots[i] = initial;
    return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
  };
  const useRef = initial => { const i = index++; return slots[i] ??= { current: initial }; };
  const useCallback = (fn, deps) => {
    const i = index++; if (!equal(slots[i]?.deps, deps)) slots[i] = { fn, deps }; return slots[i].fn;
  };
  const useEffect = (fn, deps) => {
    const i = index++;
    if (!equal(effects[i]?.deps, deps)) pendingEffects.push(() => {
      effects[i]?.cleanup?.(); effects[i] = { deps, setup: fn, cleanup: fn() };
    });
  };
  // Monday 10:00 Beijing; no wall-clock or holiday dependency.
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const context = {
    useState, useRef, useCallback, useEffect, Date: Clock,
    api: { quote: requested => new Promise((resolve, reject) => requests.push({ requested, resolve, reject })) },
    window: {
      setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
      clearTimeout: id => timers.delete(id),
    },
    document: {
      hidden: false,
      addEventListener: (_, fn) => listeners.add(fn),
      removeEventListener: (_, fn) => listeners.delete(fn),
    },
  };
  vm.runInNewContext(compiled, context);
  context.isTradingHours = () => trading;
  const render = (next = {}) => {
    enabled = next.enabled ?? enabled; codes = next.codes ?? codes;
    index = 0; result = context.hook(codes, enabled);
    while (pendingEffects.length) pendingEffects.shift()();
    return result;
  };
  render();
  return {
    requests, timers, listeners, render,
    setNow(value) { now = value; },
    state: () => { index = 0; return context.hook(codes, enabled); },
    visibility(hidden) { context.document.hidden = hidden; for (const fn of listeners) fn(); },
    setTrading(value) { trading = value; },
    fire() {
      assert.equal(timers.size, 1, 'exactly one timer owns the next tick');
      const [id, timer] = timers.entries().next().value; timers.delete(id); timer.fn();
    },
    unmount() { for (const effect of effects) effect?.cleanup?.(); },
    replayEffects() {
      for (const effect of effects) effect?.cleanup?.();
      for (const effect of effects) if (effect) effect.cleanup = effect.setup();
    },
  };
}
