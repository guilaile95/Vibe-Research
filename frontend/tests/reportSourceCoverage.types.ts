import type { api } from "../src/lib/api.ts";
import type { Report, ReportListResult, ReportSourceCoverage, ReportSourceStatus, SectorReportsDiscoveryResult } from "../src/lib/api/types.ts";

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;

export type LegacyReportsRemainArray = Assert<Equal<Awaited<ReturnType<typeof api.reports>>, Report[]>>;
export type CoverageMethodHasEnvelope = Assert<Equal<Awaited<ReturnType<typeof api.reportsWithCoverage>>, ReportListResult>>;
export type HistoryCannotBeComplete = Assert<Equal<ReportSourceCoverage["historical_complete"], false>>;
export type WindowScopeOnly = Assert<Equal<ReportSourceCoverage["scope"], "provider_report_page_window">>;
export type NullableProviderTotal = Assert<Equal<ReportSourceCoverage["reported_total_pages"], number | null>>;
export type NullableExpectedWindow = Assert<Equal<ReportSourceCoverage["expected_pages"], number | null>>;
export type ExplicitMissingCoverage = Assert<Equal<ReportListResult["source_coverage"], ReportSourceCoverage | null>>;
export type DiscoveryLegacyStatusAllowed = Assert<Equal<SectorReportsDiscoveryResult["status"], ReportSourceStatus | undefined>>;

// @ts-expect-error Provider pagination must never be typed as full-history proof.
export const invalidHistory: ReportSourceCoverage["historical_complete"] = true;
// @ts-expect-error Report status cannot reuse an unrelated healthy/success enum.
export const invalidStatus: ReportSourceStatus = "success";
