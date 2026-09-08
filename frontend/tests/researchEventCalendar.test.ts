import assert from "node:assert/strict";
import test from "node:test";

import type { ResearchEventCalendarEvent } from "../src/lib/api/types.ts";
import {
  eventNavigationHref,
  filterResearchEvents,
  formatResearchEventDate,
  groupResearchEvents,
  researchEventGroupKey,
  researchEventStateLabel,
  researchEventTypeLabel,
  shouldApplyResearchEventResponse,
} from "../src/lib/researchEventCalendar.ts";

function event(overrides: Partial<ResearchEventCalendarEvent> = {}): ResearchEventCalendarEvent {
  return {
    event_id: "event-a",
    security_code: "600001",
    security_name: null,
    campaign_ids: ["campaign_" + "a".repeat(32)],
    event_type: "PERIODIC_REPORT",
    event_date: "2026-09-12",
    date_semantics: "DATE_ONLY",
    state: "EXPECTED",
    title: "预计披露日（不是公司保证日期）",
    details: {},
    source: "eastmoney:RPT_PUBLIC_BS_APPOIN",
    source_record_identity: "record-a",
    fetched_at: "2026-09-09T00:00:00.000000Z",
    limitations: ["NO_EXPLICIT_EVENT_CATALYST_LINK"],
    ...overrides,
  };
}

test("normal upcoming events group into the next-seven-days bucket", () => {
  assert.equal(researchEventGroupKey("2026-09-12", "2026-09-09"), "NEXT_7_DAYS");
  assert.equal(groupResearchEvents([event()], "2026-09-09")[0].events.length, 1);
});

test("recent confirmed events are separated from upcoming events", () => {
  const groups = groupResearchEvents([event({ event_id: "past", event_date: "2026-09-08", state: "CONFIRMED" })], "2026-09-09");
  assert.equal(groups[0].key, "RECENT");
  assert.equal(researchEventStateLabel("CONFIRMED"), "已观察");
});

test("no active campaign is represented by an empty event projection", () => {
  assert.deepEqual(groupResearchEvents([], "2026-09-09"), []);
});

test("active campaign with no event is not turned into a fake event", () => {
  const groups = groupResearchEvents([], "2026-09-09");
  assert.equal(groups.length, 0);
});

test("partial source event remains renderable", () => {
  const rows = [event({ event_id: "partial", state: "EXPECTED" })];
  assert.equal(filterResearchEvents(rows, { securityCode: "", eventType: "ALL", state: "ALL" }).length, 1);
});

test("unavailable and provider error wording stays distinct", () => {
  assert.equal(researchEventStateLabel("UNAVAILABLE"), "不可用");
  assert.equal(researchEventStateLabel("ERROR"), "读取失败");
  assert.equal(researchEventStateLabel("NO_RECORD"), "无记录");
});

test("delayed disclosure wording does not claim a violation", () => {
  assert.equal(researchEventStateLabel("DELAYED_SIGNAL"), "预约日已过，尚未见披露");
});

test("dividend state is displayed as provider observation vocabulary", () => {
  assert.equal(researchEventStateLabel("UPCOMING"), "即将发生");
  assert.equal(researchEventTypeLabel("DIVIDEND_BONUS"), "分红送转");
});

test("lockup state is displayed separately from price impact", () => {
  assert.equal(researchEventStateLabel("HISTORY"), "历史记录");
  assert.equal(researchEventTypeLabel("LOCKUP_EXPIRY"), "限售解禁");
});

test("filters can narrow by stock, event type, and state", () => {
  const rows = [
    event(),
    event({ event_id: "announcement", security_code: "000002", event_type: "ANNOUNCEMENT", state: "CONFIRMED" }),
  ];
  assert.equal(filterResearchEvents(rows, { securityCode: "000002", eventType: "ANNOUNCEMENT", state: "CONFIRMED" }).length, 1);
  assert.equal(filterResearchEvents(rows, { securityCode: "", eventType: "PERIODIC_REPORT", state: "ALL" }).length, 1);
});

test("event row navigation prefers Decision Inbox campaign context", () => {
  assert.equal(eventNavigationHref(event()), `/decision-inbox#campaign-${"campaign_" + "a".repeat(32)}`);
});

test("event row navigation falls back to StockData without a campaign", () => {
  assert.equal(eventNavigationHref(event({ campaign_ids: [] })), "/stock-data?code=600001");
});

test("refresh stale-response guard accepts only the latest generation", () => {
  assert.equal(shouldApplyResearchEventResponse(4, 4), true);
  assert.equal(shouldApplyResearchEventResponse(3, 4), false);
});

test("date-only and unknown dates remain explicit", () => {
  assert.equal(formatResearchEventDate("2026-09-12"), "2026-09-12");
  assert.equal(formatResearchEventDate(null), "日期未知");
  assert.equal(groupResearchEvents([event({ event_id: "unknown", event_date: null, date_semantics: "UNKNOWN" })], "2026-09-09")[0].key, "UNKNOWN");
});
