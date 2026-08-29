# Next Task — Authorization Pointer

> **THE FORMER P0-DI1 TASK BODY IS ARCHIVED AND NO LONGER GRANTS AUTHORIZATION.**
>
> It named an old exact SHA, executor and file allow-list from 2026-08-12. Keeping that text as
> “current execution authority” would cause a new agent to restart completed work. The full historical
> task remains available in Git history immediately before this change.

Current work authorization is resolved in this order:

1. the Owner's latest explicit instruction;
2. live GitHub authority, especially the latest comments on Issue
   [#203](https://github.com/guilaile95/Vibe-Research/issues/203) and any narrowly named active Issue;
3. [`docs/CURRENT_STAGE.md`](CURRENT_STAGE.md) as a recovery coordinate;
4. live PR, branch and CI state.

A roadmap item, old Draft PR, historical lane assignment, Notion note, or this file by itself is never
implementation authorization.

The current product stage is Product Reality Issue
[#162](https://github.com/guilaile95/Vibe-Research/issues/162). It is a real-use observation contract,
not permission to add features. When engineering is frozen and no explicit override is active, the
correct next action is to support a real Owner workflow and record evidence—not to invent a new slice.
