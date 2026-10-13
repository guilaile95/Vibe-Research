# Local OCR and public research exports

## Scope and authority

A36 adds explicit local Tesseract OCR for archived PDF/PNG/JPEG files. A29 can reuse the ephemeral screenshot preview. A58 adds a selected public-market observation card to StockData; existing private Notes backup and original-report download remain separate.

No model/provider request, background OCR, second report store, formal-state write, public hosting, or third-party publication is introduced. OCR output is uncertain derived text, never a verified source fact. Original report bytes are not rewritten.

## Local OCR contract

- `GET /api/local-ocr/capability` only inspects fixed executable locations. It creates no directories/index/processes. Language files are checked at fixed system locations without spawning a process; execution is bound to the same fixed tessdata directory. Missing chi_sim is explicitly CHINESE_LANGUAGE_UNAVAILABLE in capability, UI and action errors; English is never an automatic fallback. The inspected Linux engine has eng/osd only; Chinese OCR is not available or quality-tested there.
- `POST /api/local-ocr/preview`: raw base64, `.png`/`.jpg`/`.jpeg`, `eng` or `chi_sim+eng`, and explicit local-processing confirmation. No filename, path, URL, binary or shell argument is caller-controlled. The preview is ephemeral.
- Preview schema: `local_ocr_preview.v1`, `OCR_UNVERIFIED` or `OCR_NO_TEXT`, one image page, source/image/text SHA256, mean recognized-word confidence, engine/language, limitations, and `source_truth_verified=false`. A confidence score is not a truth probability. Saved-report acknowledgement schema is local_ocr_report_receipt.v1; the UI validates report/source/language/pages/uncertainty before claiming success and locks uncertain retries until an explicit successful index reread.
- `POST /api/local-ocr/reports/{id}` requires the expected immutable source SHA256 and explicit confirmation. It resolves only catalog-owned files, rejects symlinks/path traversal, rechecks source identity before and after extraction, then commits derived text and provenance in the existing fulltext SQLite transaction. Read-only search/page retrieval revalidates source and OCR text hashes. The existing accepted foundation private-image reader is reused: SQLite receives an in-memory checkpointed copy, active journals fail closed, and the source identity/bytes are checked again on close. No source WAL/SHM is created by these reads.
- Bounds: 8 MiB input, 12 PDF pages, image side at most 6000, 16 million input pixels, 32 million aggregate rendered pixels, 2000-pixel PDF render side, 100000 total text characters, 1 MiB process output, 90-second aggregate deadline, one OCR process pipeline per server process. The server must retain its existing single-process local deployment for the process-wide concurrency limit.
- Executables use fixed system paths, argument arrays, no shell, a minimal environment and one OpenMP thread. A fixed isolated server-Python launcher enforces Linux RLIMIT_AS (768 MiB), CPU (90 seconds), FSIZE (16 MiB per output file), NOFILE (64) and CORE (0) before native exec; resource enforcement failures fail closed. Timeout/disconnect cancellation terminates the process group, waits for it, removes temporary files and does not commit an unfinished extraction. An already committed result is not rolled back by a later browser abort.
- Encrypted/malformed documents, absent executable/language, busy capacity and exceeded bounds are distinct failure codes. Failures preserve an existing usable index and the original. PNG/JPEG headers and dimensions are checked before native decoding.
- Windows local dependencies are not bundled/verified by this change and capability reports `WINDOWS_DEPENDENCIES_NOT_BUNDLED`. It does not claim Windows OCR execution. English synthetic execution was verified on installed Linux tools; Chinese language-pack quality remains unverified; macOS also reports RESOURCE_GUARD_UNAVAILABLE until a verified bounded native adapter exists. No unbounded fallback is used.

## Sanitized share contract

The card is constructed from a closed allowlist: six-digit security identity and explicitly selected numeric price, PE-TTM and/or total-market-value observations. Arbitrary names, prose, source URLs, paths, account/portfolio/journal objects, prompts and credential strings cannot flow into JSON or SVG. Known fixture identity is preserved. Values remain missing when invalid, rather than zero.

Source identities and fields are fixed. Quote trading date is validated and applies only to price. PE/market-value source timestamps remain explicitly unknown; download time is never substituted. JSON and passive, escaped SVG download locally after a preview; neither is published. Provider observations are not independent verification or investment advice.

## Acceptance and remaining gates

Focused Python tests include real installed Tesseract plus Poppler on generated synthetic PNG and image-only PDF; existing report search/page/chat/corruption regression coverage; stale-source/cancel/no-write/size/path/encryption/schema tests. Frontend unit tests parse the JSON projection and check SVG/private-string exclusion. A production-component adapter covers desktop/mobile explicit OCR, dependency failure, cancel/no-late-refresh, page provenance and JSON/SVG downloads using strict HTTP fixtures. The adapter build is local evidence; actual browser acceptance runs in CI only and must not be represented as a local browser pass.

Real user files, Chinese OCR quality, Windows/macOS native execution, production deployment and external publication are not accepted by these synthetic tests.
