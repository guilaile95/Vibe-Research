# AI Result Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist validated daily-review AI and portfolio advice by trading day, restore them without model/fresh aggregation calls, and report completion only after upstream, database, and frontend completion semantics all agree.

**Architecture:** Add a focused SQLite store plus validation/recovery service over the existing `daily_reviews.sqlite3`, then make each generation path save its validated authoritative result before returning business success. Expose one read-only result endpoint and model both frontend pages as restore/generate state machines that retain the last authoritative result while a replacement is in flight.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest, React 19, TypeScript, Zustand, Vite.

**Execution status:** Implemented and verified on 2026-07-23; the checkboxes below preserve the original TDD execution recipe.

---

### Task 1: SQLite store and validation service

**Files:**
- Create: `backend/ai_result_store.py`
- Create: `backend/ai_result_service.py`
- Create: `backend/tests/test_ai_result_store.py`
- Create: `backend/tests/test_ai_result_service.py`

- [ ] **Step 1: Write the failing store/service tests**

Cover idempotent schema creation, deterministic JSON, transactional upsert, immutable `created_at`, changing `updated_at`, latest/exact reads, damaged JSON, concurrent/repeated writes, type/date/provider/model/payload validation, fingerprint normalization, and stale computation.

- [ ] **Step 2: Run tests to verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ai_result_store.py tests\test_ai_result_service.py -q`

Expected: collection/import failure because the two modules do not exist.

- [ ] **Step 3: Implement the minimal store/service API**

The store owns only SQL/serialization and explicitly receives `db_path`; the service resolves production path through `review_history.resolve_review_db_path()`, validates records, computes SHA-256 over canonical `[{"code","shares","cost"}]`, and emits only the safe API fields.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ai_result_store.py tests\test_ai_result_service.py -q`

Expected: all tests pass using temporary database paths.

### Task 2: Real upstream completion and daily-review persistence

**Files:**
- Modify: `backend/chat.py`
- Modify: `backend/cli_runtime.py`
- Modify: `backend/app.py`
- Modify: `backend/tests/test_daily_review_ai_chat.py`
- Modify: `backend/tests/test_daily_review_ai_api.py`
- Modify: `backend/tests/test_fixes.py`

- [ ] **Step 1: Add failing tests**

Require `prepare_daily_review_analysis()` to return one review/context/messages bundle; require API SSE `[DONE]`; require stream error/EOF/no done/save failure to emit only safe `error`; require non-empty Markdown and successful upsert before business `done`; fix the Windows CLI test to use `sys.executable` and cover early generator close cleanup.

- [ ] **Step 2: Verify RED with focused pytest commands**

Run the three daily-review test files plus the CLI tests and confirm failures are the new missing semantics.

- [ ] **Step 3: Implement completion and persistence orchestration**

Raise a dedicated incomplete-stream exception when SSE closes without `[DONE]`; preserve public NDJSON event types; accumulate deltas in `app.py`, validate metadata from the same review, save once, then emit one final `done`.

- [ ] **Step 4: Verify GREEN and related chat regressions**

Run all daily-review AI, chat, and CLI test files.

### Task 3: Portfolio authoritative save and unified recovery API

**Files:**
- Modify: `backend/portfolio_advice_service.py`
- Modify: `backend/app.py`
- Create: `backend/tests/test_ai_result_api.py`
- Modify: `backend/tests/test_portfolio_advice_service.py`
- Modify: `backend/tests/test_portfolio_advice_api.py`

- [ ] **Step 1: Add failing portfolio/API tests**

Assert the fingerprint is captured from the exact pre-model portfolio snapshot, final validator/account-metric output is saved, save failure returns failure without overwriting the old row, empty portfolio preserves the old row, and GET exact/latest/cache-date recovery never calls fresh aggregation or a model.

- [ ] **Step 2: Verify RED**

Run focused API and service tests; expected failures are missing save/recovery calls and route.

- [ ] **Step 3: Implement save and read flows**

Attach the analyzed portfolio snapshot/fingerprint to the internal generation result, persist only after all validators and account metrics, return the existing authoritative payload, and add `GET /api/ai-results/{result_type}` with 200-null/422-safe/500-safe semantics.

- [ ] **Step 4: Verify GREEN**

Run all portfolio advice plus new AI result API tests.

### Task 4: Frontend completion parser and restore-capable stores

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/stores/dailyReviewAiTaskStore.ts`
- Modify: `frontend/src/stores/portfolioAdviceTaskStore.ts`

- [ ] **Step 1: Extract pure NDJSON line/state helpers and define desired state transitions**

The parser records `sawDone` and `sawError`, processes the final unterminated buffer, treats malformed protocol lines/network termination as failure, handles duplicate done and error-after-done as failure, and always releases the reader. Stores expose restore/empty/restore-error/restored/generating/regenerating states while retaining the prior authoritative payload.

- [ ] **Step 2: Implement parser and stores**

Use request IDs plus `AbortController` to prevent stale request replacement; deltas update temporary stream content only; successful completion replaces restored data; failure retains it.

- [ ] **Step 3: Type/build verification**

Run: `npm run build`

Expected: TypeScript and production build pass. The project has no frontend test runner, so critical protocol logic remains exported as pure functions and gets exercised during browser validation.

### Task 5: Restore both pages and reorder daily review

**Files:**
- Modify: `frontend/src/pages/DailyReview.tsx`
- Modify: `frontend/src/pages/Portfolio.tsx`

- [ ] **Step 1: Wire daily-review restoration and stable replacement**

After structured review loads, restore by its explicit `trade_date`; show restoring/empty/restored/restore-error/regenerating/failure-retains-old states plus saved generation/model/source times. Keep every existing market/history/detail/compare feature and render sections in the required ten-part order.

- [ ] **Step 2: Wire portfolio restoration/stale refresh**

On page load restore saved advice; after add/edit/delete/clear reload only the saved advice to update backend `stale`; never auto-generate or delete; retain all existing account and per-holding authoritative fields.

- [ ] **Step 3: Build and rendered QA**

Run `npm run build`, then verify `/daily-review` and `/portfolio` at desktop and mobile widths for state rendering, interaction, console errors, framework overlays, and horizontal overflow.

### Task 6: Documentation, full verification, self-review, commit, and push

**Files:**
- Modify: `docs/ai-result-persistence-design.md`
- Modify: `docs/superpowers/plans/2026-07-23-ai-result-persistence.md`

- [ ] **Step 1: Align design facts with implementation**

Record final module/API names, migration-on-first-use behavior, upstream completion boundary, frontend state semantics, and the absence of browser-side authority.

- [ ] **Step 2: Run fresh verification**

Run focused tests, `.\.venv\Scripts\python.exe -m pytest -m "not live"`, `npm run build`, `git diff --check origin/feature/research-system-v01...HEAD`, and inspect actual changed files and sensitive-field exclusions.

- [ ] **Step 3: Self-review**

Check each attachment requirement against code/tests, confirm `.superpowers/` and `pr_body.txt` are untouched/untracked, and confirm no real user database was used by tests.

- [ ] **Step 4: Commit and push**

Stage only task files, create logical commits, and push `codex/ai-result-persistence` without creating, readying, or merging a PR.
