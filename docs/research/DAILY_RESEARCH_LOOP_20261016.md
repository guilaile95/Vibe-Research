# Daily research collection recovery

This candidate reconstructs the previously reviewed daily collection, financial-summary preservation and compatible Kline fallback contracts from merged PR #408.

## Boundaries

- Daily provider collection runs in one disposable process with eight fixed public-source calls and serialized finite, size-bounded checkpoints. The parent reads results only after process exit or forced cleanup. Missing components remain unavailable; collection time does not invent a trade date or breadth count.
- Cold reads, background reads and explicit refreshes share a build generation. Parent cache and explicit disk-first persistence reject superseded generations. Existing critical-source and partial-versus-normal rules remain in force.
- Financial summaries are checkpointed before optional statement enrichment. Missing enrichment remains null, publication date is unknown and point-in-time support remains false. Partial checkpoints enter neither the worker success cache nor the endpoint's 30-minute cache.
- Kline stages share a 12-second work budget, each stage at most four seconds. Final forced process cleanup can add one second. Mootdx receives explicit frequency values 4/5/6/3 for daily/weekly/monthly/60-minute requests. Fallback does not change period, adjustment or qualified market coverage; busy capacity does not cause hidden bypass.

## Verification state

The source and regression tests were reconstructed through repository connectors after loss of the execution workspace. They have not been compiled or executed in this recovery. Static review and exact-head CI are required; historical results do not certify these bytes. Live provider availability, model quality, deployment and actual user data remain outside this verification.
