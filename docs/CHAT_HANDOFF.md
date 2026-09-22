# Chat Handoff — Recovery Coordinate

新对话只传递恢复入口，不复制旧 SHA、任务清单或工程状态。
恢复流程、授权边界与输出格式统一见 [AGENTS.md](../AGENTS.md#recovery-and-source-of-truth)。

```text
接管项目。
先读 AGENTS.md 和 docs/CURRENT_STAGE.md，按项目恢复规则核对 live GitHub 与本地现场。
仅在当前决定需要长期产品背景时读取相关 Notion 页面。
输出 CURRENT ENGINEERING STATE，然后继续当前已授权且未阻塞的最高优先级工作。
```
