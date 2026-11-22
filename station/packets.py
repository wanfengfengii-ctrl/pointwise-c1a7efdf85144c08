import json
from dataclasses import asdict, dataclass

from codec import json_bytes, stable_id
from contracts.rates import require_nonnegative_int
from contracts.records import require_id
from contracts.windows import validate_window_set


_VERSION = 1
_FIELDS = frozenset({
    'version', 'packet_id', 'contract_id', 'shift_id', 'station', 'revision_id',
    'windows', 'usage_kwh', 'ticket_ids', 'closed',
})


@dataclass(frozen=True)
class StationPacket:
    version: int
    packet_id: str
    contract_id: str
    shift_id: str
    station: str
    revision_id: str
    windows: tuple[str, ...]
    usage_kwh: tuple[int, ...]
    ticket_ids: tuple[str, ...]
    closed: bool


def packet_version(payload):
    if not isinstance(payload, dict) or type(payload.get('version')) is not int:
        raise ValueError('fixed packet requires an integer version')
    return payload['version']


def station_packet_id(contract_id, shift_id, station, revision_id):
    return stable_id('pkt', contract_id, shift_id, station, revision_id)


def encode_station_packet(shift, station, revision_id, usage, ticket_ids):
    packet_id = station_packet_id(shift.contract_id, shift.shift_id, station, revision_id)
    packet = StationPacket(_VERSION, packet_id, shift.contract_id, shift.shift_id, station,
                           revision_id, shift.windows, usage, tuple(sorted(ticket_ids)), True)
    return packet_id, json_bytes(asdict(packet))


def decode_station_packet(raw):
    if not isinstance(raw, bytes):
        raise ValueError('fixed packet must be supplied as bytes')
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid fixed packet JSON') from exc
    if packet_version(payload) != _VERSION or set(payload) != _FIELDS:
        raise ValueError('unsupported fixed packet schema')
    if payload['closed'] is not True:
        raise ValueError('packet must describe a closed revision')
    for key in ('contract_id', 'shift_id', 'station', 'revision_id', 'packet_id'):
        require_id(payload[key], key)
    expected_id = station_packet_id(payload['contract_id'], payload['shift_id'],
                                    payload['station'], payload['revision_id'])
    if payload['packet_id'] != expected_id:
        raise ValueError('fixed packet ID does not match its source')
    windows = validate_window_set(payload['windows'])
    usage = payload['usage_kwh']
    if not isinstance(usage, list) or len(usage) != len(windows):
        raise ValueError('fixed packet vector must cover all windows')
    for quantity in usage:
        require_nonnegative_int(quantity, 'station kWh')
    ticket_ids = payload['ticket_ids']
    if not isinstance(ticket_ids, list):
        raise ValueError('fixed packet requires a ticket list')
    for ticket_id in ticket_ids:
        require_id(ticket_id, 'ticket ID')
    if ticket_ids != sorted(set(ticket_ids)) or (not ticket_ids and any(usage)):
        raise ValueError('fixed packet has invalid ticket references')
    if json_bytes(payload) != raw:
        raise ValueError('fixed packet is not in canonical encoding')
    payload['windows'] = windows
    payload['usage_kwh'] = tuple(usage)
    payload['ticket_ids'] = tuple(ticket_ids)
    return StationPacket(**payload)


def build_station_packet(store, revision_id):
    """Return the original bytes sealed when the revision was closed."""
    require_id(revision_id, 'station revision ID')
    row = store.connection.execute(
        'SELECT packet_raw FROM station_revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        raise KeyError(revision_id)
    return row['packet_raw']


def read_station_packet(store, packet_id):
    require_id(packet_id, 'packet ID')
    row = store.connection.execute(
        'SELECT packet_raw FROM station_revisions WHERE packet_id = ?', (packet_id,)
    ).fetchone()
    if row is None:
        raise KeyError(packet_id)
    return row['packet_raw']
