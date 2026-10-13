import assert from "node:assert/strict";

// Assert the real browser response, not a substitute fixture or network-idle heuristic.
export function assertHr1InboxAuthority(payload, expectedItems) {
  const snapshot = payload?.data ?? payload;
  assert.equal(snapshot?.canonical, true, "HR1 browser inbox must be canonical");
  assert.ok(Array.isArray(snapshot?.campaign_items), "HR1 browser inbox must contain campaigns");
  for (const expected of expectedItems) {
    const actual = snapshot.campaign_items.find(item => item.campaign_id === expected.campaign_id);
    assert.ok(actual, `HR1 browser inbox is missing seeded campaign ${expected.campaign_id}`);
    for (const key of ["hard_risk_state", "hard_risk_evaluation", "hard_risk_reason_codes", "hard_risk_authority_refs"]) {
      assert.deepEqual(actual[key], expected[key], `HR1 browser authority changed: ${expected.campaign_id} ${key}`);
    }
  }
}

// The research calendar is explicitly independent in production. Its pending reads
// do not define readiness of the inbox worklist or its authoritative risk panels.
export function hr1CommittedInboxState(snapshot) {
  if (!snapshot) {
    snapshot = {
      pathname: location.pathname,
      title: document.querySelector("main h1")?.textContent?.trim(),
      alerts: [...document.querySelectorAll('main [role="alert"]')]
        .filter(element => !element.closest('[data-testid="decision-inbox-research-calendar"]'))
        .map(element => element.textContent?.trim()).filter(Boolean),
      overlay: Boolean(document.querySelector("vite-error-overlay")),
      worklist: Boolean(document.querySelector('[data-testid="decision-inbox-worklist"]')),
      tabs: document.querySelectorAll('[data-testid^="decision-inbox-tab-"]').length,
    };
  }
  if (snapshot.pathname !== "/decision-inbox") return { error: `Unexpected HR1 route: ${snapshot.pathname}` };
  if (snapshot.overlay) return { error: "Framework error overlay is visible" };
  if (snapshot.alerts.length) return { error: snapshot.alerts.join("; ") };
  return snapshot.title === "决策待办" && snapshot.worklist && snapshot.tabs > 0 ? { ready: true } : null;
}

export async function waitForHr1Inbox(page, navigate, expectedItems) {
  // CI's real inbox reads were observed around 40s. Bound that real-response wait
  // separately; do not make success depend on unrelated requests becoming idle.
  const [response] = await Promise.all([
    page.waitForResponse(response => response.request().method() === "GET" &&
      new URL(response.url()).pathname === "/api/decision-inbox", { timeout: 90000 }),
    navigate(),
  ]);
  assert.equal(response.status(), 200, "HR1 browser decision-inbox request failed");
  assertHr1InboxAuthority(await response.json(), expectedItems);
  const handle = await page.waitForFunction(hr1CommittedInboxState);
  try {
    const state = await handle.jsonValue();
    assert.equal(state?.error, undefined, `HR1 inbox UI error: ${state?.error}`);
    assert.equal(state?.ready, true, "HR1 inbox worklist did not commit");
  } finally { await handle.dispose(); }
}

// Track proxy completion, not only browser transport completion: a canceled
// calendar fetch can leave real backend work running after requestfailed fires.
export function createHr1BackendDrain() {
  let sequence = 0;
  const pending = new Map(), failures = [], observers = new Set();
  const notify = () => { for (const observer of observers) observer(); };
  return {
    track(label, work) {
      const id = ++sequence;
      pending.set(id, label);
      const promise = Promise.resolve().then(work);
      promise.then(() => { pending.delete(id); notify(); }, error => {
        failures.push(`${label}: ${error.message}`); pending.delete(id); notify();
      });
      return promise;
    },
    settle(renderBarrier, timeoutMs = 90000) {
      return new Promise((resolve, reject) => {
        let done = false, checking = false;
        const finish = error => {
          if (done) return;
          done = true; clearTimeout(timer); observers.delete(check);
          if (error) reject(error); else resolve();
        };
        const check = async () => {
          if (done || checking || pending.size) return;
          checking = true;
          const before = sequence;
          try {
            // Let delivery/json parsing and React effects issue any dependent
            // requests, then recheck the tracked generation. This is not a sleep.
            await renderBarrier();
            checking = false;
            if (done) return;
            if (pending.size === 0 && sequence === before) {
              finish(failures.length ? new Error(`HR1 backend proxy failed: ${failures.join("; ")}`) : null);
            } else if (pending.size === 0) queueMicrotask(check);
          } catch (error) { checking = false; finish(error); }
        };
        const timer = setTimeout(() => finish(new Error(`HR1 backend reads did not settle: ${[...pending.values()].join("; ")}`)), timeoutMs);
        observers.add(check);
        void check();
      });
    },
  };
}
