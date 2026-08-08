import test from "node:test";
import assert from "node:assert/strict";
import {
  buildSectorCapitalFlowSeries,
  formatCapitalFlowAmount,
  summarizeSectorCapitalFlow,
} from "../src/lib/sectorCapitalFlow.ts";

test("summarizeSectorCapitalFlow sorts rows and calculates rolling totals", () => {
  const rows = [
    { date: "2026-07-28", main_net: -20 },
    { date: "2026-07-30", main_net: 100 },
    { date: "2026-07-29", main_net: 50 },
    { date: "", main_net: 999 },
    { date: "2026-07-27", main_net: Number.NaN },
  ];

  assert.deepEqual(summarizeSectorCapitalFlow(rows), {
    latestDate: "2026-07-30",
    latestMainNet: 100,
    net5d: 130,
    net20d: 130,
    positiveDays20: 2,
    sampleSize5: 3,
    sampleSize20: 3,
  });
});

test("summarizeSectorCapitalFlow limits windows to 5 and 20 valid sessions", () => {
  const rows = Array.from({ length: 25 }, (_, index) => ({
    date: `2026-07-${String(30 - index).padStart(2, "0")}`,
    main_net: index + 1,
  }));

  const summary = summarizeSectorCapitalFlow(rows);
  assert.ok(summary);
  assert.equal(summary.sampleSize5, 5);
  assert.equal(summary.sampleSize20, 20);
  assert.equal(summary.net5d, 15);
  assert.equal(summary.net20d, 210);
  assert.equal(summary.positiveDays20, 20);
});

test("summarizeSectorCapitalFlow returns null without valid rows", () => {
  assert.equal(summarizeSectorCapitalFlow([]), null);
  assert.equal(
    summarizeSectorCapitalFlow([
      { date: null, main_net: 1 },
      { date: "2026-07-30", main_net: null },
    ]),
    null,
  );
});

test("formatCapitalFlowAmount uses compact signed Chinese units", () => {
  assert.equal(formatCapitalFlowAmount(125_000_000), "+1.25亿");
  assert.equal(formatCapitalFlowAmount(-20_000_000), "-2000.0万");
  assert.equal(formatCapitalFlowAmount(25_000), "+2.50万");
  assert.equal(formatCapitalFlowAmount(0), "0");
  assert.equal(formatCapitalFlowAmount(Number.NaN), "—");
});

// ── buildSectorCapitalFlowSeries ──────────────────────────────────────────

test("buildSectorCapitalFlowSeries: two companies same day sum main_net", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001", "600519"],
    {
      "000001": [{ date: "2026-07-30", main_net: 100 }],
      "600519": [{ date: "2026-07-30", main_net: 50 }],
    },
  );
  assert.equal(series.points.length, 1);
  assert.equal(series.points[0].date, "2026-07-30");
  assert.equal(series.points[0].mainNet, 150);
  assert.equal(series.points[0].contributingCompanies, 2);
  assert.equal(series.points[0].expectedCompanies, 2);
  assert.equal(series.status, "normal");
});

test("buildSectorCapitalFlowSeries: dates ascending", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001"],
    {
      "000001": [
        { date: "2026-07-30", main_net: 3 },
        { date: "2026-07-28", main_net: 1 },
        { date: "2026-07-29", main_net: 2 },
      ],
    },
  );
  assert.deepEqual(
    series.points.map((p) => p.date),
    ["2026-07-28", "2026-07-29", "2026-07-30"],
  );
  assert.deepEqual(
    series.points.map((p) => p.mainNet),
    [1, 2, 3],
  );
});

test("buildSectorCapitalFlowSeries: missing company not zero-filled", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001", "600519"],
    {
      "000001": [
        { date: "2026-07-29", main_net: 10 },
        { date: "2026-07-30", main_net: 20 },
      ],
      // 600519 only on 07-30
      "600519": [{ date: "2026-07-30", main_net: 5 }],
    },
  );
  const d29 = series.points.find((p) => p.date === "2026-07-29");
  const d30 = series.points.find((p) => p.date === "2026-07-30");
  assert.ok(d29 && d30);
  assert.equal(d29.mainNet, 10);
  assert.equal(d29.contributingCompanies, 1);
  assert.equal(d30.mainNet, 25);
  assert.equal(d30.contributingCompanies, 2);
});

test("buildSectorCapitalFlowSeries: contributingCompanies correct", () => {
  const series = buildSectorCapitalFlowSeries(
    ["A", "B", "C"],
    {
      A: [{ date: "2026-07-30", main_net: 1 }],
      B: [{ date: "2026-07-30", main_net: 2 }],
      // C missing
    },
  );
  assert.equal(series.points[0].contributingCompanies, 2);
  assert.equal(series.points[0].expectedCompanies, 3);
});

test("buildSectorCapitalFlowSeries: one company no data → partial", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001", "600519"],
    {
      "000001": [{ date: "2026-07-30", main_net: 10 }],
      "600519": [],
    },
  );
  assert.equal(series.status, "partial");
  assert.equal(series.availableCompanies, 1);
  assert.equal(series.expectedCompanies, 2);
  assert.ok(series.limitations.some((l) => l.includes("仅 1/2 家代表公司有可用资金流")));
});

test("buildSectorCapitalFlowSeries: all companies have data → normal", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001", "600519"],
    {
      "000001": [{ date: "2026-07-30", main_net: 1 }],
      "600519": [{ date: "2026-07-29", main_net: 2 }],
    },
  );
  assert.equal(series.status, "normal");
  assert.equal(series.availableCompanies, 2);
  assert.deepEqual(series.limitations, []);
});

