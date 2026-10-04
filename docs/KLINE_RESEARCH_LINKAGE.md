# K-line research linkage

The StockData market tab keeps the existing SVG daily-price/indicator chart. After
prices load, **显示研究事件** explicitly requests two existing read-only APIs:

- `GET /research-events?security_code=…&date_from=…&date_to=…`, using the first and
  last dates of the same visible (up to 60 valid bars) chart
- `GET /evidence?subject_type=stock&subject_id=…&limit=100&offset=0`

No request is made merely by viewing prices. Hiding, switching stock or changing
the visible bar-date sequence aborts pending reads and clears the opt-in/results.
Each source can fail independently without deleting price bars or the other's
successful records. Retry clears old event results before re-reading. The existing
calendar API's 90-day historical and 180-day forward boundary still applies; an
unsupported window is disclosed as a failed event read, never silently clamped.

## Identity and time

Calendar `event_id` is a provider observation identity, not an Evidence ID.
`campaign_ids` associates active research on the same security, not a formal
binding of this event to a thesis or evidence record. Multiple Campaigns are
listed individually; navigation never silently selects the first. The existing
single-Campaign route remains unchanged.

Evidence uses its actual `id` to open `/evidence/:id`. Only undeleted `stock`
records whose `subject_id` exactly matches the displayed code can appear. No
Campaign relationship is inferred for a stock evidence record.

Calendar dates require `DATE_ONLY` semantics and a valid ISO date. Evidence
`source_date` is labelled **source date, not effective time**. Only valid date-only
values are placed; unsupported timestamp formats retain their raw text and are
left unplaced. The implementation does not convert a date into temporal authority,
look up missing dates, or use accessed/created/fetched timestamps as substitutes.

Exact dates map to their own visible bar. A date between visible bars maps to the
next available bar and shows both dates. Missing a bar does not prove a market
holiday, suspension or source gap. Dates outside the visible range are not
extrapolated. Unknown/invalid dates never map to today.

## Display and limitations

Records sharing a bar share one numbered marker to avoid overlapping targets.
The matching numbered text group is keyboard reachable and contains the individual
source IDs, true dates and navigation links. Text conveys the same information
without relying on colour or SVG interpretation. Unknown/out-of-window records
remain in a separately labelled text group.

Evidence reads stop after the first 100 API records. The API `total` and number
actually received disclose unread records. The combined view displays at most 100
eligible records, sorted by date then source-specific ID, and discloses omitted
record count. It is not a complete event history or an exhaustive chart search.
Calendar partial/unavailable status and API limitations remain visible. The view
makes no price-causality, investment recommendation or automatic evidence-writing
claim. No new provider, schema, financial computation or business write is added.

## Acceptance evidence

Pure tests cover strict dates, missing/outside bars, source/stock identity,
deletion, duplicate namespaces, window changes and multi-Campaign navigation.
API tests cover bounded GETs and cancellation. Synthetic browser fixtures exercise
1440/390px, explicit loading, keyboard marker/evidence navigation, unread record
counts, unknown/outside dates, unavailable indicators, partial calendar recovery,
old-stock response rejection, hide/reopen and zero business writes. These fixtures
do not establish live market-source completeness or trading effectiveness.
