import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildEvidenceNewHref, mapEvidenceNewQuery } from "../src/lib/candidateCampaign.ts";
import { sameStockCandidateReturn } from "../src/lib/researchResume.ts";

const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
// Execute the actual two call-site returnTo expressions, not a copied desired URL.
// Browser acceptance separately clicks these rendered links and all return actions.
const captureReturns = [...source.matchAll(/to=\{buildEvidenceNewHref\(\{([\s\S]*?)\}\)\}/g)]
  .map(([_, body]) => ({ type: body.match(/evidenceType: "([^"]+)"/)![1], expression: body.match(/returnTo: ([^\n]+),/)![1] }));
const candidate = "/candidates/600519?return_to=%2Fwatchlist&question=Q2&round=R2#candidate-research-check";
function capture(type: string, stockReturnPath: string, activeCode = "600519") {
  const expression = captureReturns.find(row => row.type === type)!.expression;
  const returnTo = new Function("stockReturnPath", "activeCode", `return (${expression});`)(stockReturnPath, activeCode);
  const href = buildEvidenceNewHref({ subjectType: "stock", subjectId: activeCode, returnTo, evidenceType: type as "news" | "announcement", sourceTitle: "合成资料" });
  return mapEvidenceNewQuery(new URL(href, "http://localhost").searchParams);
}
for (const type of ["announcement", "news"]) {
  test(`${type}: actual capture call site preserves query/hash and Q2/R2 through repeated returns`, () => {
    assert.equal(captureReturns.length, 2);
    const stock = `/stock-data?${new URLSearchParams({ code: "600519", view: "synthetic", return_to: candidate })}#source-anchor`;
    let current = candidate;
    for (let pass = 0; pass < 5; pass++) {
      const mapped = capture(type, stock);
      assert.equal(mapped.return_to, stock);
      const returned = new URL(mapped.return_to, "http://localhost");
      current = sameStockCandidateReturn(returned.searchParams.get("return_to")!, "600519")!;
      assert.equal(current, candidate);
    }
  });
  test(`${type}: no upstream, changed stock and hostile upstream fail closed without false old-stock return`, () => {
    assert.equal(capture(type, "/stock-data?code=600519").return_to, "/stock-data?code=600519");
    for (const upstream of [candidate, "//evil.example", "https://evil.example", "/%255cevil.example"]) {
      const stock = `/stock-data?${new URLSearchParams({ code: "000001", return_to: upstream })}#source-anchor`;
      const mapped = capture(type, stock, "000001");
      assert.equal(mapped.subject_id, "000001");
      assert.equal(mapped.return_to, stock);
      assert.equal(sameStockCandidateReturn(new URL(mapped.return_to, "http://localhost").searchParams.get("return_to")!, "000001"), null);
    }
  });
}
