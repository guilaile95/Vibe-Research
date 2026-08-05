# BK-11 fact digest calculator v0.1

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | GO for pure calculator candidate |
| calculator candidate | 通过（纯计算、确定性、失败关闭） |
| production integration | not authorized |
| Blocker 2 | OPEN（未评估/未改变） |
| Blocker 3 | OPEN（未评估/未改变） |
| Blocker 6 | PARTIALLY CLOSED（未评估/未改变） |
| implementation_allowed(layered_promotion_rates) | false |

本模块不宣称 Blocker 2/3/6 已关闭，不宣称 layered_promotion_rates
可实现，不宣称页面或 API 已完成。

## 2. Scope and Non-goals

### Scope

- 接收已批准 `short-term-fact-summary-v0.1` envelope
- 输出确定性 Markdown 摘要文本（digest_text）
- 服务 Daily Review 历史区块与页面接入前的基础模块

### Non-goals（硬性）

```text
- 不调用 LLM / AI 叙述
- 不依赖 live 外部数据 / 存储 / 数据库
- 不进行逐股身份跨日追踪（晋级率，Blocker 2）
- 不评估 legal zero（Blocker 6）
- 不验证 consecutive lbc 来源语义
- 不输出交易建议 / 预测 / 评分
```

## 3. Reused Contract

输入为 fact-summary envelope：

```text
schema_version == "short-term-fact-summary-v0.1"
```

7 字段精确集合（schema_version / window / status / reason_codes /
warnings / limitations / stats）。

## 4. Input Validation

```text
type(envelope) is dict（拒绝子类）
schema_version 精确匹配
7 字段精确集合
status: normal / partial / unavailable / invalid
window: {count int>=0, first/last 真实日历日期}
stats: 精确 {status_distribution, facts, ladder, gap}，或 null
```

stats=null 或形状非法 -> `SUMMARY_CONTRACT_INVALID` + `OUTPUT_SUPPRESSED`。

## 5. Digest Content

```text
标题：短线市场事实摘要（N 天，first ~ last）
摘要状态行
状态分布行（normal / partial / unavailable / invalid 计数）
facts 行（limit_up_count / advance_count / failed_board_rate /
  seal_rate / up_ratio：min / max / avg / 天数）
梯队行（最高板 max / avg，有梯队数据天数）
断层行（断层层级数 avg / max，连续梯队日）
固定脚注（统计基于 normal 状态天；不包含晋级率、逐股跨日追踪、
  交易建议或预测）
```

数值格式：

```text
int -> 原值
float -> 去尾零（最多 4 位小数）
null -> "n/a"
```

## 6. Output Schema

```text
schema_version
status
reason_codes
warnings
limitations
digest_text
```

固定 limitations：

```text
deterministic digest of a fact-summary envelope
stats describe normal-status days only
does not compute layered promotion rates
does not validate consecutive-limit-up semantics
no per-stock cross-day identity tracking
no trade advice, prediction, or scoring
```

## 7. Status and Reason Codes

固定 reason-code 顺序：

```text
INPUT_CONTRACT_INVALID
SUMMARY_CONTRACT_INVALID
OUTPUT_SUPPRESSED
```

映射：

```text
summary status normal   -> status=normal, reason_codes=[]
summary status 非 normal -> 保留原状态，[OUTPUT_SUPPRESSED]
输入合同非法 / stats=null -> invalid,
  [SUMMARY_CONTRACT_INVALID, OUTPUT_SUPPRESSED]
```

## 8. Determinism

```text
相同输入 -> 完全相同的 digest_text
```

## 9. Exception Boundary

```text
公共入口只捕获 except Exception
普通异常 -> 固定 invalid envelope（INPUT_CONTRACT_INVALID +
  OUTPUT_SUPPRESSED，digest_text=""）
emergency fallback 直接构造完整固定字面量，零业务 helper、
  零输入读取、零异常文本
KeyboardInterrupt / SystemExit / GeneratorExit 自然传播
```

## 10. Input Immutability

```text
调用前后输入深度相等
输出不共享输入引用
```

## 11. Test Evidence

正式测试覆盖（`backend/tests/test_short_term_fact_digest.py`）：

```text
公开合同 / 标题与状态行 / stats 行内容 / 脚注
partial 状态透传 + OUTPUT_SUPPRESSED
确定性（两次调用文本相等）
合同（非 dict / schema / stats 缺失或 null / 额外字段 / window / status）
输入不可变 / limitations 固定 / 跨调用隔离
普通异常固定 fallback（3 helper x 3 异常类型）
进程控制异常传播
```

独立验证脚本（一次性，不提交）：见执行记录（seed 固定并报告）。

## 12. Limitations

```text
1. 文本为确定性摘要，不包含 AI 叙述
2. 统计描述基于 normal 状态天
3. 不进行逐股跨日追踪 / 晋级率
4. 不输出交易建议 / 预测 / 评分
5. 不接入生产页面 / API / 调度器
```

## 13. GO / CONDITIONAL GO / NO-GO

**GO for pure calculator candidate**

- 纯计算、确定性、失败关闭、输入不可变
- 文本内容机械可复算
- 正式测试与独立验证全部通过

剩余限制：

```text
- production integration not authorized
- layered_promotion_rates 生产实现仍不允许
- Blocker 2/3/6 未在本轮评估
- 不得宣称页面/API 已完成
```
