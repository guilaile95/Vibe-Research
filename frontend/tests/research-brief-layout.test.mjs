import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {build} from 'esbuild';

const bundle=await build({entryPoints:[fileURLToPath(new URL('../src/components/campaign/ResearchBrief.tsx',import.meta.url))],bundle:true,write:false,format:'esm',platform:'node',tsconfig:fileURLToPath(new URL('../tsconfig.json',import.meta.url))});
const {ResearchBrief}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const evidence=(stance)=>({evidenceId:stance,stance,claim:`${stance} original claim`,classification:'fact',confidence:'medium',sourceTitle:`${stance} source`,sourceUrl:`https://example.test/${stance}`,sourceDate:'2026-10-01'});
const model=()=>({campaignId:'synthetic-campaign',securityCode:'600519',strategyCode:'SWING',strategyLabel:'波段',horizonText:'10–30个交易日',thesisVersionText:'v1',horizonSource:'CURRENT_THESIS',contextState:'ready',
 effectiveState:{state:'WEAKENED',label:'削弱',kind:'caution',terminal:false,note:'当前确认状态来自已确认变更'},
 confirmed:{status:'CONFIRMED',title:'HISTORICAL ORIGINAL',summary:'历史冻结原貌',claims:['historical claim'],note:'冻结原文不是最新结论'},
 confirmedUpdates:[{deltaId:'delta',sequence:1,stateLabel:'削弱',stateKind:'caution',reason:'CONFIRMED UPDATE',confirmedAt:'2026-10-02',baseRevision:1,evidence:[]}],updatesNote:'仅已确认变更',
 changes:{status:'CHANGED',note:'检查以来变化',items:[{kind:'SOURCE_CONFLICT',label:'来源冲突',recordKey:'conflict',claim:'conflicting claim',source:'A / B',classificationLabel:null,detail:null}],baselineText:'synthetic baseline',fetchedAt:'2026-10-02',observationCount:1},
 evidence:{supporting:[evidence('support')],opposing:[evidence('oppose')],opposingRecorded:true,note:'已确认关联证据'},
 invalidation:{conditions:['INVALIDATION CONDITION'],note:'不是这些条件已经触发'},freshness:{frozenAt:'2026-09-01',gaps:['DATA GAP']},verification:{catalysts:['pending catalyst'],catalystsNote:'尚待核验',calendarState:null,calendarLine:''}});
const render=(value)=>renderToStaticMarkup(createElement(ResearchBrief,{model:value,bindingThesisId:'bound',boundThesisId:'bound'}));

test('existing boundaries precede frozen history without duplicating or changing evidence',()=>{
 const html=render(model());
 for(const id of ['subject','invalidation','freshness','changes','updates','evidence'])assert.ok(html.indexOf(`data-testid="research-brief-${id}"`)<html.indexOf('data-testid="research-brief-view"'));
 for(const text of ['INVALIDATION CONDITION','DATA GAP','HISTORICAL ORIGINAL','CONFIRMED UPDATE','不是这些条件已经触发'])assert.equal(html.split(text).length-1,1);
 for(const stance of ['support','oppose'])assert.match(html,new RegExp(`href="https://example.test/${stance}"`));
 assert.doesNotMatch(html,/<(?:input|textarea|select|button)\b/);
 assert.match(html,/lg:grid-cols-2/);
 assert.match(html,/grid-cols-2 gap-2 text-xs lg:grid-cols-5/);
 assert.match(html,/col-span-2 lg:col-span-1/);
 assert.match(html,/scroll-mt-16/);
});

test('disproven remains a terminal alert and historical original stays explicitly historical',()=>{
 const value=model();value.effectiveState={state:'DISPROVEN',label:'已证伪',kind:'terminal',terminal:true,note:'已证伪'};
 const html=render(value);assert.match(html,/role="alert"/);assert.match(html,/不能作为当前研究结论使用/);assert.match(html,/最初冻结的观点是什么？（历史原貌）/);
});

test('unavailable context preserves unknown and fallback disclosures rather than inventing certainty',()=>{
 const value=model();value.contextState='unavailable';value.horizonSource='MANUAL_FALLBACK';value.confirmed={status:'UNAVAILABLE',title:null,summary:null,claims:[],note:'上下文不可用，不展示未确认草稿'};value.invalidation={conditions:[],note:'条件不可用'};value.freshness={frozenAt:null,gaps:['当前确认材料无法读取']};
 const html=render(value);assert.match(html,/data-decision-context="unavailable"/);assert.match(html,/上下文不可用/);assert.match(html,/冻结时间：未知/);assert.match(html,/摘要不会猜测/);assert.doesNotMatch(html,/HISTORICAL ORIGINAL/);
});