test("buildSectorCapitalFlowSeries: all no data → unavailable", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001", "600519"],
    {
      "000001": [{ date: null, main_net: 1 }],
      "600519": [],
    },
  );
  assert.equal(series.status, "unavailable");
  assert.equal(series.points.length, 0);
  assert.ok(series.limitations.includes("代表公司资金流暂不可用"));
});

test("buildSectorCapitalFlowSeries: no expected companies", () => {
  const series = buildSectorCapitalFlowSeries([], {});
  assert.equal(series.status, "unavailable");
  assert.ok(series.limitations.includes("暂无代表公司"));
});

test("buildSectorCapitalFlowSeries: filters illegal date / null / NaN / Infinity / string numbers", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001"],
    {
      "000001": [
        { date: "2026-07-30", main_net: 10 },
        { date: "07-30", main_net: 99 },
        { date: "2026-07-29", main_net: null },
        { date: "2026-07-28", main_net: Number.NaN },
        { date: "2026-07-27", main_net: Number.POSITIVE_INFINITY },
        { date: "2026-07-26", main_net: "5" as unknown as number },
        { date: "", main_net: 1 },
      ],
    },
  );
  assert.equal(series.points.length, 1);
  assert.equal(series.points[0].date, "2026-07-30");
  assert.equal(series.points[0].mainNet, 10);
});

test("buildSectorCapitalFlowSeries: duplicate same company same date keeps first only", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001"],
    {
      "000001": [
        { date: "2026-07-30", main_net: 10 },
        { date: "2026-07-30", main_net: 999 }, // ignored
      ],
    },
  );
  assert.equal(series.points[0].mainNet, 10);
});

test("buildSectorCapitalFlowSeries: max 60 latest points stay ascending", () => {
  const rows = Array.from({ length: 80 }, (_, i) => {
    const day = i + 1;
    const month = day <= 31 ? "01" : "02";
    const d = day <= 31 ? day : day - 31;
    return {
      date: `2026-${month}-${String(d).padStart(2, "0")}`,
      main_net: i,
    };
  });
  // Use sequential ISO-like dates via simple counter
  const rows2 = Array.from({ length: 80 }, (_, i) => ({
    date: `2026-04-${String((i % 28) + 1).padStart(2, "0")}`, // will collide — use unique
    main_net: i,
  }));
  // Ensure unique dates with offset encoding
  const uniqueRows = Array.from({ length: 80 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 0, 1 + i));
    const iso = d.toISOString().slice(0, 10);
    return { date: iso, main_net: i };
  });

  const series = buildSectorCapitalFlowSeries(["000001"], { "000001": uniqueRows }, 60);
  assert.equal(series.points.length, 60);
  // ascending
  for (let i = 1; i < series.points.length; i++) {
    assert.ok(series.points[i].date > series.points[i - 1].date);
  }
  // latest 60 of 80: indices 20..79
  assert.equal(series.points[0].mainNet, 20);
  assert.equal(series.points[59].mainNet, 79);
  assert.equal(series.latestDate, uniqueRows[79].date);
  void rows;
  void rows2;
});

test("buildSectorCapitalFlowSeries: expectedCodes deduped", () => {
  const series = buildSectorCapitalFlowSeries(
    ["000001", "000001", "600519"],
    {
      "000001": [{ date: "2026-07-30", main_net: 1 }],
      "600519": [{ date: "2026-07-30", main_net: 2 }],
    },
  );
  assert.equal(series.expectedCompanies, 2);
  assert.equal(series.points[0].expectedCompanies, 2);
  assert.equal(series.points[0].mainNet, 3);
});

test("buildSectorCapitalFlowSeries: does not mutate inputs", () => {
  const codes = ["000001", "600519"];
  const rowA = [{ date: "2026-07-30", main_net: 1 }];
  const rowB = [{ date: "2026-07-30", main_net: 2 }];
  const rowsByCode = { "000001": rowA, "600519": rowB };
  const codesSnap = [...codes];
  const aSnap = JSON.stringify(rowA);
  const bSnap = JSON.stringify(rowB);

  buildSectorCapitalFlowSeries(codes, rowsByCode, 60);

  assert.deepEqual(codes, codesSnap);
  assert.equal(JSON.stringify(rowA), aSnap);
  assert.equal(JSON.stringify(rowB), bSnap);
});

test("positive/negative amounts reuse formatCapitalFlowAmount", () => {
  // Contract: chart must use this formatter — assert known outputs for tooltip semantics
  assert.equal(formatCapitalFlowAmount(1_000_000), "+100.0万");
  assert.equal(formatCapitalFlowAmount(-1_000_000), "-100.0万");
  assert.equal(formatCapitalFlowAmount(25_000), "+2.50万");
  const series = buildSectorCapitalFlowSeries(
    ["000001"],
    {
      "000001": [
        { date: "2026-07-28", main_net: 1_000_000 },
        { date: "2026-07-29", main_net: -500_000 },
        { date: "2026-07-30", main_net: 0 },
      ],
    },
  );
  assert.equal(formatCapitalFlowAmount(series.points[0].mainNet), "+100.0万");
  assert.equal(formatCapitalFlowAmount(series.points[1].mainNet), "-50.00万");
  assert.equal(formatCapitalFlowAmount(series.points[2].mainNet), "0");
});
