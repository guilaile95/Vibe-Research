# Discovery lifetime validation

Base: `8c141d554507b6228627271f1ef759485040591d`. Production Discovery and
public-data lifecycle code was not changed for this validation.

## Executed evidence

`backend/tests/test_discovery_resource_lifecycle.py` adds three no-network
experiments with actual spawned children, not mocked `kill`/`join`:

- Three full 24-code shortlists, each with a 1.5-second qualification deadline
  and deliberately hanging local providers: every return has no remaining child,
  all four public-provider slots and all 28 qualification slots reusable.
  Subsequent operation succeeds; next provider phase is not entered after
  cancellation. Idle shared executor threads remain bounded at four.
- Explicit cancel after a real child writes its entry marker: the call reports
  `SOURCE_CANCELLED`, the child is reaped before return and admission is reusable.
- Pre-cancelled work is never admitted and consumes no slot.

These tests plus existing Discovery service/remediation tests passed: 41 tests.
They use reduced deadlines for repeatable CI; they do not simulate a browser
abort as proof that the backend received cancellation.

A separate no-network Linux experiment retained the actual 45-second
qualification and 12-second provider budgets with 24 codes. It returned in
45.006641704 seconds, with 4 completed qualifications and 20 timed out. Sixteen
actual local child entry markers were observed across the provider phases.
At return no children remained, all admission slots were reusable, and a new
successful operation ran. Four idle shared executor threads remained by design.
The supplied JSON evidence retains every provider call and timeout/cancel result.
A concurrent-child peak was **not measured**: the `/proc` observer returned zero
despite entry markers, so that metric is excluded rather than presented as zero
resource usage.

## Observation caveat and scope

An earlier default-budget attempt used concurrent
`multiprocessing.active_children()` sampling. That API can reap processes, so it
is not a passive observer of concurrent join/kill. Its slot-reuse assertion
failed; causality was not isolated. It is retained as an inconclusive,
measurement-interfering attempt, not proof of a product leak or a product fix.
The later non-reaping observation passed the above cleanup assertions.

The existing app shutdown hook immediately cancels the shared overview refresh,
not every Discovery qualification group. Qualification work remains bounded by
its own deadline and provider cleanup; no new universal instant-stop mechanism
was added. Arbitrary injected synchronous Python callables still cannot be
forcibly killed, although their shared worker count/admission is bounded and no
new phase starts after cancellation. Production provider calls use processes.

No live provider calls, Windows native run, day-long soak, memory-leak proof,
network-socket instrumentation, production restart or real user data was involved.
Evidence supports the tested bounded local recovery, not all-environment stability.
