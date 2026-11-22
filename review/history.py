import json
from dataclasses import dataclass

from codec import canonical_json
from contracts.records import require_id
from exchange.selection import ReceiptSource


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    ack: str
    contract_id: str
    shift_id: str
    baseline_id: str
    windows: tuple[str, ...]
    baseline_kwh: tuple[int, ...]
    receipts: tuple[ReceiptSource, ReceiptSource]
    usage_kwh: tuple[int, ...]
    window_kw: tuple[int, ...]
    peak_kw: int
    limit_kw: int
    over_limit: bool


def save_report(store, content):
    """Store a fully calculated snapshot and its acknowledgment in the caller's transaction."""
    store.require_write()
    serial = store.connection.execute('SELECT MAX(serial) FROM reports').fetchone()[0]
    serial = 1 if serial is None else serial + 1
    report_id = f'rp-{serial}'
    ack = f'ra-{serial}'
    first, second = content['receipts']
    store.connection.execute('''
        INSERT INTO reports(serial, report_id, baseline_id, receipt_a, receipt_b, snapshot)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (serial, report_id, content['baseline_id'], first['receipt_id'],
          second['receipt_id'], canonical_json(content)))
    store.connection.execute(
        'INSERT INTO report_acks(report_id, ack) VALUES (?, ?)', (report_id, ack)
    )
    return get_report(store, report_id)


def get_report(store, report_id):
    require_id(report_id, 'report ID')
    row = store.connection.execute('''
        SELECT r.snapshot, a.ack FROM reports r JOIN report_acks a USING (report_id)
        WHERE r.report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        raise KeyError(report_id)
    body = json.loads(row['snapshot'])
    for field in ('windows', 'baseline_kwh', 'usage_kwh', 'window_kw'):
        body[field] = tuple(body[field])
    sources = []
    for item in body['receipts']:
        item['usage_kwh'] = tuple(item['usage_kwh'])
        sources.append(ReceiptSource(**item))
    body['receipts'] = tuple(sources)
    return ReportRecord(report_id, row['ack'], **body)


def get_report_receipt(store, report_id):
    require_id(report_id, 'report ID')
    row = store.connection.execute(
        'SELECT ack FROM report_acks WHERE report_id = ?', (report_id,)
    ).fetchone()
    if row is None:
        raise KeyError(report_id)
    return row['ack']


def report_counts(store):
    row = store.connection.execute('''
        SELECT (SELECT COUNT(*) FROM reports), (SELECT COUNT(*) FROM report_acks)
    ''').fetchone()
    return tuple(row)
