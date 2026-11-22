import csv
import io
import json

from demo import SAMPLE_DIR
from metering import (
    Store, accept_packet, build_station_packet, correct_station, count_receipts,
    create_baseline_revision, export_report, get_frozen_baseline, get_receipt,
    get_report_receipt, get_station_revision, issue_fixed, list_station_revisions,
    read_report, read_station_packet,
)
from review.history import report_counts
from tests.support import OfflineShiftCase, scenario


class CorrectionTests(OfflineShiftCase):
    def test_correct_and_read_preserves_old_report_and_issues_new(self):
        with Store(self.center_path) as center:
            baseline, first, second = self.prepare_receipts(center)
            old = issue_fixed(center, baseline.baseline_id, first.receipt_id, second.receipt_id)
            old_export = export_report(center, old.report_id)
        change = self.sample['correction']
        with Store(self.station_paths[0]) as station:
            parent = get_station_revision(station, change['parent'])
            with self.assertRaises(ValueError):
                correct_station(station, parent.revision_id, 'A-wrong',
                                {change['ticket_id']: (self.sample['windows'][1], 2)})
            with self.assertRaises(ValueError):
                correct_station(station, parent.revision_id, 'A-wrong',
                                {'A-other': (change['window'], 2)})
            with self.assertRaises(KeyError):
                correct_station(station, 'A-unknown', 'A-wrong',
                                {change['ticket_id']: (change['window'], 2)})
            revised = correct_station(station, parent.revision_id, change['revision_id'],
                                      {change['ticket_id']: (change['window'], change['kwh'])})
            self.assertEqual(revised.parent_id, parent.revision_id)
            self.assertEqual(parent.usage_kwh, (1, 0))
            self.assertEqual(revised.usage_kwh, (2, 0))
            self.assertEqual(list_station_revisions(station, parent.shift_id, parent.station),
                             (parent, revised))
            self.assertEqual(read_station_packet(station, parent.packet_id), first.raw)
        with Store(self.center_path) as center:
            updated = accept_packet(center, revised.packet)
            new = issue_fixed(center, baseline.baseline_id, updated.receipt_id, second.receipt_id)
            new_export = export_report(center, new.report_id)
            self.assertEqual((new.usage_kwh, new.peak_kw, new.over_limit), ((3, 2), 12, True))
            self.assertNotEqual(new.report_id, old.report_id)
        with Store(self.center_path) as center:
            original_again = read_report(center, old.report_id)
            current_again = read_report(center, new.report_id)
            self.assertEqual(original_again, old)
            self.assertEqual(original_again.peak_kw, 8)
            self.assertEqual(current_again, new)
            self.assertEqual(current_again.peak_kw, 12)
            self.assertEqual(original_again.receipts[0].receipt_id, first.receipt_id)
            self.assertEqual(current_again.receipts[0].receipt_id, updated.receipt_id)
            self.assertEqual(original_again.receipts[0].revision_id, 'A-01')
            self.assertEqual(current_again.receipts[0].revision_id, 'A-02')
            self.assertEqual(export_report(center, old.report_id), old_export)
            self.assertEqual(export_report(center, new.report_id), new_export)
            rows = list(csv.DictReader(io.StringIO(export_report(center, old.report_id, 'csv'))))
            self.assertEqual([row['window'] for row in rows], self.sample['windows'])
            self.assertEqual([row['usage_kwh'] for row in rows], ['2', '2'])
            self.assertEqual([row['demand_kw'] for row in rows], ['8', '8'])
            self.assertEqual(json.loads(rows[0]['station_a_source'])['receipt_id'], first.receipt_id)
        with Store(self.station_paths[0]) as station:
            self.assertEqual(build_station_packet(station, 'A-01'), first.raw)
            self.assertEqual(read_station_packet(station, revised.packet_id), revised.packet)
        scenario('correct_and_read', {'baseline': [1, 0], 'first_a': [1, 0], 'new_a': [2, 0],
                                       'b': [0, 2], 'limit_kw': 8},
                 [8, 12], [old.peak_kw, new.peak_kw],
                 [[8, first.receipt_id, 'A-01'], [12, updated.receipt_id, 'A-02']],
                 [[report.peak_kw, report.receipts[0].receipt_id, report.receipts[0].revision_id]
                  for report in (original_again, current_again)],
                 ['station/revisions.py', 'station/settle.py', 'exchange/accept.py',
                  'review/history.py', 'review/export.py'],
                 'The original maxima are 2 kWh and 3 kWh respectively. The two report numbers preserve separate source revisions.')

    def test_baseline_correction_requires_new_report_selection(self):
        with Store(self.center_path) as center:
            baseline, first, second = self.prepare_receipts(center)
            original = issue_fixed(center, baseline.baseline_id, first.receipt_id, second.receipt_id)
            windows = self.sample['windows']
            new_base = create_baseline_revision(center, baseline.baseline_id, 'BASE-02',
                                               {windows[0]: 0, windows[1]: 2})
            new = issue_fixed(center, new_base.baseline_id, first.receipt_id, second.receipt_id)
            self.assertEqual((new.baseline_kwh, new.usage_kwh, new.peak_kw),
                             ((0, 2), (1, 4), 16))
        with Store(self.center_path) as center:
            self.assertEqual(read_report(center, original.report_id), original)
            self.assertEqual(get_frozen_baseline(center, baseline.baseline_id).values, (1, 0))
            self.assertEqual(read_report(center, new.report_id).baseline_id, 'BASE-02')

    def test_legacy_store_rows_and_original_entry_points(self):
        with Store(self.center_path) as center:
            center.connection.executescript((SAMPLE_DIR / 'legacy.sql').read_text(encoding='utf-8'))
        with Store(self.center_path) as center:
            old = read_report(center, 'rp-1')
            self.assertEqual((old.usage_kwh, old.peak_kw, old.over_limit), ((2, 2), 8, False))
            self.assertEqual(old.ack, 'ra-1')
            self.assertEqual(get_report_receipt(center, 'rp-1'), 'ra-1')
            self.assertEqual(get_frozen_baseline(center, 'BASE-01').values, (1, 0))
            first, second = (get_receipt(center, source.receipt_id) for source in old.receipts)
            station_raw = self.station_packets()
            self.assertEqual((first.raw, second.raw), station_raw)
            self.assertEqual(accept_packet(center, first.raw), first)
            self.assertEqual(accept_packet(center, second.raw), second)
            self.assertEqual(count_receipts(center), 2)
            self.assertEqual(report_counts(center), (1, 1))
            again = issue_fixed(center, 'BASE-01', first.receipt_id, second.receipt_id)
            self.assertEqual((again.report_id, again.peak_kw, again.receipts), ('rp-2', 8, old.receipts))
            self.assertEqual(read_report(center, 'rp-1'), old)
            self.assertEqual(report_counts(center), (2, 2))
            payload = json.loads(export_report(center, 'rp-1'))
            self.assertEqual(payload['ack'], 'ra-1')
            self.assertEqual(payload['receipts'][0]['receipt_id'], first.receipt_id)
