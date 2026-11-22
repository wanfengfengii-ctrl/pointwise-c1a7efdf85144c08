import json
from dataclasses import dataclass

from baseline.coverage import require_complete_baseline
from baseline.register import read_baseline_draft
from codec import canonical_json
from contracts.records import require_id
from contracts.register import get_shift, lock_shift


@dataclass(frozen=True)
class FrozenBaseline:
    baseline_id: str
    shift_id: str
    parent_id: str | None
    values: tuple[int, ...]


def get_frozen_baseline(store, baseline_id):
    require_id(baseline_id, 'baseline ID')
    row = store.connection.execute(
        'SELECT * FROM baselines WHERE baseline_id = ?', (baseline_id,)
    ).fetchone()
    if row is None:
        raise KeyError(baseline_id)
    return FrozenBaseline(baseline_id, row['shift_id'], row['parent_id'],
                          tuple(json.loads(row['vector'])))


def frozen_baseline_exists(store, baseline_id):
    require_id(baseline_id, 'baseline ID')
    return store.connection.execute(
        'SELECT 1 FROM baselines WHERE baseline_id = ?', (baseline_id,)
    ).fetchone() is not None


def save_baseline(store, shift_id, baseline_id, parent_id, vector):
    store.require_write()
    if frozen_baseline_exists(store, baseline_id):
        raise ValueError('baseline ID is already used')
    store.connection.execute('''
        INSERT INTO baselines(baseline_id, shift_id, parent_id, vector) VALUES (?, ?, ?, ?)
    ''', (baseline_id, shift_id, parent_id, canonical_json(vector)))
    lock_shift(store, shift_id)
    return get_frozen_baseline(store, baseline_id)


def freeze_baseline(store, draft_id, baseline_id):
    require_id(baseline_id, 'baseline ID')
    with store.write():
        draft = read_baseline_draft(store, draft_id)
        if draft.frozen_id is not None:
            if draft.frozen_id != baseline_id:
                raise ValueError('baseline draft already has a frozen version')
            return get_frozen_baseline(store, baseline_id)
        shift = get_shift(store, draft.shift_id)
        vector = require_complete_baseline(shift.windows, draft.values)
        result = save_baseline(store, shift.shift_id, baseline_id, None, vector)
        store.connection.execute(
            'UPDATE baseline_drafts SET frozen_id = ? WHERE draft_id = ?',
            (baseline_id, draft_id),
        )
        return result
