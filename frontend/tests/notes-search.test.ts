import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {filterResearchNotes,type Note} from "../src/lib/notes.ts";
import {researchAnalyticsNote} from "../src/lib/researchAnalyticsNote.ts";
const rows:Note[]=[{id:"r",kind:"公司研究",title:"ABC",content:"毛利和cash",ts:1,research:{securityCode:"600001",question:"增长"}},{id:"d",kind:"多空辩论",title:"辩论",content:"毛利风险",ts:2},{id:"b",kind:"回测研究",title:"模拟",content:"限制价格及费用",ts:3}];
test("cross-type search is local plain text and intersects existing security metadata",()=>{
 const before=JSON.stringify(rows);
 assert.deepEqual(filterResearchNotes(rows,"","毛利").notes.map(x=>x.id),["r","d"]);
 assert.deepEqual(filterResearchNotes(rows,"多空辩论","毛利").notes.map(x=>x.id),["d"]);
 assert.deepEqual(filterResearchNotes(rows,"","CASH","600001").notes.map(x=>x.id),["r"]);
 assert.equal(filterResearchNotes(rows,"",".*").notes.length,0);
 assert.equal(filterResearchNotes(rows,"","<script>").notes.length,0);
 assert.equal(filterResearchNotes(rows,"回测研究","").notes[0].id,"b");
 assert.equal(JSON.stringify(rows),before);
});
test("excessive search is explicit and never returns a misleading partial match",()=>{
 assert.ok(filterResearchNotes(rows,"","a".repeat(121)).error);
 const huge=[...rows,{...rows[0],id:"huge",content:"x".repeat(4_000_001)}];
 const result=filterResearchNotes(huge,"","毛利");assert.deepEqual(result.notes,[]);assert.ok(result.error);
 assert.equal(filterResearchNotes(huge,"多空辩论","毛利").notes.length,1);
});
test("research result note binds validated response and excludes original input",()=>{
 const f=JSON.parse(readFileSync(new URL('./e2e/research-analytics.fixture.json',import.meta.url),'utf8'));
 const note=researchAnalyticsNote(f.simulation.result,"simulation",true);
 assert.equal(note.kind,"回测研究");assert.ok(note.content.includes(f.simulation.result.input_fingerprint));assert.match(note.content,/合成示例/);assert.match(note.content,/未保存原始输入/);
 assert.throws(()=>researchAnalyticsNote(f.performance.result,"simulation",false));
 assert.throws(()=>researchAnalyticsNote({...f.simulation.result,private_secret:"canary"},"simulation",false));
});
