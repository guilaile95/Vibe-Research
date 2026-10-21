import { ApiError, request } from './api.ts';
import type { Subject } from './companyResearch.ts';
export type Observation = { value: number; unit: string; currency: string; source: string; as_of: string };
export type ReverseDcfInput = Subject & {
  industry: 'non_financial' | 'financial' | 'unknown'; industry_source: string;
  fcf_basis: 'annual_unlevered_fcff' | 'unknown';
  price: Observation; fcff: Observation; net_debt: Observation; shares: Observation;
  assumptions: { wacc: number; terminal_growth: number; years: number; growth_lower: number; growth_upper: number; sensitivity_wacc: number[]; rationale: string };
};
type Solution = { status: 'SOLVED' | 'NO_ROOT'; implied_growth: number | null; residual_ev: number | null };
export type ReverseDcfResult = {
  schema_version: 'reverse-dcf.v1'; classification: 'MODEL_IMPLIED_NOT_FORECAST'; input_verification: 'USER_ENTERED_UNVERIFIED';
  inputs: ReverseDcfInput; evaluated_on: string; status: Solution['status'] | 'UNKNOWN' | 'INAPPLICABLE';
  reason_codes: string[]; implied_growth: number | null; residual_ev: number | null;
  sensitivity: (Solution & { wacc: number })[];
};
export function requiredNumber(value: string): number {
  if (!value.trim() || !Number.isFinite(Number(value))) throw new Error('请填写全部有限数值；空白不会作为 0');
  return Number(value);
}
export function formatImpliedGrowth(value: number | null): string {
  return value !== null && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '不可计算';
}
export async function calculateReverseDcf(input: ReverseDcfInput, signal: AbortSignal): Promise<ReverseDcfResult> {
  let result: ReverseDcfResult;
  try { result = await request<ReverseDcfResult>('/company-research/reverse-dcf', 'POST', input, { signal }); }
  catch (error) {
    if (error instanceof ApiError && error.status === 422) {
      const issues = Array.isArray(error.detail) ? error.detail as { loc?: unknown[]; msg?: unknown }[] : [];
      const details = issues.slice(0, 5).map(issue => `${(issue.loc ?? []).filter(x => typeof x === 'string' && x !== 'body').join('.')}: ${typeof issue.msg === 'string' ? issue.msg : '输入无效'}`).join('；');
      throw new Error(`输入不满足模型约束，请检查单位、币种、来源及 WACC/永续增长率。${details}`);
    }
    throw error;
  }
  const validSolution = (v: Solution) => v.status === 'SOLVED' ? Number.isFinite(v.implied_growth) && v.implied_growth !== null && Number.isFinite(v.residual_ev) && v.residual_ev !== null : v.status === 'NO_ROOT' && v.implied_growth === null && v.residual_ev === null;
  // Bind the response to the exact manual inputs, including source/date/assumptions.
  const canonical = (v: unknown): string => JSON.stringify(v, function (_key, value) { return value && typeof value === 'object' && !Array.isArray(value) ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) : value; });
  if (result.schema_version !== 'reverse-dcf.v1' || result.classification !== 'MODEL_IMPLIED_NOT_FORECAST' || result.input_verification !== 'USER_ENTERED_UNVERIFIED' || canonical(result.inputs) !== canonical(input) || !Array.isArray(result.reason_codes) || !Array.isArray(result.sensitivity) || !['SOLVED', 'NO_ROOT', 'UNKNOWN', 'INAPPLICABLE'].includes(result.status)) throw new Error('反向 DCF 回执与输入不一致');
  if (['SOLVED', 'NO_ROOT'].includes(result.status)) {
    if (!validSolution(result as Solution) || result.sensitivity.length !== input.assumptions.sensitivity_wacc.length || result.sensitivity.some((v, i) => v.wacc !== input.assumptions.sensitivity_wacc[i] || !validSolution(v))) throw new Error('反向 DCF 数值回执无效');
  } else if (result.implied_growth !== null || result.sensitivity.length || !result.reason_codes.length) throw new Error('反向 DCF 不可用状态无效');
  return result;
}
