from dataclasses import dataclass

from contracts.register import get_shift
from exchange.identity import packet_key, verify_packet_payload
from exchange.receipts import get_receipt
from station.sparse import SPARSE_KIND


@dataclass(frozen=True)
class ReceiptSource:
    receipt_id: str
    packet_id: str
    station: str
    revision_id: str
    fingerprint: str
    ack: str
    usage_kwh: tuple[int, ...]


def selected_receipt_metadata(receipt, packet):
    return ReceiptSource(receipt.receipt_id, packet.packet_id, packet.station,
                         packet.revision_id, receipt.fingerprint, receipt.ack,
                         packet.usage_kwh)


def verify_receipt_packet(shift, receipt):
    """Re-decode the stored original bytes and check every identity field."""
    packet, fingerprint = verify_packet_payload(receipt.raw)
    if (packet.packet_id != receipt.packet_id or fingerprint != receipt.fingerprint
            or packet_key(packet) != packet_key(receipt)):
        raise ValueError('receipt metadata disagrees with its stored packet')
    if (packet.shift_id != shift.shift_id or packet.contract_id != shift.contract_id
            or packet.windows != shift.windows or packet.station not in shift.stations):
        raise ValueError('receipt does not belong to the selected baseline shift')
    return packet


def validate_receipt_pair(shift, first, second):
    by_station = {}
    for receipt in (first, second):
        packet = verify_receipt_packet(shift, receipt)
        if getattr(packet, 'kind', None) == SPARSE_KIND:
            raise ValueError('a fixed report requires full fixed station packets')
        if packet.station in by_station:
            raise ValueError('the two receipts must come from different stations')
        by_station[packet.station] = selected_receipt_metadata(receipt, packet)
    first_station, second_station = shift.stations
    return by_station[first_station], by_station[second_station]


def select_station_pair(store, shift_id, receipt_a, receipt_b):
    shift = get_shift(store, shift_id)
    return validate_receipt_pair(shift, get_receipt(store, receipt_a),
                                 get_receipt(store, receipt_b))
