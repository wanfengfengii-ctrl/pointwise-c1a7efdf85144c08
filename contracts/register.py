import json
from dataclasses import asdict

from codec import canonical_json
from contracts.records import ShiftRecord, require_id, validate_shift_record
from contracts.windows import normalize_windows


def _definition(contract_id, shift_id, stations, limit_kw, windows):
    if not isinstance(stations, (tuple, list)):
        raise ValueError('stations must be a list or tuple')
    record = ShiftRecord(contract_id, shift_id, tuple(stations), limit_kw,
                         normalize_windows(windows))
    return validate_shift_record(record)


def define_shift(store, contract_id, shift_id, stations, limit_kw, windows):
    record = _definition(contract_id, shift_id, stations, limit_kw, windows)
    definition = canonical_json(asdict(record))
    with store.write():
        row = store.connection.execute(
            'SELECT definition FROM shifts WHERE shift_id = ?', (shift_id,)
        ).fetchone()
        if row is None:
            store.connection.execute(
                'INSERT INTO shifts(shift_id, definition) VALUES (?, ?)',
                (shift_id, definition),
            )
        elif row['definition'] != definition:
            raise ValueError('conflicting shift definition')
    return record


def get_shift(store, shift_id):
    require_id(shift_id, 'shift ID')
    row = store.connection.execute(
        'SELECT definition FROM shifts WHERE shift_id = ?', (shift_id,)
    ).fetchone()
    if row is None:
        raise KeyError(shift_id)
    payload = json.loads(row['definition'])
    payload['stations'] = tuple(payload['stations'])
    payload['windows'] = tuple(payload['windows'])
    return ShiftRecord(**payload)


def list_shift_windows(store, shift_id):
    return get_shift(store, shift_id).windows


def lock_shift(store, shift_id):
    store.require_write()
    store.connection.execute('UPDATE shifts SET locked = 1 WHERE shift_id = ?', (shift_id,))


def amend_shift(store, shift_id, stations, limit_kw, windows):
    """Amend a registered shift while all recorded facts still have a home."""
    with store.write():
        old = get_shift(store, shift_id)
        if store.connection.execute(
            'SELECT locked FROM shifts WHERE shift_id = ?', (shift_id,)
        ).fetchone()['locked']:
            raise ValueError('shift definition is locked')
        new = _definition(old.contract_id, shift_id, stations, limit_kw, windows)
        in_use = store.connection.execute('''
            SELECT v.window FROM baseline_values v JOIN baseline_drafts d USING (draft_id)
            WHERE d.shift_id = ?
            UNION SELECT window FROM tickets WHERE shift_id = ?
        ''', (shift_id, shift_id))
        if any(row['window'] not in new.windows for row in in_use):
            raise ValueError('amendment would orphan a recorded window')
        drafts = store.connection.execute(
            'SELECT station FROM station_drafts WHERE shift_id = ?', (shift_id,)
        )
        if any(row['station'] not in new.stations for row in drafts):
            raise ValueError('amendment would orphan a station draft')
        store.connection.execute(
            'UPDATE shifts SET definition = ? WHERE shift_id = ?',
            (canonical_json(asdict(new)), shift_id),
        )
    return new
