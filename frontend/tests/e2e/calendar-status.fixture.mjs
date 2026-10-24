// Bounded synthetic maintenance metadata only. No inferred trading dates or I/O.
export function readCalendarStatusReply(method, path, search = "", status = "SUPPORTED") {
  if (method !== "GET" || path !== "/api/calendar-status" || search) return null;
  if (!["SUPPORTED", "EXPIRING"].includes(status)) throw new Error("Unsupported synthetic calendar state");
  const expiring = status === "EXPIRING";
  return { data: {
    calendar_id: "CN_A_SHARE",
    schema_version: "cn-a-share-trade-calendar-v0.1",
    as_of_date: expiring ? "2026-10-23" : "2026-09-01",
    supported_start: "2024-01-01",
    supported_end: "2026-12-31",
    days_until_coverage_end: expiring ? 69 : 121,
    status,
    future_dates_inferred: false,
    maintenance_required: expiring,
    source_policy: "SSE_SZSE_OFFICIAL_CONSENSUS",
    next_action: expiring ? "VERIFY_SSE_SZSE_OFFICIAL_CALENDAR" : "NONE",
  } };
}
