/**
 * Internal return_to sanitizer + evidence detail href contract.
 *
 * Drives the real helper. Rejects open-redirect shapes.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { safeInternalReturnTo } from "../src/lib/internalReturnTo.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(__dirname, "../src");

function readSrc(rel: string) {
  return readFileSync(join(srcRoot, rel), "utf8");
}

const fallback = "/evidence";

test("safeInternalReturnTo keeps same-origin in-app paths", () => {
  assert.equal(safeInternalReturnTo("/evidence", fallback), "/evidence");
  assert.equal(safeInternalReturnTo("/evidence?subject_type=stock", fallback), "/evidence?subject_type=stock");
  assert.equal(safeInternalReturnTo("/candidates/600519", fallback), "/candidates/600519");
  assert.equal(
    safeInternalReturnTo("/thesis/abc?campaign_id=1#links", fallback),
    "/thesis/abc?campaign_id=1#links",
  );
  assert.equal(safeInternalReturnTo("/stock-data?code=600519", fallback), "/stock-data?code=600519");
  assert.equal(safeInternalReturnTo("/decision-inbox", fallback), "/decision-inbox");
});

test("safeInternalReturnTo rejects protocol-relative, javascript, and absolute URLs", () => {
  assert.equal(safeInternalReturnTo("//evil.example", fallback), fallback);
  assert.equal(safeInternalReturnTo("//evil.example/phish", fallback), fallback);
  assert.equal(safeInternalReturnTo("javascript:alert(1)", fallback), fallback);
  assert.equal(safeInternalReturnTo("https://evil.example/phish", fallback), fallback);
  assert.equal(safeInternalReturnTo("http://evil.example", fallback), fallback);
  assert.equal(safeInternalReturnTo("http://127.0.0.1/evidence", fallback), fallback);
  assert.equal(safeInternalReturnTo("\\\\evil.example", fallback), fallback);
  assert.equal(safeInternalReturnTo("/\\evil.example", fallback), fallback);
  assert.equal(safeInternalReturnTo("/foo\\bar", fallback), fallback);
  assert.equal(safeInternalReturnTo("", fallback), fallback);
  assert.equal(safeInternalReturnTo(null, fallback), fallback);
  assert.equal(safeInternalReturnTo("evidence", fallback), fallback);
  assert.equal(safeInternalReturnTo("./evidence", fallback), fallback);
});

test("pages import the shared helper instead of a local copy", () => {
  for (const rel of [
    "pages/ThesisNew.tsx",
    "pages/ThesisDetail.tsx",
    "pages/ThesisRevision.tsx",
    "pages/EvidenceNew.tsx",
    "pages/EvidenceDetail.tsx",
  ]) {
    const src = readSrc(rel);
    assert.ok(src.includes('from "@/lib/internalReturnTo"'), `${rel} must import safeInternalReturnTo`);
    assert.ok(!src.includes("function safeInternalReturnTo"), `${rel} must not keep a local copy`);
  }
});

test("CandidateWorkspace existing evidence href includes return_to", () => {
  const src = readSrc("pages/CandidateWorkspace.tsx");
  assert.ok(
    src.includes("`/evidence/${encodeURIComponent(record.id)}?${new URLSearchParams({ return_to: returnTo }).toString()}`"),
    "existing evidence links must append return_to = candidateWorkspaceHref(code)",
  );
  assert.match(src, /const returnTo = candidateWorkspaceHref\(code\)/);
});

test("ThesisDetail existing evidence href includes current return_to", () => {
  const src = readSrc("pages/ThesisDetail.tsx");
  assert.ok(
    src.includes("`/evidence/${link.evidence_id}?${new URLSearchParams({"),
    "查看证据 must target evidence detail with a query string",
  );
  assert.ok(
    src.includes("return_to: currentReturnTo"),
    "查看证据 must pass the same currentReturnTo as newEvidenceHref",
  );
  assert.match(
    src,
    /const currentReturnTo = `\$\{location\.pathname\}\$\{location\.search\}\$\{location\.hash\}`/,
  );
  assert.ok(
    src.includes("return_to: currentReturnTo"),
    "newEvidenceHref and 查看证据 must share currentReturnTo",
  );
});
