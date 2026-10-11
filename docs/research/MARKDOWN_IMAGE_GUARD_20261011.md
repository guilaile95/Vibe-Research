# Untrusted Markdown image guard — 2026-10-11

## Source and scope

Adapted from Simon's MIT-licensed
[`noRemoteImages.tsx`](https://github.com/simonlin1212/Vibe-Research/blob/d643728e79b955dfdcdcd8b0dd362bd7c90c35c8/desktop/src/core/ai/noRemoteImages.tsx).
The root `LICENSE` retains Copyright (c) 2026 simonlin1212 and the MIT terms.
The adaptation uses `createElement` so the existing Node TypeScript test runner can
exercise the production override directly without adding a JSX test toolchain.

Nine untrusted Markdown renders in Ask AI, Daily Review, Debate, Notes (including
imported notes and reflection), Lead Analysis and Market Intel now share the image
override. Markdown images become readable alt-text placeholders. This includes
relative URLs: untrusted text must not initiate local resource requests either.
Intentional app-owned images outside Markdown are unaffected. Stored source text,
explicit links, GFM tables, code and existing math-text behavior are unchanged.

## Evidence and limits

At the inspected baseline, no `Content-Security-Policy`, `img-src`, `urlTransform`
or `disallowedElements` guard was present in tracked frontend/backend code.
Network-free React server-render tests show the existing renderer emits an `img`
with the supplied synthetic HTTPS source; the guarded renderer emits only a span.
This establishes a rendering defect and its guard, not a demonstrated data
exfiltration exploit. No external image request, live model/provider call or
browser runtime acceptance was performed.

`frontend/tests/markdown-images.test.ts` checks the actual production override:
HTTPS/HTTP, protocol-relative, relative, data and blob image destinations;
reference images; empty/escaped alt text; linked images; preserved links, code,
math text and tables; raw HTML escaping; trusted app image independence; and
all current Markdown render sites using the guard. Existing Ask AI source wiring
coverage is updated rather than removed.

Validation commands from `frontend/`:

- `node --experimental-strip-types --test tests/markdown-images.test.ts tests/ask-ai-markdown.test.mjs`
- `npm test`
- `npm run build`

These are frontend render/aggregate/build checks only. Backend, real-market,
live-model, browser-network and product-value acceptance are outside this change.
