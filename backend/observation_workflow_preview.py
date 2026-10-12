"""Known synthetic fixtures through the same producers, in isolated memory only."""
import observation_workflow_store as store
import observation_workflows as obs
import observation_reminders as reminders


def preview():
    day = '2026-07-31'
    token = obs._preview_clock.set(obs.instant(f'{day}T01:25:10Z'))
    groups = {'watchlist': ['sh600000', 'sz000001'], 'yesterday_ladder': ['sh600000']}
    def quotes(_):
        return [{'symbol': code, 'price': value, 'open_price': value, 'previous_close': 10,
                 'provider_at': obs.stamp(obs._now()), 'source_id': 'SYNTHETIC_FIXTURE',
                 'is_limit_up': False, 'turnover_yuan': None}
                for code, value in [('sh600000', 10.4), ('sz000001', 9.8)]]
    try:
        with store.synthetic_database():
            obs._preview_clock.set(obs.instant(f'{day}T01:05:00Z'))
            reminders.run_task(day, 'premarket', lambda: {key: {'trade_date': day, 'status': 'COMPLETE', 'source_id': 'SYNTHETIC_FIXTURE', 'complete': True, 'source_total': 1, 'captured_at': obs.stamp(obs._now()), 'rows': [{'title': '纯合成事实条目', 'value': 1.2, 'unit': '%', 'published_at': obs.stamp(obs._now())}]} for key in reminders.PREMARKET_SECTIONS})
            for slot in obs.SLOTS:
                obs._preview_clock.set(obs.window(day, slot)[0])
                obs.capture_slot(day, slot, groups, quotes)
            obs._preview_clock.set(obs.instant(f'{day}T02:01:00Z'))
            obs.record_watch_quotes(groups, quotes([]))
            obs._preview_clock.set(obs.instant(f'{day}T02:02:10Z'))
            rows = quotes([])
            rows[0]['price'] = 10.7
            obs.record_watch_quotes(groups, rows)
            obs._preview_clock.set(obs.instant(f'{day}T07:40:00Z'))
            reminders.run_task(day, 'close_digest', lambda: {'trade_date': day, 'status': 'PARTIAL', 'facts': None, 'dragon_tiger': None, 'missing': ['dragon_tiger', 'qualified_close_facts'], 'observation_basis': 'CURRENT_STORED_CLOSE_RESEARCH', 'advice': None})
            obs._preview_clock.set(obs.instant(f'{day}T08:15:00Z'))
            def announcements(code, since):
                return {'status': 'COMPLETE', 'since': since, 'through': obs.stamp(obs._now()), 'has_more': False,
                        'items': [{'id': f'fixture:{code}', 'symbol': code, 'title': '合成公告：用于演示成功游标',
                                   'published_at': f'{day}T08:00:00Z', 'source_id': 'SYNTHETIC_FIXTURE'}]}
            reminders.run_task(day, 'watch_changes', announcements, ['sh600000', 'sz000001'])
            obs._preview_clock.set(obs.instant(f'{day}T08:30:00Z'))
            reminders.run_task(day, 'verification_due', lambda: {'status': 'COMPLETE', 'items': [], 'coverage': {'eligible_plans': 0, 'evaluated_plans': 0, 'has_more': False, 'order': 'latest_set_date_first', 'maximum': 20}})
            result = obs.view(day, include_due=False)
            result.update(synthetic=True, fixture_label='纯合成离线演示 · 不写真实归档 · 非实盘验收')
            return result
    finally:
        obs._preview_clock.reset(token)
