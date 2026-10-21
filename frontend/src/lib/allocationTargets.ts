import { get, put } from './api.ts';
export interface AllocationInput {
  expected_version: number; effective_date: string; market: 'CN'; currency: 'CNY';
  basis: 'CONFIRMED_ACCOUNT_ASSETS'; coverage: 'PARTIAL' | 'FULL'; targets: Record<string, number>;
}
export interface AllocationVersion { version: number; created_at: string; input: AllocationInput }
export interface AllocationComparison {
  latest_version: number; active_version: number | null; versions: AllocationVersion[];
  status: string; as_of: string; valid_until: string; denominator: number | null; reasons: string[]; limitations: string[];
  coverage: { holding_count: number; priced_count: number; unknown_industry_count: number };
  rows: { key: string; target_pct: number | null; actual_pct: number | null; drift_pp: number | null; reason: string | null }[];
}
export const readAllocation = (signal?: AbortSignal) => get<AllocationComparison>('/portfolio/allocation-targets', { signal });
export const saveAllocation = (input: AllocationInput) => put<AllocationVersion>('/portfolio/allocation-targets', input);
export { parseTargets } from './allocationTargetInput.ts';
