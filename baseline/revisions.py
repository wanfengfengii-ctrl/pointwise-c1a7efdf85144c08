from baseline.coverage import require_complete_baseline
from baseline.freeze import get_frozen_baseline as get_frozen_baseline
from baseline.freeze import save_baseline
from contracts.register import get_shift


get_baseline_revision = get_frozen_baseline


def create_baseline_revision(store, parent_id, baseline_id, values):
    with store.write():
        parent = get_baseline_revision(store, parent_id)
        shift = get_shift(store, parent.shift_id)
        vector = require_complete_baseline(shift.windows, values)
        return save_baseline(store, shift.shift_id, baseline_id, parent_id, vector)


def list_baseline_revisions(store, shift_id):
    get_shift(store, shift_id)
    rows = store.connection.execute(
        'SELECT baseline_id FROM baselines WHERE shift_id = ? ORDER BY baseline_id',
        (shift_id,),
    ).fetchall()
    return tuple(get_baseline_revision(store, row['baseline_id']) for row in rows)
