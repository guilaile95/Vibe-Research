# Project Governance — Current Authority Model

The root [`AGENTS.md`](../AGENTS.md) is the **single body of engineering and agent rules**.
This file is only a short map of authority sources; it must not copy a second rulebook or maintain
transient task state.

The former Governance v0.1 document is preserved in Git history immediately before this change. It
was retired because it still named `PROJECT_STATE.md` and `NEXT_TASK.md` as current authorities,
listed an obsolete CI job set, and carried historical recovery instructions as if they were active.

## Authority roles

- **Live GitHub = Engineering Truth**: stable branch, exact Git objects, Issues, PRs, reviews, checks,
  tests and current freeze/override authority.
- **`docs/CURRENT_STAGE.md` = recovery coordinate**: where to look next, never a substitute for live
  GitHub.
- **Notion = durable product/architecture context**: goals, decisions, research and long-lived lessons.
- **Local workspace = uncommitted execution reality**: inspect before touching files; never overwrite
  it from remote assumptions.
- **Owner's latest explicit decision = product/authorization authority**. A backlog item, old Draft,
  historical document or agent report is not permission to implement.

When sources disagree, report the conflict. Do not silently edit one source to imitate another.
Engineering completion follows GitHub and actual validation; product direction follows the Owner's
latest explicit decision and should then be synchronized to Notion.

## Freeze and authorization

Issue [#203](https://github.com/guilaile95/Vibe-Research/issues/203) is the durable freeze authority.
Read its latest comments rather than its original body alone. A narrow Owner override authorizes only
its named scope and ends when its completion comment restores the freeze.

Issue [#162](https://github.com/guilaile95/Vibe-Research/issues/162) is the Product Reality contract.
Real-use observation is not a feature-development lane, and tests or demos cannot fabricate Day 1.

Actions that still require separate Owner authorization are defined in `AGENTS.md`, including stable
push/merge, Ready transition where applicable, force operations and destructive cleanup.

## CI and delivery truth

The current workflow file and live check runs define CI. Do not maintain a copied job count or stale
list here. A green run proves only what its jobs exercised; it is not by itself semantic approval or
product-value proof.

Before accepting a change:

1. inspect the actual diff and source-to-sink behavior;
2. run the smallest sufficient targeted checks;
3. run the required exact-head CI/integration gate;
4. independently compare the evidence with the task acceptance criteria;
5. keep the PR Draft and unmerged unless the Owner separately authorizes the transition.

Historical Draft PRs remain context only. Do not revive, merge, close or delete them merely to make the
repository look tidy; perform a separate verified archive pass when explicitly authorized.
