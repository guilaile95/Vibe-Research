# BK-11 external-source holiday probe v0.1

> 证据工件：`docs/research/BK11_EXTERNAL_SOURCE_HOLIDAY_PROBE_V01.json`
> （本文所有数字均可在该 JSON 中离线复算。）

## 1. Executive Decision

| 项目 | 结论 |
|------|------|
| overall | CONDITIONAL GO |
| Blocker 2 | candidate CLOSED pending independent review |
| Blocker 3 | OPEN（替代来源自身日期语义 VERIFIED；东财日期语义仍 OPEN） |
| Blocker 6 | PARTIALLY CLOSED（未探测 legal zero） |
| 替代来源建议 | ADOPT_FOR_FURTHER_DESIGN |
| implementation_allowed | false |

`ADOPT_FOR_FURTHER_DESIGN` 仅表示来源值得进入后续架构与许可评估，
不代表已接入生产、不代表已批准替换东财、不代表允许
`layered_promotion_rates`。

本轮实测总 live 请求 26 次，超出 20 次预算 6 次，原因与完整清单见
§6 与 §19。其余请求纪律全部遵守。

## 2. Scope and Non-goals

### Scope

- research-only：只读外部公开数据探测 + 标准化 + 机械计算
- 为 Blocker 2 补充节假日边界（Pair C）跨日 stock_code / lbc 证据
- 评估一个替代公开来源的历史日期绑定、稳定性、字段完整性
- 与既有东财 Slice 2D 工件（Pair A / Pair B）交叉核验
- 输出 adopt / reject / insufficient-evidence 建议

### Non-goals

- 不实现 layered_promotion_rates
- 不修改生产代码 / adapter / producer / validator / gate
- 不接入新数据源、不新增运行时依赖
- 不创建 API / 前端 / 数据库 / 调度任务
- 不修改 Blocker 6 的 legal-zero 合同
- 不创建 PR、不 merge、不自行启动后续子阶段
- 不探测或推断 legal zero

## 3. Existing Evidence Baseline

以下为既有已批准证据（本轮不重复声称首次获得）：

```text
Pair A: 2026-07-30 -> 2026-07-31, ordinary_consecutive
Pair B: 2026-07-24 -> 2026-07-27, cross_weekend
Pair C: 2026-06-18 -> 2026-06-22, post_holiday
```

既有结论（Slice 2D / Slice 2F / Slice 2H）：

```text
Pair A: 东财非空、两轮稳定、可机械复算
Pair B: 东财非空、两轮稳定、可机械复算
Pair C: 东财两日均 EMPTY_UNEXPLAINED
Blocker 2: OPEN（Pair C 空数据导致未闭合）
Blocker 3: OPEN（东财 payload 无可独立验证的 trade_date 字段）
```

东财 Pair A/B 标准化工件来自
`docs/research/BK11_LAYERED_PROMOTION_PROBE_V01.json`（已批准），
本轮交叉核验直接引用该工件，不再重跑东财探针。

## 4. Source Candidate Matrix

评估了三个候选，均按以下最低条件筛选：

```text
无需登录 / API key / Cookie / Token / 付费账户 / 验证码绕过 / 伪造凭据
允许按历史交易日查询
具有明确日期语义
能直接提供或机械推导 stock_code + consecutive limit-up count / lbc
```

| 候选 | domain | 凭证 | 历史日期 | payload 日期字段 | 选择 |
|------|--------|------|----------|------------------|------|
| 同花顺涨停池 dataapi | data.10jqka.com.cn | 无 | 支持 date=YYYYMMDD | data.date（实测存在） | 选中 |
| Tushare 涨停列表 | api.tushare.pro | 需 token | 支持 trade_date | trade_date | 拒绝：凭证条件不满足 |
| 东财 getTopicZTPool 历史 | push2ex.eastmoney.com | 无 | 支持 date 参数 | 无（既有 Blocker 3 缺口） | 拒绝：与既有源同源且无 payload 日期 |

