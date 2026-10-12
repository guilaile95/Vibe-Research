import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/pages/DecisionProposalReview.tsx',import.meta.url),'utf8');
const parsed=ts.createSourceFile('DecisionProposalReview.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const component=parsed.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='DecisionProposalReview');
const stateNames=[];
for(const statement of component.body.statements)if(ts.isVariableStatement(statement))for(const declaration of statement.declarationList.declarations){if(ts.isArrayBindingPattern(declaration.name)&&ts.isCallExpression(declaration.initializer)&&declaration.initializer.expression.getText(parsed)==='useState')stateNames.push(declaration.name.elements[0].name.text);}
const marker=()=>null;
function render(patch={},route='campaign-one',historical=null){
 let cursor=0;const values={campaign:{campaign_id:route,security_code:'600519',strategy:'SWING',status:'ACTIVE'},binding:{thesis_id:'thesis-one'},currentThesis:{thesis_id:'thesis-one',original:{revision:3}},contextState:'ready',...patch};const writes={};
 const react={useState(init){const name=stateNames[cursor++];assert.ok(name);return[name in values?values[name]:typeof init==='function'?init():init,value=>{writes[name]=value;}];},useRef:init=>({current:init}),useEffect(){},useMemo:fn=>fn()};
 const modules={react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'},'react-router-dom':{useSearchParams:()=>[{get:name=>name==='decision_id'?historical:null}],useParams:()=>({campaignId:route}),useNavigate:()=>()=>{},Link:()=>null},'@/components/campaign/CampaignAIDraftButton':{CampaignAIDraftButton:marker},'@/lib/api':{api:new Proxy({}, {get:()=>()=>assert.fail('parent must not call an API during render')}),DECISION_CHALLENGE_DIMENSIONS:[]},'@/lib/decisionProposalForm':{VIEW_STANCE_OPTIONS:['WAIT'],VIEW_STANCE_LABELS:{WAIT:'Wait'}},'@/lib/reviewBoundaryInput':{parseReviewBoundary:()=>({status:'INVALID'}),browserTimeZoneName:()=> 'UTC'},'@/lib/candidateCampaign':{buildCandidateValuationCase:()=>null,buildCandidateTradeTerms:()=>null,presentPortfolioCapitalContext:()=>({}),candidateWorkspaceHref:()=>"/candidates/600519",CANDIDATE_CONFIDENCE_LEVELS:[]},'@/lib/researchBrief':{buildResearchBrief:()=>({})},'@/lib/decisionInbox':{isTerminalCampaignStatus:status=>status==='CLOSED',CAMPAIGN_STATUS_LABELS:{CLOSED:'Closed'}},'@/lib/decisionChallengeForm':{challengeDimensionsReady:()=>false}};
 const exports={};const code=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(code,{exports,require:name=>modules[name]||new Proxy({}, {get:()=>()=>null}),URLSearchParams,Date,Error});
 return {tree:exports.DecisionProposalReview(),writes,values};
}
function nodes(t){return t==null||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];}
function consent(tree){return nodes(tree).filter(n=>n.type===marker);}
test('production proposal page wires one consent component to exact current campaign/thesis/binding',()=>{const r=render();const [button]=consent(r.tree);assert.equal(consent(r.tree).length,1);assert.equal(button.props.campaignId,'campaign-one');assert.equal(button.props.contextIdentity,JSON.stringify([r.values.currentThesis,r.values.binding]));assert.equal(button.props.disabled,false);button.props.onBusyChange(true);button.props.onError('synthetic');assert.equal(r.writes.aiBusy,true);assert.equal(r.writes.error,'synthetic');const changed=render({currentThesis:{thesis_id:'thesis-two',original:{revision:4}}},'campaign-two');const next=consent(changed.tree)[0];assert.equal(next.props.campaignId,'campaign-two');assert.notEqual(next.props.contextIdentity,button.props.contextIdentity);});
test('loading/busy parent disables consent and history/terminal views cannot generate',()=>{for(const patch of [{contextState:'loading'},{contextState:'unavailable'},{busy:'preview'}])assert.equal(consent(render(patch).tree)[0].props.disabled,true);assert.equal(consent(render({},'campaign-one','historical-one').tree).length,0);assert.equal(consent(render({campaign:{status:'CLOSED',security_code:'600519'}}).tree).length,0);});
test('parent cannot bypass consent with direct model/API calls',()=>{let direct=[];function visit(node){if(ts.isCallExpression(node)&&/generateCampaignAIDraft|loadLlm|chatStream|streamMessages/.test(node.expression.getText(parsed)))direct.push(node.expression.getText(parsed));ts.forEachChild(node,visit);}visit(parsed);assert.deepEqual(direct,[]);});
