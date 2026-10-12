/** Best-effort diagnostics: a screenshot failure must not erase DOM/request evidence. */
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

export async function captureBrowserFailure({ page, output, prefix, selector, error, audit }) {
  mkdirSync(output, { recursive: true });
  const record = { error: String(error), selector, audit, files: [], capture_errors: [] };
  const attempt = async (name, action) => {
    try { await action(); record.files.push(name); }
    catch (failure) { record.capture_errors.push({ name, error: String(failure) }); }
  };
  const save = (name, value) => writeFileSync(path.join(output, name), value, 'utf8');
  if (page && !page.isClosed()) {
    await attempt(`${prefix}-failure.html`, async () => save(`${prefix}-failure.html`, await page.content()));
    const card = page.locator(selector).first();
    await attempt(`${prefix}-failure-fragment.html`, async () => {
      const count = await card.count();
      save(`${prefix}-failure-fragment.html`, count ? await card.evaluate(el => el.outerHTML) : '<!-- Target is not mounted -->');
    });
    await attempt(`${prefix}-failure.png`, () => page.screenshot({ path: path.join(output, `${prefix}-failure.png`), fullPage: false, timeout: 5000 }));
    await attempt(`${prefix}-failure-card.png`, async () => {
      if (!await card.count() || !await card.isVisible()) throw Error('Target is absent or hidden; see DOM and viewport evidence');
      await card.evaluate(el => el.scrollIntoView({ block: 'start', behavior: 'instant' }));
      const clip = await card.evaluate(el => {
        const b = el.getBoundingClientRect(), m = el.closest('main')?.getBoundingClientRect() || { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
        const x = Math.max(0, b.left, m.left), y = Math.max(0, b.top, m.top);
        return { x, y, width: Math.min(innerWidth, b.right, m.right) - x, height: Math.min(innerHeight, b.bottom, m.bottom) - y };
      });
      if (clip.width <= 0 || clip.height <= 0) throw Error('Target has no visible crop');
      await page.screenshot({ path: path.join(output, `${prefix}-failure-card.png`), clip, timeout: 5000 });
    });
  }
  save(`${prefix}-failure.json`, JSON.stringify(record, null, 2));
  return record;
}
