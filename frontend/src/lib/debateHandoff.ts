/** A-share code grammar only; this does not certify a listed security. */
export function stockDebateHref(code: unknown): string | null {
  return typeof code === "string" && /^[0-9]{6}$/.test(code) ? "/debate?code=" + code : null;
}
export function debateCodeFromSearch(search: string): string {
  const values = new URLSearchParams(search).getAll("code");
  return values.length === 1 && stockDebateHref(values[0]) ? values[0] : "";
}

/** Use only the returned A-share result currently displayed by StockData. */
export function stockDebateHrefForResult(
  activeCode: unknown, valuation: { code?: unknown } | null, globalStock: unknown,
): string | null {
  if (globalStock || !valuation || valuation.code !== activeCode) return null;
  return stockDebateHref(activeCode);
}
