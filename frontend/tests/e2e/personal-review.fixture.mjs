import { predictionData } from './fixtures/adoption-api.mjs';

/** Only the read-only child mounted by the personal-review overview is mocked here. */
export function personalReviewChildRead(method, url, asOf) {
  if (method !== 'GET' || url.pathname !== '/api/prediction-journal' || url.search) return null;
  return { data: { ...predictionData([]), as_of: asOf } };
}
