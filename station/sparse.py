"""Sparse station corrections sealed against a full fixed anchor packet.

A sparse revision only carries the totals of the windows changed in this step,
together with branch evidence that pins the full fixed anchor packet and the
parent chain. The station ledger still keeps the complete effective ticket set,
so later sparse corrections validate against the same original-window facts.
"""
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from codec import canonical_json, json_bytes
from contracts.rates import require_nonnegative_int
from contracts.records import require_id
from contracts.windows import validate_window_set
from station.packets import station_packet_id
from station.revisions import revision_in_use
from station.settle import get_station_close, sum_station_usage
from contracts.register import get_shift, lock_shift
from station.tickets import Ticket, ticket_payload


SPARSE_VERSION = 2
SPARSE_KIND = 'sparse'
_SPARSE_FIELDS = frozenset({
    'version', 'kind', 'packet_id', 'contract_id', 'shift_id', 'station',
    'revision_id', 'parent_id', 'anchor_id', 'windows', 'changes', 'branch',
    'closed',
})
_CHANGE_FIELDS = frozenset({'window', 'kwh', 'ticket_ids'})
_BRANCH_FIELDS = frozenset({'revision_id', 'parent_id', 'changed_windows'})


@dataclass(frozen=True)
class SparseWindowChange:
    window: str
    kwh: int
    ticket_ids: tuple[str, ...]


@dataclass(frozen=True)
class SparseBranchEntry:
    revision_id: str
    parent_id: str
    changed_windows: tuple[str, ...]


@dataclass(frozen=True)
class SparseStationPacket:
    version: int
    kind: str
    packet_id: str
    contract_id: str
    shift_id: str
    station: str
    revision_id: str
    parent_id: str
    anchor_id: str
    windows: tuple[str, ...]
    changes: tuple[SparseWindowChange, ...]
    branch: tuple[SparseBranchEntry, ...]
    closed: bool


def encode_sparse_packet(shift, station, revision_id, parent_id, anchor_id, changes,
                         branch):
    packet_id = station_packet_id(shift.contract_id, shift.shift_id, station, revision_id)
    packet = SparseStationPacket(
        SPARSE_VERSION, SPARSE_KIND, packet_id, shift.contract_id, shift.shift_id, station,
        revision_id, parent_id, anchor_id, shift.windows, tuple(changes), tuple(branch), True,
    )
    return packet_id, json_bytes(asdict(packet))


def _decode_branch_entry(item):
    if not isinstance(item, dict) or set(item) != _BRANCH_FIELDS:
        raise ValueError('sparse packet has an invalid branch entry')
    require_id(item['revision_id'], 'branch revision ID')
    require_id(item['parent_id'], 'branch parent ID')
    changed = item['changed_windows']
    if not isinstance(changed, list) or not changed or tuple(changed) != tuple(sorted(set(changed))):
        raise ValueError('sparse branch entry has invalid changed windows')
    return SparseBranchEntry(item['revision_id'], item['parent_id'], tuple(changed))


def decode_sparse_packet(raw):
    if not isinstance(raw, bytes):
        raise ValueError('sparse packet must be supplied as bytes')
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid sparse packet JSON') from exc
    if not isinstance(payload, dict) or set(payload) != _SPARSE_FIELDS:
        raise ValueError('unsupported sparse packet schema')
    if type(payload.get('version')) is not int or payload['version'] != SPARSE_VERSION:
        raise ValueError('unsupported sparse packet version')
    if payload.get('kind') != SPARSE_KIND or payload.get('closed') is not True:
        raise ValueError('packet is not a closed sparse revision')
    for key in ('contract_id', 'shift_id', 'station', 'revision_id', 'parent_id',
                'anchor_id', 'packet_id'):
        require_id(payload[key], key)
    expected_id = station_packet_id(payload['contract_id'], payload['shift_id'],
                                    payload['station'], payload['revision_id'])
    if payload['packet_id'] != expected_id:
        raise ValueError('sparse packet ID does not match its source')
    if payload['anchor_id'] == payload['revision_id']:
        raise ValueError('sparse anchor must be a distinct full fixed revision')
    windows = validate_window_set(payload['windows'])
    window_set = set(windows)
    raw_changes = payload['changes']
    if not isinstance(raw_changes, list) or not raw_changes:
        raise ValueError('sparse packet requires at least one window change')
    changes = []
    changed_windows = []
    for item in raw_changes:
        if not isinstance(item, dict) or set(item) != _CHANGE_FIELDS:
            raise ValueError('sparse packet has an invalid window change')
        window = item['window']
        if not isinstance(window, str) or window not in window_set:
            raise ValueError('sparse change window is outside the shift')
        require_nonnegative_int(item['kwh'], 'station kWh')
        ticket_ids = item['ticket_ids']
        if (not isinstance(ticket_ids, list) or not ticket_ids
                or tuple(ticket_ids) != tuple(sorted(set(ticket_ids)))):
            raise ValueError('sparse change has invalid ticket references')
        for ticket_id in ticket_ids:
            require_id(ticket_id, 'ticket ID')
        changes.append(SparseWindowChange(window, item['kwh'], tuple(ticket_ids)))
        changed_windows.append(window)
    if tuple(changed_windows) != tuple(sorted(set(changed_windows))):
        raise ValueError('each changed window has exactly one sparse total')
    raw_branch = payload['branch']
    if not isinstance(raw_branch, list) or not raw_branch:
        raise ValueError('sparse packet requires branch evidence')
    branch = tuple(_decode_branch_entry(item) for item in raw_branch)
    revision_ids = [entry.revision_id for entry in branch]
    if len(set(revision_ids)) != len(branch) or payload['anchor_id'] in revision_ids:
        raise ValueError('sparse branch contains a duplicated revision')
    if branch[0].parent_id != payload['anchor_id']:
        raise ValueError('sparse branch must start at its anchor revision')
    for previous, entry in zip(branch, branch[1:], strict=False):
        if entry.parent_id != previous.revision_id:
            raise ValueError('sparse branch parent chain is broken')
    tail = branch[-1]
    if (tail.revision_id != payload['revision_id']
            or tail.parent_id != payload['parent_id']
            or set(tail.changed_windows) != set(changed_windows)):
        raise ValueError('sparse packet does not seal its own branch step')
    if json_bytes(payload) != raw:
        raise ValueError('sparse packet is not in canonical encoding')
    return SparseStationPacket(
        payload['version'], payload['kind'], payload['packet_id'], payload['contract_id'],
        payload['shift_id'], payload['station'], payload['revision_id'], payload['parent_id'],
        payload['anchor_id'], windows, tuple(changes), branch, True,
    )


