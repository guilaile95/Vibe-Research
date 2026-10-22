/** Same-origin in-app path only. Reject protocol-relative, backslash, and absolute URLs. */
export function safeInternalReturnTo(value: string | null, fallback: string): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return fallback;
  }
  try {
    const origin = typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : "http://localhost";
    const parsed = new URL(value, origin);
    if (parsed.origin !== origin) return fallback;
    // Validate decoded path spellings too, but do not decode the query: nested
    // return_to values legitimately contain encoded slashes and query strings.
    let path = parsed.pathname;
    for (let pass = 0; pass < 8; pass++) {
      if (path.startsWith("//") || /[\\\u0000-\u0020\u007f]/.test(path)) return fallback;
      const decoded = decodeURIComponent(path);
      if (decoded === path) break;
      if (pass === 7) return fallback;
      path = decoded;
    }
    if (/[\u0000-\u0020\u007f]/.test(value)) return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}
