// Explicit unavailable sources actually mounted by CandidateWorkspace and
// StockData overview. Unknown requests must fail, not silently become optional.
export function isExpectedSoakUnavailable(method, path, search = '') {
  if (method !== 'GET') return false;
  const query = [...new URLSearchParams(search)].sort(([a], [b]) => a.localeCompare(b));
  const exact = expected => JSON.stringify(query) === JSON.stringify(Object.entries(expected).sort(([a], [b]) => a.localeCompare(b)));
  if (path === '/api/position/derived') return exact({});
  if (['/api/stock-relative-context', '/api/stock-valuation-context', '/api/valuation', '/api/blocks', '/api/hot-concepts'].includes(path)) return exact({ code: '600519' });
  if (path === '/api/market/top-risk') return exact({ code: '600519', days: '120' });
  // Calendar initially mounts with no date filter; this workload never edits it.
  if (path === '/api/research-events') return exact({ security_code: '600519' });
  return false;
}

export function isExpectedSoakConsoleError(row, baseURL) {
  if (!/^Failed to load resource: the server responded with a status of 503 \(/.test(row.text)) return false;
  try {
    const url = new URL(row.url);
    return url.origin === baseURL && isExpectedSoakUnavailable('GET', url.pathname, url.search);
  } catch { return false; }
}
