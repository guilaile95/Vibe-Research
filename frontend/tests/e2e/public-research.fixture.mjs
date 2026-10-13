import path from 'node:path';
export const PUBLIC_RESEARCH_CLOCK = '2026-10-12T23:00:00Z';
export const PUBLIC_RESEARCH_SOURCES = Object.freeze(['public_polymarket', 'public_kalshi', 'tw_monthly_revenue', 'dram_spot_thermo', 'cn_commodity_futures', 'hiring_anchor_signal']);
// Vite resolves relative outDir against the adapter root, not process.cwd().
// Give both Vite and the static server the same absolute directory.
export function publicResearchPaths(frontend, output) {
  const directory = path.resolve(frontend, output);
  return { output: directory, dist: path.join(directory, 'page-dist') };
}
export function publicResearchStaticAllowed(method, pathname, search) {
  if (method !== 'GET') return false;
  if (pathname === '/') return ['', '?tab=events', '?tab=industry'].includes(search);
  return search === '' && (['/index.html', '/favicon.ico'].includes(pathname) || /^\/assets\/[\w.-]+\.(?:js|css)$/.test(pathname));
}
export function publicResearchSource(method, pathname, search) {
  if (method !== 'GET' || pathname !== '/api/public-research') return null;
  return PUBLIC_RESEARCH_SOURCES.find(source => search === `?source_id=${source}`) || null;
}
