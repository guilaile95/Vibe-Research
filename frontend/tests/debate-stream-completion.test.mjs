import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";

const bundle = await build({
  entryPoints: [fileURLToPath(new URL("../src/lib/agents.ts", import.meta.url))],
  bundle: true, write: false, format: "esm", platform: "node",
  tsconfig: fileURLToPath(new URL("../tsconfig.json", import.meta.url)),
});
const { debateStream, reflectStream } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
const plan = rounds => rounds >= 2 ? ["bull", "bear", "bull_rebut", "bear_rebut", "referee"] : ["bull", "bear", "referee"];
const transcript = rounds => plan(rounds).map(stage => ({ stage, content: `SYNTHETIC_${stage}` }));
const events = (rounds = 1) => [
  ...transcript(rounds).flatMap(({ stage, content }) => [
    { type: "stage", stage, label: stage }, { type: "delta", stage, text: content },
    { type: "stage_done", stage, label: stage, content },
  ]),
  { type: "done", code: "600519", stages: transcript(rounds) },
];
const encode = value => value.map(event => JSON.stringify(event)).join("\n") + "\n";

test.beforeEach(t => {
  const storage = globalThis.localStorage;
  globalThis.localStorage = { getItem: key => key === "vr-llm" ? JSON.stringify({ provider: "cli-codex", model: "synthetic" }) : null };
  t.after(() => { if (storage === undefined) delete globalThis.localStorage; else globalThis.localStorage = storage; });
});

test("only complete one- and two-round terminal transcripts resolve", async t => {
  for (const rounds of [1, 2]) {
    t.mock.method(globalThis, "fetch", async () => new Response(encode(events(rounds))));
    const displayed = [];
    await debateStream("600519", rounds, { onStageDone: stage => displayed.push(stage) });
    assert.deepEqual(displayed, plan(rounds));
  }
});

test("EOF retains partial display but rejects even after all stage_done events", async t => {
  for (const fixture of [[], events().slice(0, 3), events().slice(0, -1)]) {
    t.mock.method(globalThis, "fetch", async () => new Response(encode(fixture)));
    const displayed = [];
    await assert.rejects(debateStream("600519", 1, { onStageDone: stage => displayed.push(stage) }), /辩论未完整结束/);
    assert.equal(displayed.length, fixture.filter(ev => ev.type === "stage_done").length);
  }
});

test("malformed done, missing or duplicate stages, failed roles, and post-terminal events reject", async t => {
  const normal = events();
  const terminal = normal.at(-1);
  const failures = [
    [...normal.slice(0, 3), { ...terminal, stages: transcript(1).slice(0, 1) }],
    [...normal.slice(0, -1), { type: "done" }],
    [...normal.slice(0, -1), { ...terminal, stages: [] }],
    [...normal.slice(0, -1), { ...terminal, code: "000001" }],
    [...normal.slice(0, -1), { ...terminal, stages: transcript(1).map(t => ({ ...t, content: "mismatch" })) }],
    normal.filter(ev => !(ev.type === "stage_done" && ev.stage === "bear")),
    normal.filter(ev => !(ev.type === "stage" && ev.stage === "bear")),
    [{ type: "stage", stage: "bull", label: "duplicate" }, ...normal],
    normal.map(ev => ev.type === "stage_done" && ev.stage === "bull" ? { ...ev, failed: true } : ev),
    [{ type: "error", message: "SYNTHETIC_ERROR" }, ...normal],
    [...normal, { type: "stage", stage: "bull", label: "late" }],
  ];
  for (const fixture of failures) {
    t.mock.method(globalThis, "fetch", async () => new Response(encode(fixture)));
    await assert.rejects(debateStream("600519", 1), /辩论未完整结束/);
  }
});

test("truncated or broken transport rejects; retry starts with fresh protocol state", async t => {
  const responses = [
    new Response(encode(events().slice(0, -1)) + '{"type":"done"'),
    new Response(new ReadableStream({ start(controller) { controller.error(new Error("synthetic disconnect")); } })),
    new Response(encode(events(2))),
  ];
  t.mock.method(globalThis, "fetch", async () => responses.shift());
  await assert.rejects(debateStream("600519", 1));
  await assert.rejects(debateStream("600519", 1), /synthetic disconnect/);
  await debateStream("600519", 2);
});

test("abort still rejects when transport delivers a late complete response", async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async () => { controller.abort(); return new Response(encode(events())); });
  await assert.rejects(debateStream("600519", 1, {}, controller.signal), { name: "AbortError" });
});

test("Reflection retains its own terminal event contract", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response(encode([{ type: "done", content: "SYNTHETIC_REFLECTION", truncated: true }])));
  let done;
  await reflectStream("synthetic source", "synthetic title", { onDone: (...args) => { done = args; } });
  assert.deepEqual(done, ["SYNTHETIC_REFLECTION", true]);
});

for (const [name, fixture] of [
  ['empty EOF', []],
  ['partial EOF', [{type:'delta', text:'partial'}]],
  ['empty completion', [{type:'done', content:'', truncated:false}]],
  ['mismatched completion', [{type:'delta', text:'partial'}, {type:'done', content:'different', truncated:false}]],
  ['error then done', [{type:'error', message:'failed'}, {type:'done', content:'partial', truncated:false}]],
  ['duplicate completion', [{type:'done', content:'partial', truncated:false}, {type:'done', content:'partial', truncated:false}]],
  ['post-completion delta', [{type:'done', content:'partial', truncated:false}, {type:'delta', text:'late'}]],
]) {
  test(`Reflection rejects ${name} without successful callback`, async t => {
    t.mock.method(globalThis, 'fetch', async () => new Response(encode(fixture)));
    let done = 0;
    await assert.rejects(reflectStream('synthetic source', 'title', {onDone:()=>done++}), /反思未完整结束/);
    assert.equal(done, 0);
  });
}

test('Reflection rejects late completion after abort', async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, 'fetch', async () => { controller.abort(); return new Response(encode([{type:'done', content:'audit', truncated:false}])); });
  let done=0;
  await assert.rejects(reflectStream('source', 'title', {onDone:()=>done++}, controller.signal), {name:'AbortError'});
  assert.equal(done,0);
});
