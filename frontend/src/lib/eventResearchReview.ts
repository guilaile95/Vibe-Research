import type { EvidenceRecord, ResearchEventCalendarEvent } from './api/types.ts';

export type ReviewEvent = ResearchEventCalendarEvent & { observation_hash?: string; observation_receipt?: string };
export interface EventReview {
  id: string; campaign_id: string; thesis_id: string; thesis_revision: number;
  expectation: string; observation: ResearchEventCalendarEvent; observation_hash: string;
  version: number; status: 'review_required' | 'support' | 'refute' | 'insufficient';
  judgment: null | { reason: string; reviewed_at: string; evidence: EvidenceRecord[] };
}
export interface ReviewContext {
  thesis: { id: string; title: string; current_revision: number };
  evidence: EvidenceRecord[]; reviews: EventReview[];
}
export const reviewStatus = { review_required: '待复核', support: '支持预期', refute: '反驳预期', insufficient: '证据不足' };
export function applyReviewResponse(request: number, current: number, active: boolean): boolean {
  return active && request === current;
}
export async function reviewRequest<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`/api/research-events/reviews${path}`, {
    method: payload === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '复核请求失败，请刷新后重试');
  return body.data as T;
}
