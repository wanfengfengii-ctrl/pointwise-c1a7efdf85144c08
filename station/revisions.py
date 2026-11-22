from collections.abc import Mapping

from contracts.rates import require_nonnegative_int
from contracts.records import require_id
from contracts.register import get_shift
from station.settle import get_station_close, save_station_close
from station.tickets import Ticket, require_station, revision_in_use


get_station_revision = get_station_close


def correct_station(store, parent_revision, new_revision, corrections):
    require_id(new_revision, 'station revision ID')
    if not isinstance(corrections, Mapping) or not corrections:
        raise ValueError('at least one named ticket correction is required')
    with store.write():
        parent = get_station_revision(store, parent_revision)
        if revision_in_use(store, new_revision):
            raise ValueError('station revision ID is already used')
        shift = get_shift(store, parent.shift_id)
        tickets = {ticket.ticket_id: ticket for ticket in parent.tickets}
        for ticket_id, change in corrections.items():
            require_id(ticket_id, 'ticket ID')
            if ticket_id not in tickets:
                raise ValueError('ticket does not belong to the parent revision')
            if not isinstance(change, (list, tuple)) or len(change) != 2:
                raise ValueError('a correction requires the original window and new kWh')
            window, kwh = change
            if window != tickets[ticket_id].window:
                raise ValueError('a correction must keep the original window')
            tickets[ticket_id] = Ticket(ticket_id, window, require_nonnegative_int(kwh, 'ticket kWh'))
        return save_station_close(store, shift, parent.station, new_revision,
                                  parent_revision, tickets.values())


def list_station_revisions(store, shift_id, station):
    require_station(get_shift(store, shift_id), station)
    rows = store.connection.execute('''
        SELECT revision_id FROM station_revisions WHERE shift_id = ? AND station = ?
        ORDER BY revision_id
    ''', (shift_id, station)).fetchall()
    return tuple(get_station_revision(store, row['revision_id']) for row in rows)
