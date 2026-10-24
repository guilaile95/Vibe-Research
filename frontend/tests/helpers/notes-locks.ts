// Deterministic Web Locks stand-in for unit tests. Browser CI uses native locks.
import { beforeEach } from 'node:test';
export function installNotesLocks() {
  let queue = Promise.resolve();
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    locks: { request: (_name: string, _options: unknown, work: () => unknown) => {
      const next = queue.then(work); queue = next.then(() => undefined, () => undefined); return next;
    } },
  } });
}
beforeEach(installNotesLocks);