完整矩阵（access_method / response_format / rate_limit /
retention / terms 观察）见 JSON `source_candidate_matrix`。

来源文档依据：

- 同花顺涨停池端点用法来自本机已安装的公开数据技能记录
  （a-stock-data，2026-07 实测记录，含 20260626 历史日期示例），
  本轮以实际请求验证（observed fact）。
- Tushare 需 token 为公开 API 文档说明（source documentation）。
- 东财 payload 无日期字段为既有 Slice 2D 已验证结论（observed fact）。

## 5. Selected Source

```text
source_name: 同花顺涨停池 dataapi (limit_up_pool)
domain: data.10jqka.com.cn
endpoint: /dataapi/limit_up/limit_up_pool
access: HTTP GET, User-Agent + Referer only（实测 200，零鉴权）
request params:
  page=1 limit=200
  field=199112,10,9001,330323,330324,330325,330326,9002,330329,
         133971,133970,1968584,3475914,9003,9004
  filter=HS,GEM2STAR   （沪深主板+创业板+科创板）
  order_field=330324 order_type=0
  date=YYYYMMDD
payload date field: data.date（实测值 = 请求日期 YYYYMMDD）
stock code field: info[].code（六位数字字符串）
lbc derivation: info[].high_days
  "首板" -> 1
  "N天M板" -> M
response format: JSON
```

选择理由（observed fact + mechanical derivation）：

```text
1. 唯一同时满足全部最低条件的候选
2. payload 自带 data.date，可做响应内日期绑定（Blocker 3 替代路径）
3. 每条记录自带 first_limit_up_time（unix 秒），可做逐记录日期证据
4. 与东财不同域名、不同风控面，适合做独立交叉核验
```

## 6. Request Discipline

### 设计参数（全部执行）

```text
串行、无并发
相邻数据请求间隔 >= 2.2 秒（实测最小 2.344 秒）
单请求 timeout <= 15 秒
每请求最多重试 1 次（实测重试 0 次）
无 Cookie / Token / 认证 Header / 设备指纹 / 代理池 / IP 轮换
无登录、无验证码绕过
```

### 请求清单

```text
结构预检 x1         （2026-07-31，检查响应结构与字段）
字段语义确认 x1     （2026-07-31 limit=10，确认 UTF-8 字节与 high_days 格式）
主探针 6 日期 x2 轮  x12
--------------------------------------------
合计 26 次（含一次被取代的 12 次主探针重跑）
```

### 预算超支披露（evidence defect）

```text
预算上限: 20 次
实际合计: 26 次（超支 6 次）
原因: 第一次主探针脚本存在解析缺陷（high_days="首板" 未处理）与
      持久化缺陷（normalized rows 未落盘），证据不可用；
      必须用修正脚本重跑 12 次主请求。
处置: 所有请求仍遵守串行 / >=2.2s / <=15s / 无凭据纪律；
      被取代的 12 次请求完整保留于 JSON `superseded_request_ledger`；
      停止条件（401/403/429/验证码/反自动化）全程未触发。
```

这是本轮唯一已知的纪律偏差，如实记录，不隐瞒。

## 7. Data-retention Boundary

JSON 工件只保留：

```text
source metadata / request ledger / requested date
payload date evidence / stock_code / lbc
标准化计数 / SHA256 / 跨日计算结果 / 异常分类
```

未保留、未提交：

```text
股票名称 / 价格 / 成交额 / 行业 / 封单数据 / 完整原始响应
Cookie / Token / 认证 Header / 设备指纹 / 访问控制页面
异常堆栈中的敏感 URL 参数
```

一次性脚本与缓存（`_probe_cache.json`、`_probe_cache_final.json`）
在任务结束前删除，不提交。

## 8. Date-binding Evidence

### 主证据：data.date（observed fact）

12 次主请求全部返回 `data.date`，解析后与请求日期一致：

