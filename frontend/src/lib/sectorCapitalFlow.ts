export type CapitalFlowRowLike = {
  date?: string | null;
  main_net?: number | null;
};

export type SectorCapitalFlowSummary = {
  latestDate: string;
  latestMainNet: number;
  net5d: number;
  net20d: number;
  positiveDays20: number;
  sampleSize5: number;
  sampleSize20: number;
};

/** One trading day of representative-company main_net aggregate. */
export type SectorCapitalFlowPoint = {
  date: string;
  mainNet: number;
  contributingCompanies: number;
  expectedCompanies: number;
};

/** Full series for the sector representative capital flow chart. */
export type SectorCapitalFlowSeries = {
  status: "normal" | "partial" | "unavailable";
  points: SectorCapitalFlowPoint[];
  expectedCompanies: number;
  availableCompanies: number;
  latestDate: string | null;
  limitations: string[];
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isValidDate(value: unknown): value is string {
  return typeof value === "string" && DATE_RE.test(value.trim());
}

/**
 * Normalize and summarize representative-company main-capital flow rows.
 * Rows are ordered by date descending; malformed rows are ignored rather than
 * turning one upstream defect into a sector-level failure.
 */
export function summarizeSectorCapitalFlow(
  rows: readonly CapitalFlowRowLike[],
): SectorCapitalFlowSummary | null {
  const valid = rows
    .filter((row) => typeof row?.date === "string" && row.date.trim() && finiteNumber(row.main_net))
    .map((row) => ({ date: row.date!.trim(), mainNet: row.main_net! }))
    .sort((a, b) => b.date.localeCompare(a.date));

  if (valid.length === 0) return null;

  const recent20 = valid.slice(0, 20);
  const recent5 = recent20.slice(0, 5);
  const sum = (items: readonly { mainNet: number }[]) =>
    items.reduce((total, item) => total + item.mainNet, 0);

  return {
    latestDate: valid[0].date,
    latestMainNet: valid[0].mainNet,
    net5d: sum(recent5),
    net20d: sum(recent20),
    positiveDays20: recent20.filter((item) => item.mainNet > 0).length,
    sampleSize5: recent5.length,
    sampleSize20: recent20.length,
  };
}

/**
 * Aggregate per-company fund-flow rows into a daily main_net series for
 * representative companies only. Does not mutate inputs.
 *
 * - Missing companies are not zero-filled.
 * - Duplicate (code, date) keeps the first valid row only.
 * - Dates sorted ascending; keep latest maxPoints days; still ascending.
 */
export function buildSectorCapitalFlowSeries(
  expectedCodes: readonly string[],
  rowsByCode: Readonly<Record<string, readonly CapitalFlowRowLike[] | undefined>>,
  maxPoints = 60,
): SectorCapitalFlowSeries {
  // Dedupe expected codes, preserve first-seen order then sort for determinism of count only
  const seenCodes = new Set<string>();
  const codes: string[] = [];
  for (const raw of expectedCodes) {
    const code = String(raw ?? "").trim();
    if (!code || seenCodes.has(code)) continue;
    seenCodes.add(code);
    codes.push(code);
  }
  const expectedCompanies = codes.length;

  if (expectedCompanies === 0) {
    return {
      status: "unavailable",
      points: [],
      expectedCompanies: 0,
      availableCompanies: 0,
      latestDate: null,
      limitations: ["暂无代表公司"],
    };
  }

  // date → { sum, contributors: Set<code> }
  const byDate = new Map<string, { mainNet: number; contributors: Set<string> }>();
  const companiesWithAnyValid = new Set<string>();

  for (const code of codes) {
    const rows = rowsByCode[code];
    if (!rows || rows.length === 0) continue;

    // First valid row per date for this company
    const seenDates = new Set<string>();
    for (const row of rows) {
      if (!isValidDate(row?.date) || !finiteNumber(row?.main_net)) continue;
      const date = row.date!.trim();
      if (seenDates.has(date)) continue; // keep first only
      seenDates.add(date);
      companiesWithAnyValid.add(code);

      let bucket = byDate.get(date);
      if (!bucket) {
        bucket = { mainNet: 0, contributors: new Set() };
        byDate.set(date, bucket);
      }
      bucket.mainNet += row.main_net!;
      bucket.contributors.add(code);
    }
  }

  const availableCompanies = companiesWithAnyValid.size;
  const allDates = Array.from(byDate.keys()).sort((a, b) => a.localeCompare(b));
  // Keep latest maxPoints, still ascending
  const kept =
    allDates.length > maxPoints ? allDates.slice(allDates.length - maxPoints) : allDates;

  const points: SectorCapitalFlowPoint[] = kept.map((date) => {
    const bucket = byDate.get(date)!;
    return {
      date,
      mainNet: bucket.mainNet,
      contributingCompanies: bucket.contributors.size,
      expectedCompanies,
    };
  });

  if (points.length === 0) {
    return {
      status: "unavailable",
      points: [],
      expectedCompanies,
      availableCompanies: 0,
      latestDate: null,
      limitations: ["代表公司资金流暂不可用"],
    };
  }

  const limitations: string[] = [];
  let status: SectorCapitalFlowSeries["status"];
  if (availableCompanies < expectedCompanies) {
    status = "partial";
    limitations.push(`仅 ${availableCompanies}/${expectedCompanies} 家代表公司有可用资金流`);
  } else {
    status = "normal";
  }

  return {
    status,
    points,
    expectedCompanies,
    availableCompanies,
    latestDate: points[points.length - 1]?.date ?? null,
    limitations,
  };
}

export function formatCapitalFlowAmount(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const normalized = Object.is(value, -0) ? 0 : value;
  const sign = normalized > 0 ? "+" : "";
  const abs = Math.abs(normalized);

  if (abs >= 100_000_000) {
    return `${sign}${(normalized / 100_000_000).toFixed(abs >= 1_000_000_000 ? 1 : 2)}亿`;
  }
  if (abs >= 10_000) {
    return `${sign}${(normalized / 10_000).toFixed(abs >= 1_000_000 ? 1 : 2)}万`;
  }
  return `${sign}${normalized.toFixed(0)}`;
}
