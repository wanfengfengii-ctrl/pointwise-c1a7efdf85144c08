from dataclasses import dataclass

from codec import stable_id
from contracts.records import require_id
from exchange.identity import packet_key


@dataclass(frozen=True)
class ReceiptRecord:
    receipt_id: str
    packet_id: str
    contract_id: str
    shift_id: str
    station: str
    revision_id: str
    fingerprint: str
    raw: bytes
    ack: str


def save_receipt(store, packet, raw, fingerprint):
    store.require_write()
    receipt_id = stable_id('rc', packet.packet_id)
    ack = stable_id('ack', receipt_id)
    store.connection.execute('''
        INSERT INTO receipts(receipt_id, packet_id, contract_id, shift_id, station,
                             revision_id, fingerprint, raw, ack)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (receipt_id, packet.packet_id, *packet_key(packet), fingerprint, raw, ack))
    return get_receipt(store, receipt_id)


def get_receipt(store, receipt_id):
    require_id(receipt_id, 'receipt ID')
    row = store.connection.execute(
        'SELECT * FROM receipts WHERE receipt_id = ?', (receipt_id,)
    ).fetchone()
    if row is None:
        raise KeyError(receipt_id)
    return ReceiptRecord(**dict(row))


def receipt_count(store):
    return store.connection.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]
