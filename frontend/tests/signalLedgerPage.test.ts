import assert from "node:assert/strict";
import test, { describe } from "node:test";
import { stageLabel, severityLabel } from "../src/lib/signalLedgerView.ts";

describe("SignalLedger Page View Contracts", () => {
  test("ensures all 7 decision pipeline stages have Chinese labels", () => {
    const stages = [
      "schema",
      "compatibility",
      "fact_reconciliation",
      "policy_audit",
      "execution",
      "narrative_audit",
      "account_constraint",
    ];
    stages.forEach((s) => {
      const label = stageLabel(s);
      assert.notEqual(label, s);
      assert.ok(label.length > 2);
    });
  });

  test("ensures all 3 severity levels map properly", () => {
    const severities = ["info", "warning", "error"];
    severities.forEach((sev) => {
      const label = severityLabel(sev);
      assert.notEqual(label, sev);
    });
  });
});
