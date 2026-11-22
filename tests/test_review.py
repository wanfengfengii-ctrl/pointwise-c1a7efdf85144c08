import json
import sqlite3

from demo import collect_station
from metering import Store, accept_packet, correct_station, define_shift, export_report
from metering import get_receipt, get_report_receipt, issue_fixed, read_report
from review.history import report_counts
from tests.support import OfflineShiftCase, allow_report_commit, fail_report_commit
from tests.support import reopened_counts, scenario


class ReviewTests(OfflineShiftCase):
    def test_fixed_peak_and_verdict_after_shutdown(self):
        with Store(self.center_path) as center:
            baseline, first, second = self.prepare_receipts(center)
            report = issue_fixed(center, baseline.baseline_id, second.receipt_id, first.receipt_id)
            self.assertEqual(report.windows, tuple(self.sample['windows']))
            self.assertEqual(report.baseline_kwh, (1, 0))
            self.assertEqual(report.usage_kwh, (2, 2))
            self.assertEqual(report.window_kw, (8, 8))
            self.assertEqual((report.peak_kw, report.limit_kw, report.over_limit), (8, 8, False))
            self.assertEqual(tuple(source.receipt_id for source in report.receipts),
                             (first.receipt_id, second.receipt_id))
            self.assertEqual(tuple(source.packet_id for source in report.receipts),
                             (first.packet_id, second.packet_id))
            self.assertEqual(tuple(source.ack for source in report.receipts), (first.ack, second.ack))
            self.assertEqual(tuple(source.fingerprint for source in report.receipts),
                             (first.fingerprint, second.fingerprint))
        with Store(self.center_path) as center:
            actual = read_report(center, report.report_id)
            self.assertEqual(actual, report)
            self.assertEqual(get_report_receipt(center, report.report_id), report.ack)
            exported = json.loads(export_report(center, report.report_id))
            self.assertEqual(exported['peak_kw'], 8)
            self.assertEqual(exported['usage_kwh'], [2, 2])
        scenario('fixed_peak', {'baseline': [1, 0], 'a': [1, 0], 'b': [0, 2], 'limit': 8},
                 [[2, 2], 8, False], [report.usage_kwh, report.peak_kw, report.over_limit],
                 [[2, 2], 8, [first.receipt_id, second.receipt_id]],
                 [exported['usage_kwh'], exported['peak_kw'],
                  [source['receipt_id'] for source in exported['receipts']]],
                 ['exchange/selection.py', 'review/peak.py', 'review/issue.py', 'review/history.py',
                  'review/export.py'],
                 '(1+1+0, 0+0+2) gives (2,2). Each 2 kWh window gives 8 kW, equal to the limit.')

    def test_same_station_rejects_duplicate_station(self):
        with Store(self.center_path) as center:
            baseline, first, _ = self.prepare_receipts(center)
            change = self.sample['correction']
            with Store(self.station_paths[0]) as station:
                corrected = correct_station(station, change['parent'], change['revision_id'],
                                            {change['ticket_id']: (change['window'], change['kwh'])})
            other = accept_packet(center, corrected.packet)
            self.assertNotEqual(first.receipt_id, other.receipt_id)
            with self.assertRaises(ValueError) as rejected:
                issue_fixed(center, baseline.baseline_id, first.receipt_id, other.receipt_id)
            counts = report_counts(center)
            self.assertEqual(counts, (0, 0))
            self.assertEqual(get_receipt(center, first.receipt_id), first)
            self.assertEqual(get_receipt(center, other.receipt_id), other)
        scenario('same_station', {'revisions': [first.revision_id, other.revision_id],
                                  'stations': [first.station, other.station]},
                 'ValueError', type(rejected.exception).__name__, (0, 0), counts,
                 ['exchange/selection.py', 'review/issue.py', 'review/history.py'],
                 'The contract requires both stations, so two closed revisions from one station cannot be signed.')

    def test_mixed_shift_and_unknown_ids(self):
        with Store(self.center_path) as center:
            baseline, first, _ = self.prepare_receipts(center)
            other_sample = {**self.sample, 'shift_id': 'S-02'}
            define_shift(center, 'C-17', 'S-02', other_sample['stations'], 8, other_sample['windows'])
            raw = collect_station(self.root / 'other.sqlite', other_sample,
                                  other_sample['station_inputs'][1])
            foreign = accept_packet(center, raw)
            with self.assertRaises(ValueError):
                issue_fixed(center, baseline.baseline_id, first.receipt_id, foreign.receipt_id)
            with self.assertRaises(KeyError):
                issue_fixed(center, baseline.baseline_id, first.receipt_id, 'rc-unknown')
            with self.assertRaises(KeyError):
                issue_fixed(center, 'BASE-unknown', first.receipt_id, foreign.receipt_id)
            with self.assertRaises(KeyError):
                read_report(center, 'rp-100')
            with self.assertRaises(ValueError):
                read_report(center, '')
            self.assertEqual(report_counts(center), (0, 0))

    def test_rollback_atomic_retry(self):
        with Store(self.center_path) as center:
            baseline, first, second = self.prepare_receipts(center)
            arguments = baseline.baseline_id, first.receipt_id, second.receipt_id
            fail_report_commit(center)
            with self.assertRaises(sqlite3.IntegrityError) as failed:
                issue_fixed(center, *arguments)
            self.assertEqual(failed.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
            self.assertFalse(center.connection.in_transaction)
            counts_at_failure = report_counts(center)
            self.assertEqual(counts_at_failure, (0, 0))
            self.assertEqual(reopened_counts(self.center_path), (0, 0))
            with self.assertRaises(KeyError):
                get_report_receipt(center, 'rp-1')
            allow_report_commit(center)
            saved = issue_fixed(center, *arguments)
            self.assertEqual(report_counts(center), (1, 1))
            self.assertEqual(saved.peak_kw, 8)
        with Store(self.center_path) as center:
            reopened = read_report(center, saved.report_id)
            ack = get_report_receipt(center, saved.report_id)
            self.assertEqual(reopened, saved)
            self.assertEqual(ack, saved.ack)
        scenario('rollback', {'baseline_id': arguments[0], 'receipt_ids': arguments[1:],
                              'failure': 'deferred foreign key at commit'},
                 [0, 0], counts_at_failure, [8, True], [reopened.peak_kw, ack == saved.ack],
                 ['review/issue.py', 'review/history.py', 'store.py'],
                 'A failed SQLite commit leaves neither row. The same inputs can then sign the hand-calculated 8 kW report.')
