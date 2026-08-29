// Browser E2E processes use isolated temporary databases and must remain deterministic.
// The production app still performs its non-blocking startup refresh unless an explicit
// environment override is present. Every npm test:e2e:* script preloads this module before
// its harness starts FastAPI, so read-only browser assertions cannot race an unrelated RSS write.
if (process.env.VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH === undefined) {
  process.env.VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH = "1";
}