def _anchor_of(parent):
    return parent.anchor_id if parent.sparse else parent.revision_id


def _parent_branch(parent):
    if not parent.sparse:
        return ()
    packet = decode_sparse_packet(parent.packet)
    return packet.branch


def save_sparse_close(store, shift, station, revision_id, parent_revision, anchor_id,
                      tickets, changed_windows, parent):
    store.require_write()
    tickets = tuple(sorted(tickets, key=lambda ticket: ticket.ticket_id))
    usage = sum_station_usage(shift.windows, tickets)
    positions = {window: index for index, window in enumerate(shift.windows)}
    tickets_by_window = {}
    for ticket in tickets:
        tickets_by_window.setdefault(ticket.window, []).append(ticket.ticket_id)
    changes = []
    for window in changed_windows:
        changes.append(SparseWindowChange(
            window, usage[positions[window]],
            tuple(sorted(tickets_by_window.get(window, ()))),
        ))
    branch = (*_parent_branch(parent),
              SparseBranchEntry(revision_id, parent_revision, tuple(changed_windows)))
    packet_id, packet = encode_sparse_packet(
        shift, station, revision_id, parent_revision, anchor_id, changes, branch,
    )
    snapshot = canonical_json({
        'windows': shift.windows,
        'usage_kwh': usage,
        'tickets': [ticket_payload(ticket) for ticket in tickets],
        'sparse': True,
        'anchor_id': anchor_id,
        'changed_windows': tuple(changed_windows),
    })
    store.connection.execute('''
        INSERT INTO station_revisions(revision_id, shift_id, station, parent_id,
                                      snapshot, packet_id, packet_raw)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (revision_id, shift.shift_id, station, parent_revision, snapshot, packet_id, packet))
    lock_shift(store, shift.shift_id)
    return get_station_close(store, revision_id)


def correct_station_sparse(store, parent_revision, new_revision, corrections):
    """Seal a sparse correction carrying only the changed window totals."""
    require_id(new_revision, 'station revision ID')
    if not isinstance(corrections, Mapping) or not corrections:
        raise ValueError('at least one named ticket correction is required')
    with store.write():
        parent = get_station_close(store, parent_revision)
        if revision_in_use(store, new_revision):
            raise ValueError('station revision ID is already used')
        shift = get_shift(store, parent.shift_id)
        tickets = {ticket.ticket_id: ticket for ticket in parent.tickets}
        changed_windows = set()
        for ticket_id, change in corrections.items():
            require_id(ticket_id, 'ticket ID')
            if ticket_id not in tickets:
                raise ValueError('ticket does not belong to the parent revision')
            if not isinstance(change, (list, tuple)) or len(change) != 2:
                raise ValueError('a correction requires the original window and new kWh')
            window, kwh = change
            if window != tickets[ticket_id].window:
                raise ValueError('a correction must keep the original window')
            tickets[ticket_id] = Ticket(
                ticket_id, window, require_nonnegative_int(kwh, 'ticket kWh'),
            )
            changed_windows.add(window)
        ordered_windows = tuple(
            window for window in shift.windows if window in changed_windows
        )
        return save_sparse_close(
            store, shift, parent.station, new_revision, parent_revision,
            _anchor_of(parent), tickets.values(), ordered_windows, parent,
        )
