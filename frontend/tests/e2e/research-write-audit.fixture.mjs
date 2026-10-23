// Observes native storage attempts without replacing IndexedDB or changing data.
// Callers classify phases explicitly; navigation preferences are not business writes.
export async function installResearchWriteAudit(context, phase) {
  const events = [];
  await context.exposeBinding('__recordResearchWrite', (_source, event) => events.push({ phase: phase(), ...event }));
  await context.addInitScript(() => {
    for (const method of ['add', 'put', 'delete', 'clear']) {
      const original = IDBObjectStore.prototype[method];
      IDBObjectStore.prototype[method] = function(...args) {
        if (this.transaction.db.name === 'vr-research-workflow') void window.__recordResearchWrite({ kind: 'research', store: this.name, method });
        return original.apply(this, args);
      };
    }
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (this === localStorage && ['vr-notes', 'vr-research-resume-v1'].includes(key)) void window.__recordResearchWrite({ kind: key === 'vr-notes' ? 'note' : 'navigation-preference', key, method: 'setItem' });
      return original.call(this, key, value);
    };
  });
  return events;
}
