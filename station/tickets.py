from dataclasses import dataclass

from contracts.rates import require_nonnegative_int
from contracts.records import require_id
from contracts.register import get_shift
from contracts.windows import window_positions


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    window: str
    kwh: int


def ticket_payload(ticket):
    return {'ticket_id': ticket.ticket_id, 'window': ticket.window, 'kwh': ticket.kwh}


def revision_in_use(store, revision_id):
    require_id(revision_id, 'station revision ID')
    return store.connection.execute('''
        SELECT 1 FROM station_drafts WHERE revision_id = ?
        UNION ALL SELECT 1 FROM station_revisions WHERE revision_id = ? LIMIT 1
    ''', (revision_id, revision_id)).fetchone() is not None


def require_station(shift, station):
    require_id(station, 'station')
    if station not in shift.stations:
        raise ValueError('station is outside the shift')


def begin_station(store, shift_id, station, revision_id):
    require_id(revision_id, 'station revision ID')
    with store.write():
        shift = get_shift(store, shift_id)
        require_station(shift, station)
        current = store.connection.execute('''
            SELECT revision_id, closed FROM station_drafts WHERE shift_id = ? AND station = ?
        ''', (shift_id, station)).fetchone()
        if current is not None:
            if current['revision_id'] == revision_id and not current['closed']:
                return revision_id
            raise ValueError('station already has a draft or a closed revision')
        if revision_in_use(store, revision_id):
            raise ValueError('station revision ID is already used')
        store.connection.execute('''
            INSERT INTO station_drafts(shift_id, station, revision_id) VALUES (?, ?, ?)
        ''', (shift_id, station, revision_id))
    return revision_id


def station_draft(store, shift, station):
    require_station(shift, station)
    row = store.connection.execute('''
        SELECT revision_id, closed FROM station_drafts WHERE shift_id = ? AND station = ?
    ''', (shift.shift_id, station)).fetchone()
    if row is None:
        raise KeyError((shift.shift_id, station))
    return row


def _as_ticket(row):
    return Ticket(row['ticket_id'], row['window'], int(row['kwh']))


def _lookup(store, shift_id, station, ticket_id):
    row = store.connection.execute('''
        SELECT ticket_id, window, kwh FROM tickets
        WHERE shift_id = ? AND station = ? AND ticket_id = ?
    ''', (shift_id, station, ticket_id)).fetchone()
    return _as_ticket(row) if row is not None else None


def get_ticket(store, shift_id, station, ticket_id):
    require_id(ticket_id, 'ticket ID')
    station_draft(store, get_shift(store, shift_id), station)
    ticket = _lookup(store, shift_id, station, ticket_id)
    if ticket is None:
        raise KeyError(ticket_id)
    return ticket


def list_tickets(store, shift_id, station):
    station_draft(store, get_shift(store, shift_id), station)
    rows = store.connection.execute('''
        SELECT ticket_id, window, kwh FROM tickets
        WHERE shift_id = ? AND station = ? ORDER BY ticket_id
    ''', (shift_id, station))
    return tuple(_as_ticket(row) for row in rows)


def _validate_ticket(ticket, positions):
    if not isinstance(ticket, Ticket):
        raise ValueError('expected Ticket records')
    require_id(ticket.ticket_id, 'ticket ID')
    require_nonnegative_int(ticket.kwh, 'ticket kWh')
    if not isinstance(ticket.window, str) or ticket.window not in positions:
        raise ValueError('ticket window is outside the shift')


def record_tickets(store, shift_id, station, tickets):
    """Post a batch atomically, identifying each fact by its station ticket ID."""
    try:
        batch = tuple(tickets)
    except TypeError as exc:
        raise ValueError('tickets must be iterable') from exc
    with store.write():
        shift = get_shift(store, shift_id)
        draft = station_draft(store, shift, station)
        if draft['closed']:
            raise ValueError('station is closed')
        positions = window_positions(shift.windows)
        for ticket in batch:
            _validate_ticket(ticket, positions)
            previous = _lookup(store, shift_id, station, ticket.ticket_id)
            if previous is None:
                store.connection.execute('''
                    INSERT INTO tickets(shift_id, station, ticket_id, window, kwh)
                    VALUES (?, ?, ?, ?, ?)
                ''', (shift_id, station, ticket.ticket_id, ticket.window, str(ticket.kwh)))
            elif previous != ticket:
                raise ValueError('conflicting ticket replay')
        return batch


def record_ticket(store, shift_id, station, ticket_id, window, kwh):
    return record_tickets(store, shift_id, station, (Ticket(ticket_id, window, kwh),))[0]
