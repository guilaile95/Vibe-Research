# Windows AI fixture portability — 2026-10-24

Source: PR #417 Windows job 120865596049. Changes are test-only; production network policy, model budgets and cancellation are unchanged.

- Read the UTF-8 frontend provider registry explicitly instead of Windows' default cp1252. The new temporal clock input also declares UTF-8; other newly added temporal/Interest Filter harnesses have no implicit text reads.
- Accept the two defined CONNECT request-line versions emitted by supported stdlib releases (HTTP/1.0 before Python 3.12, HTTP/1.1 from 3.12), while retaining exact numeric authority, destination, TLS verification and original host assertions.
- Reuse the strict offline socket guard. Its only exception is the actual CPython socketpair implementation's own client connecting to its exact listener. Application loopback and external connections remain prohibited.
- Isolate header/body/close timing tests from DNS-thread scheduling and unused real TLS context creation. Only the named preparation worker runs inline; model time begins at the phase under test, while real AnyIO deadline/cancellation scopes remain active. Phase entry, cancellation, owner task, cleanup and absence of false success remain asserted. Separate DNS/preparation timeout tests retain real workers.
- Add route-level proof that an expired task budget becomes the fixed PROBE_TIMEOUT SSE result with HTTP 200, rather than escaping as HTTP 500 or exposing exception details.

Validation: 138 targeted backend tests passed on Linux. Native Windows acceptance must be established by CI; Linux and forced stdlib socketpair tests do not substitute for it. No real model or external network was used.
