import csv
from dataclasses import asdict
from io import StringIO

from codec import canonical_json
from review.history import SparseReportRecord, get_report


def report_columns():
    return (
        'report_id', 'ack', 'contract_id', 'shift_id', 'baseline_id',
        'peak_kw', 'limit_kw', 'over_limit', 'station_a_source', 'station_b_source',
        'window', 'baseline_kwh', 'station_a_kwh', 'station_b_kwh', 'usage_kwh', 'demand_kw',
    )


def serialize_report(report, format='json'):
    if format == 'json':
        return canonical_json(asdict(report))
    if format != 'csv':
        raise ValueError('report format must be json or csv')
    if isinstance(report, SparseReportRecord):
        return serialize_sparse_csv(report)
    first, second = report.receipts
    common = (
        report.report_id, report.ack, report.contract_id, report.shift_id, report.baseline_id,
        report.peak_kw, report.limit_kw, canonical_json(report.over_limit),
        canonical_json(asdict(first)), canonical_json(asdict(second)),
    )
    target = StringIO(newline='')
    writer = csv.writer(target, lineterminator='\n')
    writer.writerow(report_columns())
    for row in zip(report.windows, report.baseline_kwh, first.usage_kwh, second.usage_kwh,
                   report.usage_kwh, report.window_kw, strict=True):
        writer.writerow((*common, *row))
    return target.getvalue()


def serialize_sparse_csv(report):
    target = StringIO(newline='')
    writer = csv.writer(target, lineterminator='\n')
    writer.writerow(report_columns())
    head = (
        report.report_id, report.ack, report.contract_id, report.shift_id, report.baseline_id,
        report.peak_kw, report.limit_kw, canonical_json(report.over_limit),
    )
    for index, window in enumerate(report.windows):
        alpha_receipt, beta_receipt = report.window_receipts[index]
        writer.writerow((*head, canonical_json(alpha_receipt),
                         canonical_json(beta_receipt), window,
                         report.baseline_kwh[index], '', '',
                         report.usage_kwh[index], report.window_kw[index]))
    return target.getvalue()


def export_report(store, report_id, format='json'):
    return serialize_report(get_report(store, report_id), format)
