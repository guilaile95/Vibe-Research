import { useEffect, useRef, useState } from 'react';
import type { Subject } from '@/lib/companyResearch';
import { calculateReverseDcf, formatImpliedGrowth, requiredNumber, type Observation, type ReverseDcfInput, type ReverseDcfResult } from '@/lib/reverseDcf';

type Field = 'price' | 'fcff' | 'net_debt' | 'shares';
type Entry = Omit<Observation, 'value'> & { value: string };
const labels: Record<Field, string> = { price: '参考股价', fcff: '年度无杠杆自由现金流 FCFF', net_debt: '净债务（债务减现金，可为负）', shares: '稀释后股数' };
const units: Record<Field, string[]> = { price: ['currency_per_share'], fcff: ['currency', 'million_currency'], net_debt: ['currency', 'million_currency'], shares: ['shares', 'million_shares'] };
const unitLabels: Record<string, string> = { currency_per_share: '货币/股', currency: '货币元', million_currency: '百万货币元', shares: '股', million_shares: '百万股' };
const emptyEntries = (): Record<Field, Entry> => Object.fromEntries(Object.keys(labels).map(key => [key, { value: '', unit: units[key as Field][0], currency: key === 'shares' ? 'NONE' : '', source: '', as_of: '' }])) as Record<Field, Entry>;
const reasonLabels: Record<string, string> = { FINANCIAL_FIRM_INAPPLICABLE: '金融企业不适用此 FCFF 模型', INDUSTRY_UNKNOWN: '行业适用性未知', FCFF_BASIS_UNKNOWN: '未确认年度无杠杆 FCFF 口径', NONPOSITIVE_FCFF_INAPPLICABLE: '非正 FCFF 不适用', NONPOSITIVE_ENTERPRISE_VALUE_INAPPLICABLE: '隐含企业价值非正，不适用' };
function reasonLabel(code: string) {
  if (reasonLabels[code]) return reasonLabels[code];
  const [field, ...rest] = code.toLowerCase().split('_');
  const key = code.startsWith('NET_DEBT') ? 'net_debt' : field;
  const suffix = rest[rest.length - 1];
  return `${labels[key as Field] ?? key}：${suffix === 'stale' ? '输入已过期' : '日期晚于计算日'}`;
}

