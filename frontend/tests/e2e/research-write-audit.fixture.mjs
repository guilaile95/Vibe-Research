// Observes native storage attempts without replacing IndexedDB or changing data.
// Callers flush before phase changes; preference writes are not business writes.
export async function installResearchWriteAudit(context, phase) {
  const events = [];
  await context.exposeBinding('__recordResearchWrite', (_source, event) => events.push({ ...event, phase: event.phase ?? phase() }));
  await context.addInitScript(() => {
    window.__researchWritePending = [];
    const record = event => {
      const pending = window.__recordResearchWrite({ ...event, phase: window.__researchWritePhase ?? null });
      window.__researchWritePending.push(pending);
    };
    for (const method of ['add', 'put', 'delete', 'clear']) {
      const original = IDBObjectStore.prototype[method];
      IDBObjectStore.prototype[method] = function(...args) {
        if (this.transaction.db.name === 'vr-research-workflow') record({ kind: 'research', store: this.name, method });
        return original.apply(this, args);
      };
    }
    for (const method of ['setItem', 'removeItem', 'clear']) {
      const original = Storage.prototype[method];
      Storage.prototype[method] = function(...args) {
        const key = args[0];
        if (this === localStorage && (method === 'clear' || ['vr-notes', 'vr-notes.v2', 'vr-research-resume-v1'].includes(key))) record({ kind: method === 'clear' ? 'all-local-storage' : ['vr-notes', 'vr-notes.v2'].includes(key) ? 'note' : 'navigation-preference', key: key ?? null, method });
        return original.apply(this, args);
      };
    }
  });
  events.phases = [];
  events.flush = page => page.evaluate(async () => { await Promise.all(window.__researchWritePending?.splice(0) ?? []); });
  events.setPhase = (page, value) => { events.phases.push(value); return page.evaluate(async phase => { await Promise.all(window.__researchWritePending?.splice(0) ?? []); window.__researchWritePhase = phase; }, value); };
  return events;
}
