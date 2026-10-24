import { readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// Explicit phases shared by the API process, seed subprocesses and browser.
// Never use the runner's date or a far-future execution fact to avoid expiry.
export const CREATION_TIME = "2026-08-28T08:00:00.000000Z";
export const OBSERVATION_TIME = "2026-09-02T08:00:00.000000Z";
export function createTemporalClock(dataDir) {
  const file = join(dataDir, "e2e-clock.txt");
  const set = (instant) => {
    if (!Number.isFinite(Date.parse(instant))) throw new Error("invalid E2E clock");
    // Atomic replacement prevents in-flight API reads seeing a partial phase.
    writeFileSync(`${file}.next`, instant, "utf8");
    renameSync(`${file}.next`, file);
  };
  set(CREATION_TIME);
  const advance = (seconds = 1) => {
    if (!Number.isFinite(seconds) || seconds <= 0) throw new Error("E2E clock must advance");
    const instant = new Date(Date.parse(readFileSync(file, "utf8")) + seconds * 1000).toISOString();
    set(instant);
    return instant;
  };
  return { env: { E2E_CLOCK_FILE: file }, set, advance };
}
