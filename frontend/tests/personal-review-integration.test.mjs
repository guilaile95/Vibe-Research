import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
const read = (name) => readFileSync(new URL(name, import.meta.url), "utf8");
const bundle = await build({ entryPoints: [fileURLToPath(new URL("../src/components/personal-review/PersonalReviewPanel.tsx", import.meta.url))], bundle: true, write: false, format: "esm", platform: "node", external: ["react", "react-dom", "react-router-dom"], tsconfig: fileURLToPath(new URL("../tsconfig.json", import.meta.url)) });
// Import via a local file URL so external React remains a single shared instance.
import { writeFileSync, unlinkSync } from "node:fs";
const path = new URL("./.personal-review-render-temporary.mjs", import.meta.url);
writeFileSync(path, bundle.outputFiles[0].text);
let Panel;
try { Panel = (await import(path.href)).PersonalReviewPanel; } finally { unlinkSync(path); }

test("actual panel renders local privacy and loading boundary without model calls", () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => { throw new Error("network forbidden"); };
  try {
    const html = renderToStaticMarkup(createElement(Panel));
    assert.match(html, /个人复查/); assert.match(html, /默认不发给模型/); assert.match(html, /正在读取本地复查/);
    assert.doesNotMatch(html, /net_pnl|undefined|NaN/);
  } finally { globalThis.fetch = original; }
});
test("ledger entry and detail use one review component and authenticated API", () => {
  const trades = read("../src/pages/Trades.tsx");
  assert.match(trades, /<PersonalReviewPanel refreshKey=/);
  assert.match(trades, /<PersonalReviewPanel key=\{detailTrade.trade_id\} trade=\{detailTrade\}/);
  const source = read("../src/components/personal-review/PersonalReviewPanel.tsx");
  assert.match(source, /import \{ request \} from "@\/lib\/api"/);
  assert.match(source, /controller.abort\(\)/);
  assert.match(source, /generation.current === token/);
  assert.doesNotMatch(source, /fetch\(|analyze|chatStream|registerPage|localStorage|sessionStorage/);
});

test("actual editor JSX recovers malformed GET and locks uncertain PUT without wiping draft", async () => {
  const state = { values:[], cursor:0, effects:[], queue:[], writes:0 };
  globalThis.__personalReviewTestHooks = state;
  const sourcePath=fileURLToPath(new URL("../src/components/personal-review/PersonalReviewPanel.tsx",import.meta.url));
  const compiled=await build({ entryPoints:[sourcePath],bundle:true,write:false,format:"esm",platform:"node",external:["react","react-dom","react-router-dom"],tsconfig:fileURLToPath(new URL("../tsconfig.json",import.meta.url)),plugins:[{
    name:"controlled-production-editor-hooks",
    setup(api){
      api.onLoad({filter:/PersonalReviewPanel\.tsx$/},async(args)=>({contents:readFileSync(args.path,"utf8").replace('from "react"','from "review-test-hooks"'),loader:"tsx",resolveDir:fileURLToPath(new URL("../src/components/personal-review",import.meta.url))}));
      api.onResolve({filter:/^review-test-hooks$/},()=>({path:"hooks",namespace:"review-test"}));
      api.onResolve({filter:/^@\/lib\/api$/},()=>({path:"api",namespace:"review-test"}));
      api.onLoad({filter:/.*/,namespace:"review-test"},(args)=>({contents:args.path==="hooks"?`const s=globalThis.__personalReviewTestHooks; export function useState(init){const i=s.cursor++; if(!(i in s.values))s.values[i]=typeof init==='function'?init():init; return [s.values[i],v=>{s.values[i]=typeof v==='function'?v(s.values[i]):v;}];} export const useRef=v=>useState(()=>({current:v}))[0]; export const useId=()=>"synthetic-review-form"; export const useEffect=f=>{s.effects.push(f);};`:`export async function request(path,method){const s=globalThis.__personalReviewTestHooks;if(method==='PUT')s.writes++;if(!s.queue.length)throw new Error('unplanned request');return s.queue.shift();}`,loader:"js"}));
    }
  }]});
  const temporary=new URL("./.personal-review-controlled-temporary.mjs",import.meta.url);
  writeFileSync(temporary,compiled.outputFiles[0].text);
  let Editor;
  try{Editor=(await import(`${temporary.href}?controlled`)).PersonalReviewPanel;}finally{unlinkSync(temporary);}
  const zero={requested:10,closed_count:0,insufficient_samples:true,money_scored:0,wins:0,losses:0,flat:0,win_rate_excluding_flat:null,net_pnl:null,self_assessed_count:0,self_reported_deviations:0,self_reported_violations:0};
  const valid={schema_version:"personal-review.v1",privacy:"LOCAL_ONLY_EXCLUDED_FROM_MODEL_CONTEXT",as_of:"2026-07-28T00:00:00Z",data_time:null,trade_count:1,closed_episodes:[],diagnostics:[],windows:[10,20,50].map(n=>({...zero,requested:n})),patterns:[],risk:{open_episodes:[],equity_reference:null,equity_effective_at:null,equity_confirmation:"UNKNOWN",boundary:"SELF_REPORTED"},assessment_history:{},limitations:[]};
  const trade={trade_id:"a".repeat(32),executed_at:"2026-07-21T02:00:00Z",execution_status:"full"};
  let props={trade};
  const tree=()=>{state.cursor=0;state.effects=[];return Editor(props);};
  const nodes=(element)=>!element||typeof element!=="object"?[]:[element,...[element.props?.children].flat(Infinity).flatMap(nodes)];
  const drain=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  try{
    state.queue.push({...valid,windows:null});tree();state.effects[0]();await drain();
    let element=tree();assert.match(renderToStaticMarkup(element),/响应无法核验/);
    const retry=nodes(element).find(n=>n.type==="button"&&n.props.children==="重新加载");retry.props.onClick();
    state.queue.push(valid);tree();state.effects[0]();await drain();
    element=tree();const note=nodes(element).find(n=>n.type==="textarea"&&n.props.maxLength===2000);note.props.onChange({target:{value:"Synthetic private draft retained"}});
    element=tree();state.queue.push({});nodes(element).find(n=>n.type==="form").props.onSubmit({preventDefault(){}});await drain();
    element=tree();const html=renderToStaticMarkup(element);assert.match(html,/写入结果待核验/);assert.match(html,/Synthetic private draft retained/);
    const noteLabel=html.match(/<label[^>]*>复查笔记([\s\S]*?)<\/label>/)?.[0];
    assert.ok(noteLabel);assert.equal(noteLabel.replace(/<[^>]*>/g, ""), "复查笔记", "exact label text must not absorb controlled textarea draft");
    const associations=[...html.matchAll(/<label for="([^"]+)"[^>]*>([^<]*)<\/label>/g)];
    assert.equal(associations.length,8);assert.equal(new Set(associations.map(m=>m[1])).size,8);
    for(const [,id]of associations)assert.ok(html.includes(`id="${id}"`));
    assert.equal(nodes(element).find(n=>n.type==="button"&&n.props.children==="保存自评修订").props.disabled,true);
    nodes(element).find(n=>n.type==="form").props.onSubmit({preventDefault(){}});await drain();assert.equal(state.writes,1);
    const writesBeforeReload=state.writes;
    nodes(element).find(n=>n.type==="button"&&n.props.children==="重新加载").props.onClick();
    // Before the passive read effect commits, the old history/form still exists and remains locked.
    element=tree();assert.equal(nodes(element).find(n=>n.type==="button"&&n.props.children==="保存自评修订").props.disabled,true);
    let resolveRead;state.queue.push(new Promise(resolve=>{resolveRead=resolve;}));state.effects[0]();
    element=tree();assert.match(renderToStaticMarkup(element),/正在读取本地复查/);assert.equal(nodes(element).some(n=>n.type==="form"),false);
    const content={environment:"",closing_board_rank:null,stop_price:null,judgment:"unknown",execution:"unknown",pattern_id:null,pattern_revision:null,violations:[],note:"Synthetic private draft retained"};
    resolveRead({...valid,assessment_history:{[props.trade.trade_id]:[{revision:1,content,saved_at:"2026-07-28T00:00:00Z",stop_recorded_at:null,classification:"RETROSPECTIVE_SELF_ASSESSMENT"}]}});await drain();
    element=tree();assert.equal(nodes(element).find(n=>n.type==="button"&&n.props.children==="保存自评修订").props.disabled,false);
    assert.match(renderToStaticMarkup(element),/Synthetic private draft retained/);assert.equal(state.writes,writesBeforeReload);
    props={};state.values=[];
    const episode={episode_id:"b".repeat(32),code:"600000",name:"Synthetic",trade_ids:["a".repeat(32)],opened_at:"2026-07-21T02:00:00Z",closed_at:"2026-07-24T02:00:00Z",holding_calendar_days:3,state:"CLOSED",gross_pnl:0,net_pnl:0,fees:0,fee_coverage:"LEDGER_RECORDED",assessment:null,formal_attributions:[]};
    state.queue.push({...valid,closed_episodes:[episode]});tree();state.effects[0]();await drain();
    element=tree();state.queue.push({state:"RAW_INTERIOR_PRICE_RANGE",mfe_pct:null,mae_pct:null,raw_interior_high:null,raw_interior_low:null,boundary:"EXCLUDED",reason:"UNKNOWN",source:null,adjusted_bound:{state:"BASIS_ARCHIVE_INVALID",limitations:{},source:{provider_revision:{}}}});
    nodes(element).find(n=>n.type==="button"&&n.props.children==="读取本地持有期价格证据").props.onClick();await drain();
    element=tree();assert.match(renderToStaticMarkup(element),/响应无法核验/);
  }finally{delete globalThis.__personalReviewTestHooks;}
});
