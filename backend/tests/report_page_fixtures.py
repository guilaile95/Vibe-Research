"""Known-complete synthetic windows for projection-only regression tests."""
def complete_report_window(rows, requested_pages=1):
    return {'rows': rows, 'status': 'normal', 'source_coverage': {
        'scope': 'provider_report_page_window', 'requested_pages': requested_pages,
        'reported_total_pages': 1 if rows else 0, 'expected_pages': 1,
        'attempted_pages': 1, 'received_pages': 1, 'returned_rows': len(rows),
        'reason': None, 'historical_complete': False,
    }}