```text
2026-06-18 -> data.date=20260618, match=true
2026-06-22 -> data.date=20260622, match=true
2026-07-24 -> data.date=20260724, match=true
2026-07-27 -> data.date=20260727, match=true
2026-07-30 -> data.date=20260730, match=true
2026-07-31 -> data.date=20260731, match=true
```

### 次级证据：逐记录交易日期（observed fact）

每条记录 `first_limit_up_time`（unix 秒）换算 Asia/Shanghai 日期：

```text
1046 次记录检查（523 条记录 x 2 轮）全部等于请求日期
```

### 结论

```text
payload_date_match: true（全部 12 轮）
evidence path: response.data.date + response.data.info[].first_limit_up_time
```

仅 URL 参数含日期不作为证据；本来源的日期绑定在响应内部成立。

## 9. Two-round Stability

每个日期两轮独立读取，逐项比较：

```text
canonical normalized rows: 完全相等（6/6 日期）
normalized_rows_sha256:    完全相等（6/6 日期）
payload date:              完全一致（6/6 日期）
invalid / duplicate / excluded counts: 全部 0
```

```text
2026-06-18: 91 行, sha 9418cb2e96e1...
2026-06-22: 132 行, sha 9f53834368ba...
2026-07-24: 40 行,  sha e15d3ce80ff9...
2026-07-27: 111 行, sha 8f35e1e814d0...
2026-07-30: 51 行,  sha 20e5cced2bd5...
2026-07-31: 98 行,  sha 9400f87f7663...
```

稳定性 = STABLE（6/6 日期）。

## 10. Pair A Results（ordinary_consecutive）

```text
previous: 2026-07-30, 51 行, 两轮稳定, 日期绑定 true
current:  2026-07-31, 98 行, 两轮稳定, 日期绑定 true
```

跨日：

```text
shared_identity: 10
previous_only: 41
current_only: 88
exact N->N+1: 10 / 10（全部）
same / skipped / decreased / other: 0 / 0 / 0 / 0
```

rates（denominator > 0 层）：

```text
N=1: 38 -> 6, rate=0.1579
N=2: 8  -> 1, rate=0.1250
N=3: 1  -> 1, rate=1.0000
N=4: 3  -> 1, rate=0.3333
N=8: 1  -> 1, rate=1.0000
```

## 11. Pair B Results（cross_weekend）

```text
previous: 2026-07-24, 40 行, 两轮稳定, 日期绑定 true
current:  2026-07-27, 111 行, 两轮稳定, 日期绑定 true
```

跨日：

```text
shared_identity: 8
previous_only: 32
current_only: 103
exact N->N+1: 8 / 8（全部）
same / skipped / decreased / other: 0 / 0 / 0 / 0
```

rates：

```text
N=1: 21 -> 3, rate=0.1429
N=2: 13 -> 2, rate=0.1538
N=3: 3  -> 1, rate=0.3333
N=4: 2  -> 2, rate=1.0000
N=9: 1  -> 0, rate=0.0000
```

## 12. Pair C Holiday Results（post_holiday）

```text
previous: 2026-06-18, 91 行, 两轮稳定, 日期绑定 true
current:  2026-06-22, 132 行, 两轮稳定, 日期绑定 true
```

跨日（跨端午假期：2026-06-19 非交易日）：

```text
shared_identity: 23
previous_only: 68
current_only: 109
exact N->N+1: 23 / 23（全部）
same / skipped / decreased / other: 0 / 0 / 0 / 0
```

rates：

```text
N=1: 64 -> 14, rate=0.2188
N=2: 17 -> 4,  rate=0.2353
N=3: 9  -> 4,  rate=0.4444
N=5: 1  -> 1,  rate=1.0000
```

本轮核心新增证据（observed fact）：替代来源在 Pair C 两日均有完整、
稳定、日期绑定的非空数据；东财该两日 EMPTY_UNEXPLAINED。

## 13. Eastmoney Cross-source Comparison

