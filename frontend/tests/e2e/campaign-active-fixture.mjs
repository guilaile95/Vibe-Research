import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const ACTIVE_SEED = `
import os, sys, uuid
from datetime import datetime, timezone
sys.path.insert(0, os.getcwd())
import campaign_store
campaign, _transition = campaign_store.transition_campaign(
    campaign_id=os.environ["E2E_CAMPAIGN_ID"],
    expected_status="PRE-ENTRY",
    to_status="ACTIVE",
    transition_id=f"campaign_transition_{uuid.uuid4().hex}",
    transitioned_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
)
assert campaign.get("status") == "ACTIVE", campaign
print("ACTIVE_SEED_OK")
`;

/** Seed an already-established ACTIVE history for downstream E2E fixtures.
 * Production PRE-ENTRY activation is intentionally available only through the
 * attributed executed-BUY command; tests for that command use the real API.
 */
export function seedActiveCampaign(backendDir, env, campaignId) {
  const python = env.PYTHON || (process.platform === "win32" ? "py" : "python3");
  const args = [
    ...(env.PYTHON || process.platform !== "win32" ? [] : ["-3"]),
    "-c",
    ACTIVE_SEED,
  ];
  const result = spawnSync(python, args, {
    cwd: backendDir,
    env: { ...env, E2E_CAMPAIGN_ID: campaignId },
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout, /ACTIVE_SEED_OK/);
}
