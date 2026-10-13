import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
const require=createRequire(import.meta.url);
const {Locator}=require(path.join(path.dirname(require.resolve('playwright-core/package.json')),'lib/client/locator.js'));

test('actual Playwright pattern disclosure selector has a descendant-relative text condition',()=>{
 const source=readFileSync(new URL('./e2e/personal-review.browser.mjs',import.meta.url),'utf8');
 const expression=source.match(/const modeDisclosure = (.*);/)[1];
 const frame={_platform:{}};
 const page={getByText:(text,options)=>new Locator(frame,'').getByText(text,options)};
 const overview=new Locator(frame,'internal:testid=[data-testid="personal-review-panel"s]').first();
 const locator=Function('page','overview',`return ${expression}`)(page,overview);
 const inner=JSON.parse(locator._selector.split(' >> internal:has=')[1]);
 assert.match(inner,/internal:text=/);
 assert.doesNotMatch(inner,/personal-review-panel|nth=/,'has must search descendants of details, never re-enter its panel ancestor');
 assert.match(locator._selector,/personal-review-panel/,'outer owner remains the correct panel');
 const broken=overview.locator('details').filter({has:overview.getByText('模式卡 · 版本历史与复用',{exact:true})});
 assert.match(JSON.parse(broken._selector.split(' >> internal:has=')[1]),/personal-review-panel/,'negative control reproduces the rejected ancestor-scoped selector');
});
