# CLI Security v0.1 (P0-SEC2)

**Status:** implementation contract

**Authority role:** HTTP-reachable local AI CLI execution boundary (subscription CLI path)

**Policy version:** `cli_security.v0.1`

## Boundary

This policy answers one question only: under what conditions may an HTTP request
launch a local, logged-in AI CLI (Claude Code / Qwen / DeepSeek / Codex) as a
subprocess, and what resource bounds apply to every such launch.

It is a **convergence** contract: the `cli-*` provider surface changes from
"generic agent execution" to an explicitly authorized, text-only, bounded,
minimal-environment, process-contained execution surface.

## Threat model

Vibe-Research runs locally, binds a loopback HTTP server, and exposes a "subscription
AI" feature: any HTTP client that can reach the server can request
`provider=cli-*`, and the backend launches the user's logged-in AI CLI on the same
machine. The AI CLIs are agentic tools (filesystem read/write, shell execution,
code editing, web, plugins, MCP, sub-agents). The audit (S-02, S-06) identified:

- **S-02**: HTTP can drive a local high-privilege AI CLI. A malicious or compromised
  local process (browser extension, other local service) can POST to the loopback
  server and cause arbitrary agentic actions under the user's identity.
- **S-06**: CLI input / process / output resource boundaries are insufficient:
  child inherits the full `os.environ` (API keys, DB URLs, secrets), stdout is
  unbounded (`capture_output=True` / unbounded `queue.Queue()`), concurrency is
  unlimited, `proc.kill()` kills only the parent process leaving orphan CLI/tool
  children, timeout is per-operation rather than total wall-clock.

Freezing principle: **HTTP-reachable CLI MUST NOT be general agent execution.**
Temp-CWD is not tool disablement: `cwd=<tmpdir>` does not stop an agentic CLI from
reading files elsewhere, running shell, or calling the network. Only a proven
no-tools text-only invocation contract qualifies.

## Explicit opt-in and authentication (HTTP execution gate)

HTTP-reachable CLI execution is **disabled by default** and fail-closed. All three
conditions must hold; otherwise the request is rejected with `CLI_EXECUTION_DISABLED`
(HTTP 403 on routes that pre-check, or a fixed error inside the runtime):

1. `VR_ENABLE_LOCAL_CLI=1` (explicit opt-in);
2. `VR_API_KEY` non-empty (the deployment is authenticated; loopback + no API key
   does not permit HTTP → process launch, because other low-privilege local
   processes can also reach localhost);
3. the requested provider is marked `http_allowed=True` in `CLI_SECURITY_CAPABILITIES`.

The gate lives at the CLI execution boundary (`cli_runtime.assert_http_cli_authorized`,
invoked by `run_cli` / `run_cli_stream` with `via_http=True`) so no HTTP route can
bypass it. `_require_llm_ready` and the decision-cockpit route pre-check the same
gate before touching `detect_cli`, so an unauthorized caller cannot probe which
CLIs are installed. There is no silent fallback: a disabled/unauthorized CLI
request is never rerouted to an API provider or another CLI. All four HTTP
entrypoints (chat, daily-review analyze, portfolio advice, decision-cockpit
tomorrow-plan) are covered.

## Text-only proof and provider matrix

Only providers with a **proven** no-tools, text-only invocation contract may be
reachable through HTTP. Proof requires current CLI `--help`/version output plus
official primary documentation that the tool-execution path is actually
uninvocable — not a deny-list guess (`--disallowedTools`) and not a flag
substitution (`--yolo` → "approval mode").

Audited 2026-08 (all `NOT_PROVEN`, all `http_allowed=False`):

| Provider | Version | Mechanism examined | Verdict |
| --- | --- | --- | --- |
| Claude Code | 2.1.226 | `--allowedTools` (empty allowlist), `--permission-mode dontAsk`, `--safe-mode`, `--bare` | NOT_PROVEN: empty-allowlist argv contract not verified end-to-end on this machine |
| Qwen Code | v0.21.10 | `--exclude-tools` (explicit enumeration, no wildcard), `--safe-mode`, plan mode | NOT_PROVEN: no single no-tools switch; read tools still need manual enumeration |
| DeepSeek | — | No official CLI exists; `deepseek`/`codewhale` is the community CodeWhale project; `--disallowed-tools` glob not officially endorsed | NOT_PROVEN |
| Codex | rust-v0.147.0 | `--disable shell_tool`, `--sandbox read-only`, `-a never` | NOT_PROVEN: read-only sandbox is read-only-tools, not no-tools |

`QWEN_YOLO_HTTP_ALLOWED = NO`, `DEEPSEEK_AUTO_HTTP_ALLOWED = NO`. Until a provider
is proven, `http_allowed` stays `False`. This file is the authority; flipping a
provider requires updating `CLI_SECURITY_CAPABILITIES` with a new proof (docs +
argv contract test).

## Login state (opencode pattern)

Credentials belong to the CLI, not to Vibe. Child processes receive a minimal
environment containing only platform variables required to run the CLI and locate
its own login state (`~/.claude`, `~/.codex`, `~/.local/share/opencode/auth.json`,
etc. via `HOME` / `USERPROFILE` / `APPDATA` / `LOCALAPPDATA` / `XDG_CONFIG_HOME`).
No model API key is forwarded from the Vibe environment to the CLI. A provider
that can only run on an API key forwarded by the parent is not a subscription-CLI
path and is not opened automatically.

