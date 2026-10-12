import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {parseExtendedResearch,validResearchDate} from '../src/lib/extendedPublicResearch.ts';
const golden=JSON.parse(readFileSync(new URL('./fixtures/extended-public-research.golden.json',import.meta.url),'utf8'));
const selection=(key:string)=>({kind:key==='market'?'market' as const:'company' as const,asOf:'2026-09-30',market:key,symbol:key==='US'?'AAPL':key==='HK'?'00700':'600000'});
for(const key of Object.keys(golden)) test(`registered API strict golden ${key}`,()=>assert.deepEqual(parseExtendedResearch(golden[key],selection(key)),golden[key]));
const cases:[string,string,(x:any)=>void][]=[
 ['PIT mutation','US',x=>x.point_in_time_claim='HISTORICAL'],
 ['capture future','US',x=>x.blocks[0].captured_at='2999-01-01T00:00:00.000000Z'],
 ['source future','US',x=>x.blocks[0].rows[0].quote.source_time='2999-01-01T00:00:00.000000Z'],
 ['quote wrong currency','HK',x=>x.blocks[0].rows[0].quote.currency='USD'],
 ['benchmark wrong identity','US',x=>x.blocks[0].rows[0].benchmark.symbol='QQQ'],
 ['null rendered row','US',x=>x.blocks[0].rows=[null]],
 ['object rendered label','market',x=>x.blocks[0].rows[0].name={}],
 ['unexpected rendered window','market',x=>x.blocks[0].rows[0].windows.bad=null],
 ['missing window','market',x=>delete x.blocks[0].rows[0].windows['5']],
 ['duplicate source','market',x=>x.blocks.push(x.blocks[0])],
 ['hidden missing source','US',x=>x.blocks.pop()],
 ['mixed fixture classes','US',x=>x.blocks[0].fixture=false],
 ['unknown schema','US',x=>x.blocks[0].normalizer_version='other'],
 ['financial certified scale','US',x=>x.blocks[1].rows[0].amount_unit='currency units'],
 ['financial invented conversion','US',x=>x.blocks[1].rows[0].amount_scale_to_currency_units=1000],
 ['late notice','US',x=>x.blocks[1].rows[0].notice_date='2026-10-01'],
 ['false quarter duration','US',x=>x.blocks[1].rows[0].period_kind='quarter'],
 ['consensus wrong unit','US',x=>x.blocks[2].rows[0].eps_unit='price'],
 ['consensus fractional analysts','US',x=>x.blocks[2].rows[0].analyst_count=1.5],
 ['consensus reversed bounds','US',x=>x.blocks[2].rows[0].eps_low=100],
 ['bond price claim','market',x=>x.blocks.at(-1).rows[0].price=100],
 ['YTD invented base','market',x=>x.blocks[0].rows[0].metrics.ytd_basis_date='2026-01-01'],
 ['turnover false sum','market',x=>x.turnover.rows[0].total=0],
 ['turnover false average','market',x=>x.turnover.ma60=0],
 ['counter object','US',x=>x.blocks[1].counters.unclassified={}],
 ['nonfinite','US',x=>x.blocks[0].rows[0].quote.price=Infinity],
 ['CN quote wrong key','A',x=>x.blocks[0].rows[0].quote.key='sz600000'],
 ['unknown revision','US',x=>x.blocks[1].source_revision='certified'],
];
for(const [name,key,mutate] of cases)test(`reject ${name}`,()=>{const value=structuredClone(golden[key]);mutate(value);assert.throws(()=>parseExtendedResearch(value,selection(key)));});
test('missing archive coverage remains useful',()=>{const x=structuredClone(golden.US);x.missing_sources=x.blocks.map((b:any)=>({source_id:b.source_id,subject:b.subject}));x.blocks=[];x.fixture=false;x.status='missing';assert.equal(parseExtendedResearch(x,selection('US')).status,'missing');});
test('strict dates',()=>{for(const d of ['0000-01-01','2026-02-30','2026-1-01','2026-01-01x'])assert.equal(validResearchDate(d),false);});
test('bounded nested hostile tree',()=>{const x=structuredClone(golden.US);x.hostile=Array.from({length:1000},()=>Array(1000).fill('x'));assert.throws(()=>parseExtendedResearch(x,selection('US')));});
test('production pages bind source context and require deliberate archive read',()=>{const review=readFileSync(new URL('../src/pages/DailyReview.tsx',import.meta.url),'utf8'), stock=readFileSync(new URL('../src/pages/StockData.tsx',import.meta.url),'utf8');assert.match(review,/ExtendedResearchCard kind="market"/);assert.match(stock,/CompanyArchiveCard/);const card=readFileSync(new URL('../src/components/research/ExtendedResearchCard.tsx',import.meta.url),'utf8');assert.match(card,/serial.current === id/);assert.match(card,/state.key === key/);assert.match(card,/if \(!open/);assert.match(card,/缩放单位未核实/);});
for(const bad of [{}, {rows:[null]}])test('company cannot carry malformed turnover '+JSON.stringify(bad),()=>{const x=structuredClone(golden.US);x.turnover=bad;assert.throws(()=>parseExtendedResearch(x,selection('US')));});
test('provenance arrays and wrong provider URL rejected',()=>{for(const field of ['source_url','hash']){const x=structuredClone(golden.US);if(field==='source_url')x.blocks[0].source_url='https://wrong.example/';else x.blocks[0].evidence.raw_payload_hash=[x.blocks[0].evidence.raw_payload_hash];assert.throws(()=>parseExtendedResearch(x,selection('US')));}});
test('Yahoo reporting currencies mirror producer enum',()=>{for(const currency of ['EUR','GBP','JPY','CAD','AUD','CHF','TWD','KRW']){const x=structuredClone(golden.US);x.blocks[2].rows[0].currency=currency;assert.equal(parseExtendedResearch(x,selection('US')).blocks[2].rows[0].currency,currency);}});
test('actual persisted malformed XLS raw failure remains renderable with full missing coverage',()=>{const x=JSON.parse(readFileSync(new URL('./fixtures/extended-public-failure.golden.json',import.meta.url),'utf8'));const parsed=parseExtendedResearch(x,selection('market'));assert.equal(parsed.blocks[0].status,'unavailable');assert.deepEqual(parsed.blocks[0].rows,[]);assert.equal(parsed.turnover?.ma60,null);});
test('returned financial issuer and fiscal period code cannot be relabeled',()=>{for(const patch of [{returned_secucode:'OTHER.O'},{period_code:'001'},{period_days:1}]){const x=structuredClone(golden.US);Object.assign(x.blocks[1].rows[0],patch);assert.throws(()=>parseExtendedResearch(x,selection('US')));}});
