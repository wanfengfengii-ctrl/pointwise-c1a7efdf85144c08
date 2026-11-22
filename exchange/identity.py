import json

from codec import digest
from station.packets import decode_station_packet
from station.sparse import SPARSE_KIND, decode_sparse_packet


def packet_fingerprint(raw):
    return digest(raw)


def packet_key(packet):
    return packet.contract_id, packet.shift_id, packet.station, packet.revision_id


def decode_packet(raw):
    """Decode either a full fixed packet or a sparse correction packet."""
    if not isinstance(raw, bytes):
        raise ValueError('a packet must be supplied as bytes')
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid packet JSON') from exc
    if not isinstance(payload, dict):
        raise ValueError('invalid packet payload')
    if payload.get('kind') == SPARSE_KIND:
        return decode_sparse_packet(raw)
    return decode_station_packet(raw)


def verify_packet_payload(raw):
    packet = decode_packet(raw)
    return packet, packet_fingerprint(raw)