export function ReverseDcfCard({ subject }: { subject: Subject }) {
  const [entries, setEntries] = useState(emptyEntries);
  const [industry, setIndustry] = useState<ReverseDcfInput['industry']>('unknown');
  const [industrySource, setIndustrySource] = useState('');
  const [basis, setBasis] = useState<ReverseDcfInput['fcf_basis']>('unknown');
  const [assumptions, setAssumptions] = useState({ wacc: '', terminal_growth: '', years: '', growth_lower: '', growth_upper: '', sensitivity_wacc: '', rationale: '' });
  const [result, setResult] = useState<ReverseDcfResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const owner = useRef<AbortController | null>(null);
  const invalidate = () => { owner.current?.abort(); owner.current = null; setBusy(false); setResult(null); setError(''); };
  useEffect(() => () => owner.current?.abort(), []);
  useEffect(() => { invalidate(); setEntries(emptyEntries()); setIndustry('unknown'); setIndustrySource(''); setBasis('unknown'); }, [subject.market, subject.symbol]);
  const submit = async () => {
    if (owner.current) return;
    setError(''); setResult(null);
    const controller = new AbortController(); owner.current = controller; setBusy(true);
    try {
      const observations = Object.fromEntries(Object.entries(entries).map(([key, entry]) => [key, { ...entry, source: entry.source.trim(), value: requiredNumber(entry.value) }])) as Record<Field, Observation>;
      const input: ReverseDcfInput = { ...subject, ...observations, industry, industry_source: industrySource.trim(), fcf_basis: basis,
        assumptions: { wacc: requiredNumber(assumptions.wacc) / 100, terminal_growth: requiredNumber(assumptions.terminal_growth) / 100, years: requiredNumber(assumptions.years), growth_lower: requiredNumber(assumptions.growth_lower) / 100, growth_upper: requiredNumber(assumptions.growth_upper) / 100, sensitivity_wacc: assumptions.sensitivity_wacc.split(',').map(s => requiredNumber(s) / 100), rationale: assumptions.rationale.trim() } };
      const response = await calculateReverseDcf(input, controller.signal);
      if (owner.current === controller) setResult(response);
    } catch (e) { if (owner.current === controller) setError(e instanceof Error ? e.message : '反向 DCF 计算失败'); }
    finally { if (owner.current === controller) { owner.current = null; setBusy(false); } }
  };
  return <details className="my-3 rounded border border-border p-3" data-testid="reverse-dcf">
    <summary className="cursor-pointer font-semibold">反向 DCF · 价格隐含假设（不调用 AI）</summary>
    <p className="my-2 text-xs text-muted-foreground">模型求解使折现价值等于参考股价的恒定 FCFF 增长率，不是预测或买卖建议。年度期末现金流、股数与净债务固定；不替代完整估值。手动录入来源不代表事实已核验，不读取 AI 草稿或将净利润折算为现金流。</p>
    <form onSubmit={event => { event.preventDefault(); void submit(); }}>
      <fieldset className="space-y-3"><legend className="font-medium">手动录入的来源数据（未核验）</legend>
        <div className="grid gap-2 sm:grid-cols-2"><label>行业适用性<select aria-label="行业适用性" value={industry} onChange={e => { invalidate(); setIndustry(e.target.value as typeof industry); }} className="block w-full rounded border bg-background p-2"><option value="unknown">未知</option><option value="non_financial">已核对：非金融企业</option><option value="financial">金融企业（不适用）</option></select></label><label>行业分类来源<input required value={industrySource} onChange={e => { invalidate(); setIndustrySource(e.target.value); }} className="block w-full rounded border bg-background p-2" /></label></div>
        {(Object.keys(labels) as Field[]).map(key => <fieldset key={key} className="rounded border border-border p-2"><legend className="text-sm">{labels[key]}</legend><div className="grid gap-2 sm:grid-cols-3">
          <label className="text-xs">数值<input aria-label={`${labels[key]}数值`} required type="number" step="any" value={entries[key].value} onChange={e => { invalidate(); setEntries(v => ({ ...v, [key]: { ...v[key], value: e.target.value } })); }} className="block w-full rounded border bg-background p-2" /></label>
          <label className="text-xs">单位<select value={entries[key].unit} onChange={e => { invalidate(); setEntries(v => ({ ...v, [key]: { ...v[key], unit: e.target.value } })); }} className="block w-full rounded border bg-background p-2">{units[key].map(unit => <option key={unit} value={unit}>{unitLabels[unit]}</option>)}</select></label>
          {key !== 'shares' && <label className="text-xs">币种<select required value={entries[key].currency} onChange={e => { invalidate(); setEntries(v => ({ ...v, [key]: { ...v[key], currency: e.target.value } })); }} className="block w-full rounded border bg-background p-2"><option value="">请选择</option>{['CNY', 'HKD', 'USD'].map(c => <option key={c}>{c}</option>)}</select></label>}
          <label className="text-xs">来源（报告/页码或链接）<input required maxLength={300} value={entries[key].source} onChange={e => { invalidate(); setEntries(v => ({ ...v, [key]: { ...v[key], source: e.target.value } })); }} className="block w-full rounded border bg-background p-2" /></label>
          <label className="text-xs">数据截至日<input required type="date" value={entries[key].as_of} onChange={e => { invalidate(); setEntries(v => ({ ...v, [key]: { ...v[key], as_of: e.target.value } })); }} className="block w-full rounded border bg-background p-2" /></label>
        </div></fieldset>)}
        <label className="block text-xs">FCF 口径<select value={basis} onChange={e => { invalidate(); setBasis(e.target.value as typeof basis); }} className="ml-2 rounded border bg-background p-2"><option value="unknown">未知（不可计算）</option><option value="annual_unlevered_fcff">已核对年度无杠杆 FCFF（不是 FCFE 或净利润）</option></select></label>
        <p className="text-xs text-muted-foreground">同币种才能计算，无自动汇兑。过期门槛：股价 7 天、年度 FCFF 550 天、净债务与股数 180 天；未来日期拒绝计算。不同日期需自行核对可比性。</p>
      </fieldset>
      <fieldset className="my-3 grid gap-2 sm:grid-cols-2"><legend className="font-medium">手动模型假设（与来源数据分开）</legend>
        {([['wacc', 'WACC (%)，0 至 100'], ['terminal_growth', '永续增长率 (%)，大于 -100，最高 20'], ['years', '显式预测年数（整数 1–30）'], ['growth_lower', '求解增长率下界 (%)，大于 -100'], ['growth_upper', '求解增长率上界 (%)，最高 300'], ['sensitivity_wacc', '敏感性 WACC (%)，逗号分隔，最多 9 个'], ['rationale', '假设依据与局限']] as const).map(([key, label]) => <label key={key} className="text-xs">{label}<input required type={key === 'rationale' || key === 'sensitivity_wacc' ? 'text' : 'number'} step="any" value={assumptions[key]} onChange={e => { invalidate(); setAssumptions(v => ({ ...v, [key]: e.target.value })); }} className="block w-full rounded border bg-background p-2" /></label>)}
        <p className="text-xs text-muted-foreground sm:col-span-2">每个 WACC 必须大于永续增长率，否则拒绝，不会自动改写假设。敏感性逐项重新求解增长率，其他输入保持不变。超出求解边界显示无解，不外推。</p>
      </fieldset>
      <button disabled={busy} className="min-h-11 rounded border px-3 disabled:opacity-50">{busy ? '计算中…' : '计算价格隐含增长率'}</button>
      {busy && <button type="button" onClick={invalidate} className="ml-3 min-h-11">取消</button>}
    </form>
    {error && <p role="alert" className="my-2 text-sm text-destructive">{error}</p>}
    {result && <div className="mt-3 space-y-2 text-sm" data-testid="reverse-dcf-result">
      <p>计算日：{result.evaluated_on} · 价格隐含假设，不是预测</p>
      {result.status === 'SOLVED' ? <p>模型隐含年度 FCFF 增长率：<strong>{formatImpliedGrowth(result.implied_growth)}</strong></p> : <p>{result.status === 'NO_ROOT' ? '指定增长率边界内无解' : result.status === 'INAPPLICABLE' ? '不适用' : 'UNKNOWN：资料不足或已过期'}</p>}
      {result.reason_codes.map(code => <p key={code}>{reasonLabel(code)}</p>)}
      {result.sensitivity.length > 0 && <><p>WACC 敏感性（相同价格与其他假设）</p><ul>{result.sensitivity.map((row, i) => <li key={i}>WACC {formatImpliedGrowth(row.wacc)} → {row.status === 'SOLVED' ? formatImpliedGrowth(row.implied_growth) : '边界内无解'}</li>)}</ul><p className="text-xs text-muted-foreground">显示保留两位百分数；求解使用未舍入值。任何输入修改立即清除旧结果。</p></>}
    </div>}
  </details>;
}
