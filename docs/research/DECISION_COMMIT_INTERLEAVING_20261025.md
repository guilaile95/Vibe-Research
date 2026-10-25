# Decision Commit lifecycle interleaving

Base: `8c141d554507b6228627271f1ef759485040591d`.

## Reproduced defect

The production runtime rechecked the Campaign in the service-owned
pre-write validator, but the Frozen Decision store acquired its own transaction
later. A controlled pause between these points allowed the legitimate Campaign
transition service to commit `ACTIVE -> CLOSED` in a different SQLite file.
Decision Commit subsequently inserted and returned success. The pre-fix
regression failed with `statuses_at_insert == ['CLOSED']` rather than `['ACTIVE']`.
Only the Campaign/Frozen lifecycle ordering is confirmed by this experiment;
other Thesis/evidence/account authority races are not proved or fixed here.

## Narrow correction

The production writer holds a Campaign SQLite `BEGIN IMMEDIATE` reservation
from the final Campaign check until the actual Frozen store call returns after
commit. A transition that wins first causes rejection; a Decision that wins
first completes before the transition. The Campaign reservation does not write
Campaign records and is always rolled back/released. This is not two-database
atomic commit, data migration, or distributed transaction machinery.

Order is runtime commit lock -> Campaign SQLite writer reservation -> Frozen
store mutex -> Frozen SQLite transaction. Source inspection found no production
Frozen store path which acquires the Campaign reservation in reverse order.
The optional challenge validator reads its ledger only. Network/provider work
and proposal construction remain outside the reservation.

Campaign connection initialization and reservation each retain the existing
10-second SQLite connection timeout; frozen store connections use 5 seconds.
These are bounded SQLite busy waits, not an absolute full-request deadline.
The existing in-process Frozen mutex has no new hard-timeout guarantee.
SQLite writer reservation serializes unrelated Campaign writers too, only for
the final local validation/insert span; it does not lock the earlier research
or model pipeline. Database aliases remain unsupported and fail schema checks.

## Tests and limits

`backend/tests/test_decision_commit_cross_database.py` exercises:
- Two real databases and an independent transition connection at the vulnerable gap.
- Transition-first rejection and decision-first ordering.
- Separate spawned process unable to bypass the reservation.
- Unrelated Campaign writer resumes after release, with no lost transition.
- Busy timeout fails closed without a Frozen row (shortened SQLite timeout in test).
- Downstream failure and a real SQLite INSERT abort leave no new records.
- Existing immutable replay after Campaign close does not acquire new write admission.
- Aliased incompatible database schemas reject without mutations.

Focused regression command: `python -m pytest backend/tests/test_decision_commit_cross_database.py backend/tests/test_campaign_store.py backend/tests/test_campaign_service.py backend/tests/test_decision_commit_runtime.py backend/tests/test_frozen_decision_service.py backend/tests/test_frozen_decision_store.py -q`.
All data is disposable and synthetic. No real portfolio, trade, model call,
production deployment, or crash/power-loss durability experiment was performed.
