from codec import digest
from station.packets import decode_station_packet


def packet_fingerprint(raw):
    return digest(raw)


def packet_key(packet):
    return packet.contract_id, packet.shift_id, packet.station, packet.revision_id


def verify_packet_payload(raw):
    packet = decode_station_packet(raw)
    return packet, packet_fingerprint(raw)