## Minimal child environment

`env = {**os.environ, ...}` is deleted. The child environment is an explicit
allowlist (`_CHILD_ENV_ALLOWLIST`): `PATH`, `PATHEXT`, `SYSTEMROOT`, `WINDIR`,
`COMSPEC`, `TEMP`, `TMP`, `TMPDIR`, `HOME`, `USERPROFILE`, `APPDATA`,
`LOCALAPPDATA`, `XDG_CONFIG_HOME`, `LANG`, `LC_ALL`, `LC_CTYPE`.

Not inherited: `VR_API_KEY`, `IWENCAI_API_KEY`, `TUSHARE_TOKEN`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `DATABASE_URL`, `DB_URL`, any
`*_PASSWORD`, `*_SECRET`, unrelated `*_TOKEN` / `*_KEY`.

`PROXY_ENV_INHERITANCE = NO`: proxy variables are not copied; CLIs use their own
network configuration. Credential-bearing proxy URLs are never forwarded.

`FULL_OS_ENV_INHERITANCE = NO`, `SECRET_ENV_LEAK = NO` (enforced by adversarial
sentinel tests).

## Input budget

`CLI_INPUT_LIMIT_BYTES = 500_000`. The combined input (system prompt + user prompt,
covering stdin / positional arg / system-file deliveries uniformly) is counted in
UTF-8 bytes before spawn. Over budget: fail closed with a fixed error — never
silently truncated. The provider-specific positional-arg limit
(`_MAX_ARG_BYTES = 110_000` for DeepSeek's arg delivery) remains an additional,
stricter bound and is not a substitute for the global limit.

## Output budget

`CLI_OUTPUT_LIMIT_BYTES = 1_000_000` (`MAX_STDOUT_BYTES`), enforced on **both**
stream and non-stream paths. Exceeding the budget terminates the process tree and
returns `CLI_OUTPUT_LIMIT` — never silent truncation with success. stderr is
redirected to `DEVNULL` and never reflected to the HTTP client. The non-stream
path no longer uses `subprocess.run(capture_output=True)` (unbounded collector);
both paths share one bounded process runner.

Streaming uses a bounded queue (`CLI_QUEUE_MAXSIZE = 256`) with a `stop_event`
and timed puts, so a slow consumer cannot cause unbounded RAM growth or deadlock
the pump thread.

## Concurrency and deadline

`CLI_MAX_CONCURRENT_PROCESSES = 2`, shared by `run_cli` and `run_cli_stream` via a
single global semaphore (no per-provider unlimited slots). Slot acquisition has a
deterministic timeout (`CLI_CONCURRENCY_ACQUIRE_TIMEOUT = 10.0s`); over capacity
fails fast with `CLI_BUSY`. The slot is released on success, failure, and
cancellation.

`CLI_TOTAL_DEADLINE_SECONDS = 300` is a total wall-clock deadline covering process
start, stdin delivery, stdout streaming, and process exit — not an idle timeout.

## Process tree containment

Timeout, cancellation, output-limit, and internal failure all terminate the
**entire process tree**, never only the parent:

- POSIX: `start_new_session=True` + `os.killpg(pid, SIGKILL)`;
- Windows: native `taskkill /pid <pid> /t /f`.

Verified by process-tree tests (parent spawns a child sleeper; after
timeout / cancel / output-limit both parent and child are dead). Windows CI is
covered; POSIX coverage runs on POSIX CI.

`PROCESS_TREE_CONTAINMENT = YES`.

## Temp directory

Each run gets a unique `mkdtemp(prefix="vibe-cli-")` working directory (never the
repo cwd). The system-prompt file (`system.txt`) and the directory are removed in
`finally` on every path.

## Shell safety and argument delivery

`shell=False` is frozen; argv is always a list. The binary comes only from the
fixed provider registry (`_CLI_DEFS`) resolved by `detect_cli`; users cannot inject
a binary path, arbitrary argv, or a shell string. Unsupported kinds fail closed
(`CLI_UNAVAILABLE`). All delivery modes (stdin / positional arg / system file)
pass through the same input budget.

## Error redaction

Public CLI errors carry fixed classification codes only: `CLI_UNAVAILABLE`,
`CLI_EXECUTION_DISABLED`, `CLI_TIMEOUT`, `CLI_OUTPUT_LIMIT`, `CLI_BUSY`,
`CLI_FAILED`. Error text never contains filesystem paths, argv, environment,
stdout/stderr dumps, tokens, or credentials. Internal logs may record provider,
stage, error class, and duration — never prompt, context, or secret env.

## Non-goals

- **No OS sandbox is claimed.** Temp-CWD + argv contract is not sandboxing; no
  claim of OS-level isolation is made.
- No RBAC, user accounts, JWT, or OAuth.
- No request-body limiter for the whole FastAPI surface (that is a separate
  runtime-budget slice, not this one).
- SSRF / DNS-rebinding / redirect handling for remote HTTP providers is out of
  scope here (P0-SEC3).
- Global CLI config (`~/.codex`, `~/.claude`, `~/.qwen`, `~/.deepseek`) and login
  state are never modified; only the Vibe invocation contract changes.
