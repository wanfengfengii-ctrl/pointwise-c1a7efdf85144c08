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


@dataclass(frozen=True)
class SparseReportRecord:
    report_id: str
    ack: str
    contract_id: str
    shift_id: str
    baseline_id: str
    windows: tuple[str, ...]
    baseline_kwh: tuple[int, ...]
    usage_kwh: tuple[int, ...]
    window_kw: tuple[int, ...]
    peak_kw: int
    limit_kw: int
    over_limit: bool
    anchor_receipt_id: str
    target_receipt_id: str
    other_receipt_id: str
    window_receipts: tuple[tuple[str, str], ...]


def save_report(store, content):
    """Store a fully calculated snapshot and its acknowledgment in the caller's transaction."""
    store.require_write()
    serial = store.connection.execute('SELECT MAX(serial) FROM reports').fetchone()[0]
    serial = 1 if serial is None else serial + 1
    report_id = f'rp-{serial}'
    ack = f'ra-{serial}'
    if content.get('sparse'):
        first_receipt = content['anchor_receipt_id']
        second_receipt = content['other_receipt_id']
    else:
        first, second = content['receipts']
        first_receipt = first['receipt_id']
        second_receipt = second['receipt_id']
    store.connection.execute('''
        INSERT INTO reports(serial, report_id, baseline_id, receipt_a, receipt_b, snapshot)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (serial, report_id, content['baseline_id'], first_receipt,
          second_receipt, canonical_json(content)))
    store.connection.execute(
        'INSERT INTO report_acks(report_id, ack) VALUES (?, ?)', (report_id, ack)
    )
    return get_report(store, report_id)


def _as_receipt_source(item):
    item['usage_kwh'] = tuple(item['usage_kwh'])
    return ReceiptSource(**item)


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
    if body.get('sparse'):
        body['window_receipts'] = tuple(
            tuple(pair) for pair in body['window_receipts']
        )
        public = {field: body[field] for field in SparseReportRecord.__dataclass_fields__
                  if field != 'report_id' and field != 'ack'}
        return SparseReportRecord(report_id, row['ack'], **public)
    sources = []
    for item in body['receipts']:
        sources.append(_as_receipt_source(dict(item)))
    body['receipts'] = tuple(sources)
    return ReportRecord(report_id, row['ack'], **{
        field: body[field] for field in ReportRecord.__dataclass_fields__
        if field != 'report_id' and field != 'ack'
    })


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