与已批准东财 Slice 2D 工件交叉核验（Pair A / Pair B 四日期；
eastmoney 行先按 universe 规则过滤 4/8/92/9 前缀）：

```text
2026-07-30: em=51, ths=51, shared=51, em_only=0, ths_only=0,
            lbc same=48, diff=3, jaccard=1.0000
2026-07-31: em=98, ths=98, shared=98, em_only=0, ths_only=0,
            lbc same=94, diff=4, jaccard=1.0000
2026-07-24: em=40, ths=40, shared=40, em_only=0, ths_only=0,
            lbc same=38, diff=2, jaccard=1.0000
2026-07-27: em=111, ths=111, shared=111, em_only=0, ths_only=0,
            lbc same=98, diff=13, jaccard=1.0000
```

identity 结论（observed fact）：四日期股票集合与东财完全一致
（jaccard 1.0，0 个 only 代码）。

lbc 结论（observed fact + inference）：300 个共享代码比较中
278 个一致（92.7%），22 个不一致，全部为同一模式：

```text
替代来源 M >= 2，东财 consecutive lbc = 1
（即同花顺 "N天M板" 中 N > M 的行：窗口计数 > 今日连续板数）
```

22 个不一致代码逐项列于 JSON `eastmoney_crosscheck.dates.*.
lbc_discrepancies`，不隐瞒来源差异。

```text
Pair A 分类: PARTIALLY_CONSISTENT
Pair B 分类: PARTIALLY_CONSISTENT
Pair C 分类: NOT_COMPARABLE（东财两日为空）
```

交叉验证不等于证明东财 payload 日期字段；东财 Blocker 3 维持 OPEN。

## 14. Cross-day lbc Verification

对 A / B / C 三组，previous 层 N 的晋级率：

```text
denominator_N = previous 中 lbc == N 的唯一股票数
numerator_N   = 上述股票中 current 存在且 lbc == N+1 的唯一股票数
rate_N        = round(numerator_N / denominator_N, 4)
```

结果（mechanical calculation，完整 normalized rows 已提交，
可离线独立复算）：

```text
Pair A: N=1..4,8 层全部给出 denominator/numerator/rate
Pair B: N=1..4,9 层全部给出
Pair C: N=1..3,5 层全部给出
```

共享股票（两日均在池内）全部呈现精确 N -> N+1（41/41），
无 same / skipped / decreased / other 迁移（observed fact）。

语义说明（inference，已列 caveat）：同花顺 high_days 为
"N 天内 M 板"窗口计数；N == M 的行与东财连板数一致，
N > M 的行在 22/22 个观测中对应东财连板数 1。
保守映射（N > M -> consecutive=1）与全部观测一致，
但超出本探针 4 个日期的普遍性未证明。

## 15. Blocker 2 Decision

```text
Blocker 2: candidate CLOSED pending independent review
```

条件核对：

```text
A/B/C 三组非空完整数据:           通过（51/98, 40/111, 91/132）
三组 previous/current 日期明确绑定: 通过（data.date + 逐记录时间戳）
每个日期两轮稳定:                  通过（6/6）
无非法行:                          通过（invalid=0 全部日期）
无重复代码:                        通过（duplicate=0 全部日期）
三组均存在 shared identity:        通过（10, 8, 23）
三组均存在 exact N->N+1 transition:通过（10, 8, 23）
denominator/numerator/rate 可复算:  通过（rows 已提交）
非 N->N+1 transition 已逐项列出:    通过（0 个，列为空）
无无法解释的系统性 lbc 冲突:        通过（N>M 差异已完全解释并逐项枚举）
```

caveats：

```text
1. lbc 语义差（N天M板 vs 连板数）已解释并枚举，但保守映射的普遍性未证明
2. Pair C 节假日证据仅来自替代来源（东财为空）
3. 正式关闭需独立复审（C）+ 来源采用决策；生产采用未授权
```

## 16. Blocker 3 Decision

```text
Blocker 3: OPEN（整体）
```

区分两个问题：

