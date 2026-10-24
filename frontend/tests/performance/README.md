# Measured frontend performance

These measurements isolate frontend work. They do not claim target-machine speed,
real provider latency, model quality, or physical-disk/crash durability.

## Production browser comparison

Build the immutable baseline and candidate with the same dependency lock and Node
version, then run from the candidate frontend:

    node tests/performance/frontend.browser.mjs --baseline-dist /path/to/baseline/frontend/dist --candidate-dist ./dist --output ./performance-evidence

Source trees must remain alongside each dist directory. The native IndexedDB
portion serves those exact source files using the same TypeScript transpiler.
The harness runs 21 measured pairs plus one discarded warmup, alternates variant
order, uses fresh browser contexts for cold loads and same-context reloads for
warm loads. It never clears operating-system caches. Built-in default browser
CPU/network settings apply. Font stylesheet links are removed identically and
external requests or non-GET API calls fail acceptance. Synthetic API replies use
a fixed 20 ms wait. Unknown sources return explicit 503, not fabricated success.

The ready markers require a rendered synthetic index, named security, actual news
body, and complete checked-in PCB research paragraph. All sources need not be
available: this is deliberately a partial-market fixture. `uiSettledMs` is a UI-settle proxy: the marker plus current fetch/body-read
idle and unchanged request count over two animation frames, not full market
coverage or proof that future asynchronous work cannot start. Requests measure resource entries (excluding the top-level document).
The report includes raw samples, P50/P95, JS heap, cumulative task duration,
long tasks, response bytes, unavailable sources, production build identities and
static bundle census. Task duration is cumulative per document, not a per-flow CPU
delta. Wall-clock timings have no flaky speed gate; correctness assertions do.

The native store scenarios have 25 × 1,000-character, 250 × 50,000-character,
and 1,000 × 1,000-character materials. Both variants retain all 8 getAll reads and
full global integrity validation. Baseline/candidate trials alternate. Synthetic
records are created in an isolated context, never a real browser profile.

## Node validation-cost comparison

    node --experimental-strip-types --expose-gc tests/performance/research-read.bench.mjs ./research-read.json

Copy this same harness and fixture to the baseline frontend before running it
there. It invokes actual production store code, but uses a controlled IndexedDB
scheduler and structuredClone double. This isolates validation/serialization and
is not native browser read timing. Default 15 samples after 3 warmups; set
PERF_SAMPLES for a larger final run. Run without concurrent builds/tests and retain
all samples; do not publish exploratory timings as a final user-machine result.

## Build census

    node tests/performance/build-assets.mjs ./dist ./build-assets.json

Counts initial HTML JS assets and gzip-equivalent bytes. The HTTP benchmark serves
uncompressed static data; gzip figures are a deterministic comparison, not actual
wire compression. Verifies full PCB content is still included in emitted chunks.
