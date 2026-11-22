import json
from dataclasses import dataclass

from codec import canonical_json
from contracts.records import require_id
from contracts.register import get_shift, lock_shift
from contracts.windows import window_positions
from station.packets import encode_station_packet
from station.tickets import Ticket, list_tickets, station_draft, ticket_payload


@dataclass(frozen=True)
class StationClose:
    revision_id: str
    shift_id: str
    station: str
    parent_id: str | None
    windows: tuple[str, ...]
    usage_kwh: tuple[int, ...]
    tickets: tuple[Ticket, ...]
    packet_id: str
    packet: bytes
    sparse: bool = False
    anchor_id: str | None = None
    changed_windows: tuple[str, ...] = ()


def sum_station_usage(windows, tickets):
    positions = window_positions(windows)
    usage = [0] * len(windows)
    for ticket in tickets:
        if ticket.window not in positions:
            raise ValueError('station revision contains a foreign window')
        usage[positions[ticket.window]] += ticket.kwh
    return tuple(usage)


def get_station_close(store, revision_id):
    require_id(revision_id, 'station revision ID')
    row = store.connection.execute(
        'SELECT * FROM station_revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        raise KeyError(revision_id)
    data = json.loads(row['snapshot'])
    return StationClose(row['revision_id'], row['shift_id'], row['station'], row['parent_id'],
                        tuple(data['windows']), tuple(data['usage_kwh']),
                        tuple(Ticket(**item) for item in data['tickets']),
                        row['packet_id'], row['packet_raw'], bool(data.get('sparse', False)),
                        data.get('anchor_id'),
                        tuple(data.get('changed_windows', ())))


def save_station_close(store, shift, station, revision_id, parent_id, tickets):
    store.require_write()
    tickets = tuple(sorted(tickets, key=lambda ticket: ticket.ticket_id))
    usage = sum_station_usage(shift.windows, tickets)
    packet_id, packet = encode_station_packet(
        shift, station, revision_id, usage, (ticket.ticket_id for ticket in tickets),
    )
    snapshot = canonical_json({
        'windows': shift.windows,
        'usage_kwh': usage,
        'tickets': [ticket_payload(ticket) for ticket in tickets],
    })
    store.connection.execute('''
        INSERT INTO station_revisions(revision_id, shift_id, station, parent_id,
                                      snapshot, packet_id, packet_raw)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (revision_id, shift.shift_id, station, parent_id, snapshot, packet_id, packet))
    lock_shift(store, shift.shift_id)
    return get_station_close(store, revision_id)


def close_station(store, shift_id, station, revision_id):
    require_id(revision_id, 'station revision ID')
    with store.write():
        shift = get_shift(store, shift_id)
        draft = station_draft(store, shift, station)
        if draft['revision_id'] != revision_id:
            raise KeyError(revision_id)
        if draft['closed']:
            raise ValueError('station revision is already closed')
        tickets = list_tickets(store, shift_id, station)
        closed = save_station_close(store, shift, station, revision_id, None, tickets)
        store.connection.execute('''
            UPDATE station_drafts SET closed = 1 WHERE shift_id = ? AND station = ?
        ''', (shift_id, station))
        return closed