```text
A. 替代来源自身历史日期语义: VERIFIED
   - response.data.date == 请求日期（12/12 轮）
   - info[].first_limit_up_time 换算 Asia/Shanghai 日期 == 请求日期
     （1046/1046 记录检查）

B. 东财 getTopicZTPool 日期语义: 仍按既有证据（payload 无日期字段，
   本轮未取得直接针对东财 payload 日期绑定的新证据）
```

```text
replacement_or_crosscheck_path: candidate available pending
                                source adoption decision
```

不得仅因替代来源可靠就宣称东财 Blocker 3 已关闭。

## 17. Blocker 6 Boundary

```text
Blocker 6: PARTIALLY CLOSED（不变）
```

本轮未探测 legal zero。以下均不作为 legal-zero 证据：

```text
单次空数组 / 两次相同空数组 / HTTP 200 + 空数组
替代来源也为空 / 无涨停新闻 / 页面显示 0
```

## 18. Source Recommendation

```text
recommendation: ADOPT_FOR_FURTHER_DESIGN
production adoption authorized: false
architecture decision required: true
```

优势（observed fact）：

```text
零鉴权公开 JSON 端点（仅 UA + Referer，实测 200）
payload 自带日期字段，日期绑定在响应内部成立
逐记录交易时间戳，可独立验证日期
历史查询已验证至 7 周前（含节假日对）
股票集合与东财完全一致（jaccard 1.0）
两轮稳定性 6/6
覆盖东财空缺的 Pair C 节假日边界
跨日迁移 41/41 精确 N->N+1
```

缺陷（observed fact + inference）：

```text
lbc 为窗口板数（N天M板）而非连板数；N>M 行会高估连板数
  （22/300 观测，全部东财连板=1）
非官方内部端点：无 SLA、无许可证声明、可能随时变更
需要串行低频纪律；无生产速率保证
```

历史覆盖 / 日期绑定 / 字段完整性 / 稳定性 / 与东财一致性 /
访问限制 / 数据保留边界 / 维护成本 / 依赖影响：完整条目见 JSON
`source_recommendation`。

```text
维护成本: 中高（非官方端点 schema 可能漂移，采用前必须重验证）
依赖影响: 探针零新增依赖；生产适配器需直连 HTTP + 串行限流
```

## 19. Risks and Limitations

```text
1. 预算超支（证据缺陷）: 26 次 vs 20 次，原因与清单见 §6；
   其余纪律全部遵守
2. 非官方端点: 无 SLA / 无许可证声明，生产采用前需条款与稳定性评估
3. lbc 语义差: 22/300 不一致，全部为窗口计数 vs 连板数的单一模式，
   已解释并枚举；保守映射普遍性未证明
4. Pair C 无东财交叉: 节假日证据仅替代来源单边
5. 编码显示问题: 一次控制台输出中文显示为 GBK 乱码；
   原始响应字节验证为合法 UTF-8，无数据缺陷
6. 历史覆盖: 仅验证 6 个固定日期，通用保留窗口未探测
7. 单来源: 节假日边界仅一个替代来源 + 既有东财（Pair C 为空）
```

## 20. GO / CONDITIONAL GO / NO-GO

**CONDITIONAL GO**

- 替代来源可行性：通过（日期绑定 VERIFIED、两轮稳定、身份与东财一致）
- 节假日跨日证据：新增（Pair C 91->132，23 个共享身份全部精确晋级）
- Blocker 2：candidate CLOSED pending independent review
- Blocker 3：整体 OPEN（东财 payload 日期语义未获直接证据）
- Blocker 6：PARTIALLY CLOSED（未变）
- implementation_allowed：false

剩余阻断：

```text
- 东财 Blocker 3 仍 OPEN（本轮只验证替代来源）
- 替代来源生产采用未授权（需架构 + 条款评估）
- layered_promotion_rates 生产实现仍不允许
```

完成并推送后停止；未通知 C；未启动下一子阶段。
