from contracts.records import require_id
from contracts.register import get_shift, lock_shift
from exchange.identity import packet_key, verify_packet_payload
from exchange.receipts import get_receipt, receipt_count, save_receipt


count_receipts = receipt_count


def find_receipt(store, packet_id):
    require_id(packet_id, 'packet ID')
    row = store.connection.execute(
        'SELECT receipt_id FROM receipts WHERE packet_id = ?', (packet_id,)
    ).fetchone()
    if row is None:
        raise KeyError(packet_id)
    return get_receipt(store, row['receipt_id'])


def accept_packet(store, raw):
    packet, fingerprint = verify_packet_payload(raw)
    with store.write():
        try:
            shift = get_shift(store, packet.shift_id)
        except KeyError as exc:
            raise ValueError('packet belongs to an unregistered shift') from exc
        if (packet.contract_id != shift.contract_id or packet.station not in shift.stations
                or packet.windows != shift.windows):
            raise ValueError('packet disagrees with the registered shift')
        previous = store.connection.execute('''
            SELECT receipt_id FROM receipts WHERE packet_id = ? OR
                (contract_id = ? AND shift_id = ? AND station = ? AND revision_id = ?)
        ''', (packet.packet_id, *packet_key(packet))).fetchone()
        if previous is not None:
            first = get_receipt(store, previous['receipt_id'])
            if first.fingerprint != fingerprint or first.raw != raw:
                raise ValueError('conflicting fixed packet replay')
            return first
        receipt = save_receipt(store, packet, raw, fingerprint)
        lock_shift(store, shift.shift_id)
        return receipt
