# Native Intel Wave 4 behavior contract

Reference: [TrendRadar v6.10.0, pinned commit](https://github.com/sansan0/TrendRadar/tree/8ee26026ba6c11dec41a95fb3895a7162876caa1).
This is an independently written input/output specification, not imported source.
Audited: `config/config.yaml`, `config/timeline.yaml`, `trendradar/core/analyzer.py`,
`trendradar/core/frequency.py`, `trendradar/core/scheduler.py`,
`trendradar/report/generator.py`, `trendradar/__main__.py`, and
`mcp_server/tools/analytics.py` (deterministic operations only).

## Report behavior

- CURRENT selects the latest fetched list; DAILY includes the local calendar day's
  observations, including earlier lists. INCREMENTAL in the reference selects newly
  discovered titles/URLs (the first daily crawl counts everything as new).
- Vibe uses a persisted report baseline, not query time or a daily reset. New
  source/item pairs and changed observed titles, publication times or real ranks
  qualify. Re-observing the same state does not. This is an explicit deterministic
  extension. Only successful generation advances the baseline; preview is read-only.
  Baselines are isolated by report profile, mode, scope, Wave 2 rule fingerprint
  and native source/freshness policy. Initial or changed-policy baselines take
  the current source lists. Report previews never consume scheduled cursors.
- Keyword grouping assigns the first matching configured group. Required terms are
  AND, includes are OR, exclusions win. A positive group `max_count` overrides the
  report-wide display cap; zero inherits it, zero at both levels means no clipping.
  Vibe reuses Wave 2 title + summary matching (reference matches title only).
  Scope all retains nonmatching facts under Other; my_interests applies the
  existing rule or cached AI classifications. Wave 4 never requests classification;
  missing/error cached results produce PARTIAL and do not advance the cursor.
- Keyword groups sort by descending pre-clipping count, with configured position
  breaking ties; `sort_by_position_first` reverses these two priorities. Platform
  groups sort by descending displayed count. Source grouping preserves source IDs.
- Hotlist display ordering uses the reference's three normalized components:
  mean rank strength (rank 1 = 100, rank >= 10 = 10), capped observation frequency
  (10 observations = 100), and percentage of observations at/better than the
  highlight threshold, weighted 0.6 / 0.3 / 0.1. Ties use best rank, then frequency.
  This is display ordering, never a combined market rank or investment score.
- `rank_threshold` highlights real ranks and participates in the display ordering;
  it does not discard observations. RSS sorts newest publication first. The
  reference assigns RSS synthetic positions; Vibe deliberately keeps rank NULL.
- New badges distinguish RSS first local observation (NEWLY_OBSERVED, not newly
  published) from a source-specific first or confirmed return to a hotlist
  (NEW_ON_LIST). Source failure cannot establish a return to a list.
  CURRENT does not present a failed source's old list as current; DAILY can show
  its earlier observed facts with explicit latest_source_status (e.g. FAILED)
  and the existing Wave 1 rank state (UNKNOWN after failure, never OBSERVED).
  RSS exposes source status but keeps NO_RANK_SEMANTICS and NULL rank.
  Raw history is untouched. Re-enabled sources wait for a new observation.

CURRENT reads the active sources' latest completed runs, DAILY only the Shanghai
calendar day, and INCREMENTAL only each source/item's last valid observation at
or before its cursor plus observations after the cursor. Daily display-rank
statistics are separately SQL-aggregated, not loaded as raw history. Only an
incremental baseline older than the supported 30-day lookback is rejected.
Analytics supports 2–30 days plus the previous equal-length comparison window.
Observations and source runs stream through 5,000-row pages in one SQLite read
snapshot; each page is aggregated before the next. There is no total raw-row
rejection. Memory holds distinct aggregation keys/latest items, not all repeated
observations. No second analytics store is introduced.
All counts use the complete window. Only returned rank trajectories are capped
to the latest 10,000 matching observation IDs across trajectories, with explicit
total/returned/truncated metadata and a UI notice; cooccurrence samples remain
at most three items per pair. Reports and CURRENT_ELIGIBLE analytics share the
same source-enabled/deleted/re_enabled_at guard and existing freshness evaluator.
RAW_HISTORY retains pre-reenable observations unchanged.
The deterministic 432,000-observation regression verifies CURRENT, DAILY,
INCREMENTAL and exact 14/30-day aggregates, including the previous window.
Titles/ranks/publication timestamps come from observations; item URL/summary and
source labels use the existing current metadata, not a new snapshot authority.

## Timeline behavior (Asia/Shanghai)

Intervals include their start and exclude their end. Cross-midnight intervals are
supported. Day selection uses the current local weekday, including the early part
of a cross-midnight interval. Each weekday must have an explicit policy.

| Preset | Fetch | Report policy |
| --- | --- | --- |
| always_on | All day | INCREMENTAL every refresh |
| morning_evening | All day | CURRENT, except 20:00–22:00 DAILY once |
| office_hours | All day | Weekdays 09:00–11:00 CURRENT once, 13:00–15:00 CURRENT once, 17:00–19:00 DAILY once; weekends 08:00–23:00 INCREMENTAL; otherwise no scheduled report |
| night_owl | All day | 15:00–17:00 CURRENT once, 22:00–01:00 DAILY once; otherwise no scheduled report |
| custom (initial example) | All day | Weekdays 08:00–10:00 INCREMENTAL once; weekends 10:00–12:00 DAILY once; all days 19:00–21:00 DAILY once; 23:00–06:00 collection only |

Vibe uses its existing fetch loop, with native report generation replacing the
reference's push opportunity. No notification or AI stage is executed. The native
weekly segment configuration is saved in the existing Intel database. Invalid
times and overlapping intervals return 422 (the reference also offers last-wins;
Owner explicitly requires rejection here). A once-per-segment record is written
only after successful generation. Status exposes boundaries and next transition.
It also exposes the latest scheduled report's time, mode, count and source status.
The policy controls scheduled ticks; explicit manual/startup collection remains
the existing Vibe behavior. Disabling the policy retains the existing fetch loop.

## Statistical behavior

All results are observations, not Formal authority. Windows use local calendar
days; default trend/lifecycle window is seven days. Data basis is explicitly
CURRENT_ELIGIBLE or RAW_HISTORY. Missing collection coverage is reported separately
from observed zero counts. Counts deduplicate repeated fetches within a source/day.

| Capability | Reference calculation | Vibe mapping / explicit difference |
| --- | --- | --- |
| Similar | Case-sensitive Python SequenceMatcher title ratio; exclude identical title; threshold 0.6; descending similarity | Same heuristic, item provenance and NULL RSS ranks retained |
| Topic trend | Daily matching-title count per platform; final day versus first nonzero day; >10% rising, <-10% falling, otherwise stable | Same count unit and thresholds; also unique item/source/platform counts and bucket changes; Wave 2 groups or explicit query define topics |
| Rank timeline | Actual observed rank/time pairs | Separate source and item trajectories; no aggregate rank |
| Lifecycle | Compare last three bucket counts with first three: greater => 上升期; less than half => 衰退期; otherwise latest three contain overall maximum => 爆发期; else 稳定期 | Same ordered rules; no matching history => NOT_EVALUATED; input counts and comparison exposed |
| Lifecycle type | At most two active days and peak > twice nonzero-day mean => 昙花一现; else active days >=60% of window => 持续热点; else 周期性热点 | Same rules, including the mathematically unreachable short-spike condition; no invented replacement |
| Viral | Today/yesterday >=3 (inclusive); yesterday zero requires today >=5. High alert when ratio >6, else medium | Same thresholds for explicit topics/groups; absent coverage is UNKNOWN, not an invented zero baseline. Reference time_window parameter does not alter its day comparison |
| Prediction | Prior three days plus today; latest/previous growth >30% (strict). Two populated buckets strength 0.6; >=3 nondecreasing buckets 0.9, otherwise 0.7; default threshold 0.7 | Preserve actual nonzero-day reference sequence and expose it alongside full buckets; never label strength a probability. No forecast horizon is inferred from the unused reference lookahead parameter |
| Platform comparison | Sum daily distinct source titles, matching topic count, distinct titles, topic coverage percentage. Activity divides news count by active days; reference update/hour counts derive from snapshot filenames | Individual Hotlist sources + individual RSS sources + RSS grouped aggregate rows (native superset). Aggregate rows must not be summed again with individual rows. Native successful source-run counts replace filename-derived update frequency (not updates/hour); add first-observed item counts, ranked visibility, observed-day coverage and previous equal-day-window change. Today is partial and explicitly labelled; RSS never enters rank metrics |
| Co-occurrence | Pairs of whitespace/punctuation-extracted title tokens per source/title, default minimum 3 | Owner-directed Wave 2 group pairs, counted per Native Intel item identity, with samples. Hotlist identities are source-qualified: the same story on Weibo and Baidu can count separately. No story-level cross-source deduplication is claimed. Multi-group matches are retained; no causal claim |

The reference token extractor does not provide Chinese semantic segmentation and
may count repeated tokens. Vibe's existing configured keyword groups are the sole
group authority. No embeddings, LLM, second fact store, copied GPL implementation,
or new scheduler daemon is introduced. Wave 5/6/7 remain deferred.
