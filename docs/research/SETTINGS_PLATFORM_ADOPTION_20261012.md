# Settings and platform adoption — 2026-10-12

## Source and bounded contract

Compared against Vibe-Astock commit
`d5bf80d2ed1629f8fa602058093f8d41bb0c7ace`, specifically
[`orchestrator/src/finance/sec_contact.ts`](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/orchestrator/src/finance/sec_contact.ts),
[`orchestrator/src/update_check.ts`](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/orchestrator/src/update_check.ts), and
[`desktop/src/verticals/finance/lib/update.ts`](https://github.com/simonlin1212/vibe-astock/blob/d5bf80d2ed1629f8fa602058093f8d41bb0c7ace/desktop/src/verticals/finance/lib/update.ts).

A39 settings now expose an explicit SEC contact configuration and a manual
release check within the existing Settings page. `backend/platform_settings.py`
is the authority only for this previously missing nonsecret setting; it does not
replace model credentials, Native Intel settings, runtime, deployment or launch
configuration. `version.read_version` remains the software version authority.

SEC contact is an owner-entered English name and email intended for eventual
SEC User-Agent identification. Nothing is prefilled; saving only validates and
stores it locally. **No SEC transport is connected or activated.** It is not an
API credential, but remains personal data: status omits the name/email entirely,
files are excluded from repository artifacts by residing in the existing private
data directory, and no provider or update request receives the value. Explicit
future SEC transmission remains outside this delivery. The optional
`VR_SEC_CONTACT` deployment setting is read-only in the UI. Remote request
addresses, remote Host/Origin, and environment-managed settings cannot use the
contact write endpoint. Existing application Host/Origin/key security still
applies; reverse proxies must preserve those boundaries and must not disguise
remote requests as owner-local traffic.

A revision token prevents stale writes in the existing single-process backend.
Descriptor-relative POSIX I/O and non-following Windows parent handles pin the directory chain; symlinks/reparse points and changed file identities are refused. Windows handle execution is not established by Linux fixture tests. Atomic replacement leaves the previous file intact on pre-replacement failure;
corrupt stores fail closed. Blank input explicitly saved clears the setting.
The UI does not echo stored identities. Dirty drafts survive refresh and failed
or uncertain writes; a successful save requires status readback with the new
revision. A synchronous operation gate prevents duplicate same-render actions, and read ownership prevents older results replacing refreshed state. Uncertain writes require an explicit reread before retry.

## Release check adaptation

Only the explicit local manual button calls the fixed official endpoint
`https://api.github.com/repos/guilaile95/Vibe-Research/releases/latest`.
GET capabilities never contacts a network or writes settings. Checks have a
five-second transport timeout, elapsed-time guard, 256 KiB streamed byte cap,
no redirects, no environment proxies, and no authentication/contact headers.
Release-provided arbitrary URLs, bodies and error messages are never displayed.
Links are constructed only from validated stable version tags on the fixed
repository. Canonical UTC publication timestamps must be real and no later than
the check timestamp. Three-part numeric versions are compared numerically;
prereleases, malformed fields and unknown current versions cannot imply current.

Results distinguish never checked, unavailable, release not found (404, possibly unavailable repository), unknown current
version, same version, ahead and update available. Check time and release time
are separate. A result is process-local observation, not a persisted promise or
installation verification. This deliberately differs from upstream's automatic
daily GET-triggered checking, skipped-version persistence and portable-upgrade
instructions: this delivery offers **manual read-only checks only**, with no
download, install, execution, service changes or deployment activation.

## A59 existing contracts, not a second launcher

- Windows: `Start-Vibe.cmd` delegates to `start-vibe.ps1`; backend reuse and
  startup readiness use the existing service marker. Existing
  `test_windows_launcher_backend_identity.py` checks both callsites; its real
  PowerShell function test is Windows-only. The existing Windows workflow owns
  actual startup/shutdown CI. This Linux test run does not certify Windows.
- Linux: `tools/linux/vibe_linux.py:commands` uses the existing loopback
  frontend/backend/runtime ports. Existing `verify`, `safe_path`, `install`,
  `run`, and owned-process cleanup contracts are exercised by
  `tools/linux/test_vibe_linux.py`: integrity, traversal/symlink rejection,
  private-file exclusion, failed-install isolation, fixed ports, timeout and
  partial-child cleanup. No package was built or installed in this task.
  Existing Linux packaging is not fully offline or dependency-free;
  [Linux installation documentation](../LINUX_INSTALL.md) remains authoritative.
- macOS: no dedicated supported launcher/portable deployment contract is
  established by this source. Capability status says unsupported launcher;
  it does not claim that browser source code cannot run on macOS.
- Ports/security/runtime paths: existing `runtime_info_router.create_router`,
  `BackendRuntimeCard`, application local API middleware and deployment guides
  remain the authority. New capability status does not expose source paths.
- Themes: existing application theme controls remain unchanged. No upstream
  brand or second runtime/launcher is imported.

## Verification scope

Focused backend fixtures cover local status, local/remote/environment controls,
strict contact types/header guards, corruption, atomic-write failure, revision
conflicts, release source/versions/dates, redirect refusal, response size,
manual-only activation and concurrent-check rejection. The guarded regression
selection additionally checks existing runtime info, API security and Windows
launcher identity. Linux packaging/lifecycle tests use fixtures and mocks.
Frontend tests run the actual Settings card JSX with an isolated hook harness,
including failed initial read, dirty refresh, lost save response, explicit
recovery and update failure, plus strict response parsers. Build includes type
checking. These are offline software/CI-style tests, not a browser visual test,
live SEC/GitHub check, native OS installation, real model or market acceptance.
