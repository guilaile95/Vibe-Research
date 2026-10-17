/** Source contract only; actual scroll geometry is validated by browser CI. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/components/layout/Layout.tsx', import.meta.url), 'utf8');
const classes = (value) => new Set(value.split(/\s+/));

test('mobile navigation clearance belongs outside the independently scrolling main', () => {
  const main = source.match(/<main\b[^>]*className="([^"]+)"/);
  assert.ok(main, 'main keeps its explicit scrollport classes');
  const mainClasses = classes(main[1]);
  for (const name of ['mt-16', 'md:mt-0', 'flex-1', 'overflow-auto']) {
    assert.ok(mainClasses.has(name), `main must retain ${name}`);
  }
});

test('moving clearance outside main preserves initial mobile and desktop content offsets', () => {
  const wrapper = source.match(/"(mx-auto w-full [^"]+)"/);
  assert.ok(wrapper, 'content wrapper remains present');
  const wrapperClasses = classes(wrapper[1]);
  assert.ok(wrapperClasses.has('pt-0'), 'do not duplicate the mobile 64px outer clearance');
  assert.ok(wrapperClasses.has('md:pt-7'), 'desktop content padding remains unchanged');
  assert.ok(!wrapperClasses.has('pt-16'), 'scrolling padding must not provide the mobile clearance');
});
