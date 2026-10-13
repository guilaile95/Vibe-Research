import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/pages/Portfolio.tsx', import.meta.url), 'utf8');
const body = source.match(/const generateAdvice = async \(\) => \{([\s\S]*?)\n  \};/)[1];
const code = ts.transpileModule(`async function run() {${body}}`, {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const create = new Function('loadLlm', 'setErr', 'usePortfolioAdviceTaskStore', 'confirm', 'adviceLoading', 'adviceRequest', `${code}; return run;`);
const cfg = { provider:'deepseek', model:'synthetic-model', baseURL:'https://provider.example/v1' };

test('portfolio advice discloses destination and sensitive categories; declining sends nothing', async () => {
  let calls = 0, prompt = '';
  const run = create(()=>cfg, ()=>{}, {getState:()=>({start:()=>{calls++;}})}, text=>{prompt=text; return false;}, false, 'Synthetic request');
  await run();
  assert.equal(calls, 0);
  assert.match(prompt, /provider.example/);
  for(const text of ['持股数量', '成本', '市值', '盈亏', '原样发送']) assert.ok(prompt.includes(text));
});

test('affirmative confirmation permits exactly the requested analysis', async () => {
  const calls = [];
  await create(()=>cfg, ()=>{}, {getState:()=>({start:(...args)=>calls.push(args)})}, ()=>true, false, 'Synthetic request')();
  assert.deepEqual(calls, [[cfg, 'Synthetic request']]);
});

test('invalid destination fails before consent or model task; destination omits URL credentials', async () => {
  let called = false, error = '';
  await create(()=>({...cfg,baseURL:'broken'}), e=>{error=e;}, {}, ()=>{called=true;}, false, '')();
  assert.equal(called,false); assert.match(error,/无法确认/);
  let prompt = '';
  await create(()=>({...cfg,baseURL:'https://synthetic:secret@provider.example/v1?token=private'}), ()=>{}, {}, text=>{prompt=text;return false;}, false,'')();
  assert.doesNotMatch(prompt,/secret|private|synthetic:/);
});
