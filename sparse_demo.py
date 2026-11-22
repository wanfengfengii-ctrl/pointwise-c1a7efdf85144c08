"""Demo for sparse station corrections and the sparse review handover.

Shows the three situations required by SPARSE-REVIEW.md:
1. a missing intermediate correction can still be signed when later corrections
   cover every window it changed;
2. a target that still needs an unreceived supplying original is rejected;
3. after the missing piece is backfilled, the same target signs and the report
   together with every per-window source can be reclaimed after reopening.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import SAMPLE_DIR, define_sample_shift, prepare_center
from metering import (
    Store, Ticket, accept_packet, begin_station, build_station_packet, close_station,
    correct_station_sparse, get_report_receipt, issue_sparse,
    read_report, record_tickets,
)


def _station_packets(sample, history):
    station_input = sample['station_inputs'][0]
    with Store(':memory:') as station:
        shift = define_sample_shift(station, sample)
        code = station_input['station']
        begin_station(station, shift.shift_id, code, station_input['revision_id'])
        record_tickets(station, shift.shift_id, code,
                       [Ticket(*row) for row in station_input['tickets']])
        close_station(station, shift.shift_id, code, station_input['revision_id'])
        packets = {station_input['revision_id']:
                   build_station_packet(station, station_input['revision_id'])}
        for entry in history:
            revised = correct_station_sparse(
                station, entry['parent'], entry['revision'],
                {ticket_id: tuple(change) for ticket_id, change in entry['tickets'].items()},
            )
            packets[revised.revision_id] = build_station_packet(station, revised.revision_id)
        return packets


def _other_station_packet(sample):
    station_input = sample['station_inputs'][1]
    with Store(':memory:') as station:
        shift = define_sample_shift(station, sample)
        code = station_input['station']
        begin_station(station, shift.shift_id, code, station_input['revision_id'])
        record_tickets(station, shift.shift_id, code,
                       [Ticket(*row) for row in station_input['tickets']])
        close_station(station, shift.shift_id, code, station_input['revision_id'])
        return build_station_packet(station, station_input['revision_id'])


def _source_revisions(center, window_receipts):
    revisions = []
    for alpha_receipt_id, _ in window_receipts:
        revisions.append(find_receipt_id_revision(center, alpha_receipt_id))
    return revisions


def find_receipt_id_revision(store, receipt_id):
    from metering import get_receipt
    return get_receipt(store, receipt_id).revision_id


def run_sparse_demo():
    sample = json.loads((SAMPLE_DIR / 'sparse-shift.json').read_text(encoding='utf-8'))
    packets = _station_packets(sample, sample['corrections'])
    beta_packet = _other_station_packet(sample)
    summary = {}
    with TemporaryDirectory(prefix='haijia-sparse-') as directory:
        center_path = Path(directory) / 'center.sqlite'
        with Store(center_path) as center:
            baseline = prepare_center(center, sample)
            # The center receives things out of order: A2 arrives before its
            # anchor A0, and intermediate A1 never arrives at this stage.
            target_a2 = accept_packet(center, packets['A2'])
            anchor = accept_packet(center, packets['A0'])
            other = accept_packet(center, beta_packet)
            accept_packet(center, packets['P'])
            signed = issue_sparse(center, baseline.baseline_id, anchor.receipt_id,
                                  target_a2.receipt_id, other.receipt_id)
            summary['missing_intermediate_signed'] = {
                'report_id': signed.report_id,
                'usage_kwh': list(signed.usage_kwh),
                'peak_kw': signed.peak_kw,
                'over_limit': signed.over_limit,
                'alpha_source_revisions': _source_revisions(center, signed.window_receipts),
            }
            # A3 needs A1's window-2 total: without A1 the supply original is missing.
            target_a3 = accept_packet(center, packets['A3'])
            try:
                issue_sparse(center, baseline.baseline_id, anchor.receipt_id,
                             target_a3.receipt_id, other.receipt_id)
            except ValueError as rejected:
                summary['missing_supply_original_rejected'] = str(rejected)
            # Backfill A1: the same target now signs, over the contract limit.
            backfill = accept_packet(center, packets['A1'])
            over_limit = issue_sparse(center, baseline.baseline_id, anchor.receipt_id,
                                      target_a3.receipt_id, other.receipt_id)
            summary['backfilled_target_signed'] = {
                'report_id': over_limit.report_id,
                'usage_kwh': list(over_limit.usage_kwh),
                'peak_kw': over_limit.peak_kw,
                'over_limit': over_limit.over_limit,
                'alpha_source_revisions': _source_revisions(center, over_limit.window_receipts),
                'backfilled_receipt_id': backfill.receipt_id,
            }
            saved = (signed.report_id, over_limit.report_id,
                     {signed.report_id: signed.window_receipts,
                      over_limit.report_id: over_limit.window_receipts})
        # Reopen the closed center and reclaim the signed usage and sources by id.
        with Store(center_path) as center:
            reclaimed = {}
            for report_id in saved[:2]:
                report = read_report(center, report_id)
                reclaimed[report_id] = {
                    'ack': get_report_receipt(center, report_id),
                    'usage_kwh': list(report.usage_kwh),
                    'window_receipts': [list(pair) for pair in report.window_receipts],
                }
            summary['reopened_reclaims'] = reclaimed
    return summary


def main():
    print(json.dumps(run_sparse_demo(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
