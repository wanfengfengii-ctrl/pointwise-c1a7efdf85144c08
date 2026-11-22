from dataclasses import dataclass

from contracts.rates import require_nonnegative_int
from contracts.records import require_id
from contracts.register import get_shift


@dataclass(frozen=True)
class BaselineDraft:
    draft_id: str
    shift_id: str
    frozen_id: str | None
    values: dict[str, int]


def begin_baseline(store, shift_id, draft_id):
    require_id(draft_id, 'baseline draft ID')
    with store.write():
        get_shift(store, shift_id)
        row = store.connection.execute(
            'SELECT shift_id FROM baseline_drafts WHERE draft_id = ?', (draft_id,)
        ).fetchone()
        if row is None:
            store.connection.execute(
                'INSERT INTO baseline_drafts(draft_id, shift_id) VALUES (?, ?)',
                (draft_id, shift_id),
            )
        elif row['shift_id'] != shift_id:
            raise ValueError('baseline draft belongs to another shift')
        return read_baseline_draft(store, draft_id)


def read_baseline_draft(store, draft_id):
    require_id(draft_id, 'baseline draft ID')
    rows = store.connection.execute('''
        SELECT d.shift_id, d.frozen_id, v.window, v.kwh
        FROM baseline_drafts d LEFT JOIN baseline_values v USING (draft_id)
        WHERE d.draft_id = ? ORDER BY v.window
    ''', (draft_id,)).fetchall()
    if not rows:
        raise KeyError(draft_id)
    values = {row['window']: int(row['kwh']) for row in rows if row['window'] is not None}
    return BaselineDraft(draft_id, rows[0]['shift_id'], rows[0]['frozen_id'], values)


def record_baseline_value(store, draft_id, window, kwh):
    require_nonnegative_int(kwh, 'baseline kWh')
    with store.write():
        draft = read_baseline_draft(store, draft_id)
        if draft.frozen_id is not None:
            raise ValueError('baseline draft is frozen')
        if not isinstance(window, str) or window not in get_shift(store, draft.shift_id).windows:
            raise ValueError('window is outside the baseline shift')
        store.connection.execute('''
            INSERT INTO baseline_values(draft_id, window, kwh) VALUES (?, ?, ?)
            ON CONFLICT (draft_id, window) DO UPDATE SET kwh = excluded.kwh
        ''', (draft_id, window, str(kwh)))
        return read_baseline_draft(store, draft_id)
