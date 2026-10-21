import assert from "node:assert/strict";
import { test } from "node:test";
import { annotationContext, annotationPlacement, registerAnnotationContext, type AnnotationContext, type ResearchAnnotation } from "../src/lib/researchAnnotations.ts";
import { normalizeKlineIndicatorOverlay } from "../src/lib/klineIndicatorOverlay.ts";
const bars = [{date:"2026-10-16",open:10,high:12,low:9,close:11,volume:20}];
const context: AnnotationContext = {code:"000001",bar_period:"day",snapshot_id:"a".repeat(64),token:"b".repeat(64),expires_at:"2026-10-20T00:00:00+00:00",points:[["2026-10-16","10","12","9","11","20"]]};
const note = {id:"note",code:"000001",bar_period:"day",snapshot_id:context.snapshot_id,date:"2026-10-16",text:"<script>unsafe</script>",price:null,link_kind:null,link_id:null,link_revision:null,created_at:"2026-10-19"} as ResearchAnnotation;
test("API array is unmodified and metadata is scoped to exact array and normalized points", () => {
  const data = bars.map(x=>({...x})), before=JSON.stringify(data);
  assert.equal(registerAnnotationContext(data, context),data);
  assert.equal(JSON.stringify(data),before);
  assert.equal(annotationContext(data,"000001",normalizeKlineIndicatorOverlay(data,null)), context);
  assert.equal(annotationContext([...data],"000001",normalizeKlineIndicatorOverlay(data,null)),null);
  assert.equal(annotationContext(data,"000002",normalizeKlineIndicatorOverlay(data,null)),null);
  data[0].volume=21;
  assert.equal(annotationContext(data,"000001",normalizeKlineIndicatorOverlay(data,null)),null);
});
test("annotations never remap missing dates, foreign subjects, changed periods or stale snapshots", () => {
  assert.equal(annotationPlacement(note,context,"000001",[note.date]),"EXACT");
  for (const changed of [{date:"2026-10-17"},{code:"000002"},{bar_period:"week"},{snapshot_id:"other"}]) {
    assert.equal(annotationPlacement({...note,...changed},context,"000001",[note.date]),"UNMAPPED");
  }
  assert.equal(annotationPlacement(note,null,"000001",[note.date]),"UNMAPPED");
  assert.equal(annotationPlacement(note,context,"000001",[]),"UNMAPPED");
});
