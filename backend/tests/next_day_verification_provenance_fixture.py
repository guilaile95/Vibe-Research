"""Real service output with synthetic qualified prior/current observations only."""
from datetime import datetime
import next_day_verification as service
from test_next_day_verification import seed


def contracts(monkeypatch):
    day, target = "2026-07-31", "2026-08-03"
    clock = [datetime.fromisoformat("2026-07-31T08:00:00+00:00")]
    monkeypatch.setattr(service, "_now", lambda: clock[0])
    for index, date in enumerate(service._history_days(day)[-14:]):
        seed(monkeypatch, day=date, count=20 + index * 2, rate=0.25)
    pending = service.replace_plan(day, service.SavePlan(revision=0, items=[
        service.Condition(metric="limit_up_count", direction="up", reason="Synthetic count condition"),
        service.Condition(metric="failed_board_rate", direction="flat", reason="Synthetic ratio condition"),
    ]))
    clock[0] = datetime.fromisoformat("2026-08-03T08:00:00+00:00")
    seed(monkeypatch, day=target, count=56, rate=0.28)
    verified = service.view(day)
    seed(monkeypatch, day=target, count=36, rate=0.4)
    corrected = service.view(day)
    return {"pending": pending, "verified": verified, "corrected": corrected}
