# 当前下一任务

## 任务标题

对提交 **`5dec970`**（`feat: calculate executable add quantities`）做**受控端到端验收**。

## 约束

- **不修改**产品代码
- **不提交**验收脚本或临时文件
- 验收结束后工作区必须**干净**
- 不扩大到其它功能重构

## 验收清单

### 后端受控（validator / TestClient / 临时脚本均可，用完删除）

| 场景 | 输入 | 期望 |
|------|------|------|
| A | 持股 1500，现价 14.29，action=add，pct=10，模型 qty/amount 为 null | quantity=**100**，estimated_amount=**1429.00** |
| B | 同上，pct=20 | quantity=**300**，estimated_amount=**4287.00** |
| C | 持股 300，现价 14.29，add 10% | quantity=**null**，amount=**null**，含「不足一个100股交易单位」类限制文案 |
| 覆盖 | 模型 qty=999、amount=99999 | 仍覆盖为 A/B 对应后端计算值 |
| 文字 | 「建议买入100股」@100 | 通过 |
| 文字 | 「建议买入150股」@100 | 拒绝 |
| 文字 | 「预计需要1429元」 | 通过 |
| 文字 | 「预计需要5000元」 | 拒绝 |
| 文字 | 「相对当前持股加仓10%」 | 通过 |
| 文字 | 「使用账户10%资金买入」 | 拒绝 |

### 浏览器 / 前端受控展示

- 拦截或注入 `POST /api/portfolio/advice` 的 add=20% 结果，确认页面显示：
  - 相对当前持股加仓：20%
  - 建议买入数量：300股
  - 预计所需金额：约 ¥4,287.00
  - 执行前确认可用资金
- **不显示**：缺少「相对当前持股」语义的模糊「加仓20%」作为唯一标签、0股、¥0、账户资金/仓位 20% 话术
- quantity/amount 为 null 时：不显示 0股 / ¥0，展示不足 100 股限制说明

### 回归

```bash
cd backend
python -m pytest \
  tests/test_portfolio_advice_validator.py \
  tests/test_portfolio_advice_service.py \
  tests/test_portfolio_advice_api.py \
  -v

cd ../frontend
npm run build
```

允许的已知失败仅：

```text
tests/test_fixes.py::test_run_cli_stream_timeout
```

（若未纳入上述命令则不必强行打开。）

### 真实模型（可选补充）

- 可调用一次真实 `/api/portfolio/advice`
- 如实记录 action；若非 add，**不得**声称已完成真实 add 场景
- 以确定性 A/B/C 证明 add 计算链路

## 完成定义

- [ ] A/B/C 与覆盖、文字校验通过
- [ ] 浏览器展示检查通过
- [ ] 回归通过
- [ ] 临时脚本已删，工作区干净
- [ ] **无**新提交（验收轮次）

## 非目标

- 不改 Clash / 网络配置
- 不改 daily review / 行情抓取
- 不实现账户总资产或可卖数量接入
