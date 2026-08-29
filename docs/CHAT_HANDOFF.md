# Chat Handoff — Minimal Recovery Coordinate

Do not hand-copy project history, old SHAs, lane assignments or feature inventories into a new chat.
They become stale and can override live reality by accident.

Use this handoff verbatim:

```text
接管项目

先读 AGENTS.md，
通过已连接的 GitHub + Notion 自主恢复项目。

不要依赖聊天历史。

恢复后输出 CURRENT ENGINEERING STATE，
然后继续当前最高优先级且未阻塞的工作。
```

The receiving agent must then:

1. read root `AGENTS.md` and `docs/CURRENT_STAGE.md`;
2. resolve live stable, exact-head CI, Open Issues and Open/Draft PRs;
3. read the latest live freeze/override authority and Product Reality state;
4. inspect the local workspace when available;
5. read only the Notion pages needed for the current decision;
6. report source conflicts instead of asking the Owner to reconstruct history.

The former long handoff—containing early P2/BK-11 implementation snapshots, obsolete exceptions and
old task assignments—is preserved in Git history immediately before this change and is historical only.
