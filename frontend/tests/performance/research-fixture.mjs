/** Synthetic, full-size JSON records. Never reads real user data. */
export function researchFixture(count, chars) {
 const questions=[], rounds=[];
 for(let i=0;i<count;i++) {
  const securityCode=i===0?'600001':'600002';
  rounds.push({id:`r${i}`,questionId:`q${i}`,securityCode,parentRoundId:null,createdAt:2,materials:[{id:`m${i}`,version:'v1',securityCode,title:'synthetic',content:'x'.repeat(chars),sourceUrl:null,sourceKind:'manual',sourceHash:null,publishedAt:null,capturedAt:1,readRange:{pages:[],totalPages:null,truncated:false,ocr:false,description:'synthetic'},availability:'partial'}],calculation:null,judgement:'synthetic',limitations:'synthetic',nextMaterial:'next',reviewedMaterialKeys:[],ignoredMaterialKeys:[],coverage:'partial'});
  questions.push({id:`q${i}`,securityCode,question:'synthetic',origin:{kind:'manual',label:'synthetic',capturedAt:1},createdAt:1,updatedAt:2,revision:1,headRoundId:`r${i}`,status:'watching',reviewedMaterialKeys:[]});
 }
 return {questions,rounds,operations:[],legacySources:[]};
}
