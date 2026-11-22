import json
import sqlite3

from codec import json_bytes
from demo import SAMPLE_DIR, define_sample_shift, prepare_center
from metering import (
    SparseReportRecord, Store, Ticket, accept_packet, begin_station,
    build_station_packet, close_station, correct_station_sparse,
    count_receipts, decode_sparse_packet, export_report, find_receipt, get_receipt,
    get_report_receipt, get_station_revision, issue_fixed, issue_sparse,
    list_station_revisions, read_report, read_station_packet, record_tickets,
)
from review.history import report_counts
from tests.support import OfflineShiftCase, allow_report_commit, fail_report_commit, scenario


def load_sparse_sample():
    return json.loads((SAMPLE_DIR / 'sparse-shift.json').read_text(encoding='utf-8'))


def seal_sparse_station(sample, history=None):
    """Return every sealed packet for station A built from the named history."""
    sample_input = sample['station_inputs'][0]
    history = sample['corrections'] if history is None else history
    with Store(':memory:') as station:
        shift = define_sample_shift(station, sample)
        code = sample_input['station']
        begin_station(station, shift.shift_id, code, sample_input['revision_id'])
        record_tickets(station, shift.shift_id, code,
                       [Ticket(*row) for row in sample_input['tickets']])
        close_station(station, shift.shift_id, code, sample_input['revision_id'])
        packets = {sample_input['revision_id']:
                   build_station_packet(station, sample_input['revision_id'])}
        for entry in history:
            revised = correct_station_sparse(
                station, entry['parent'], entry['revision'],
                {ticket_id: tuple(change)
                 for ticket_id, change in entry['tickets'].items()},
            )
            packets[revised.revision_id] = build_station_packet(station, revised.revision_id)
        return packets


def seal_other_station(sample):
    sample_input = sample['station_inputs'][1]
    with Store(':memory:') as station:
        shift = define_sample_shift(station, sample)
        code = sample_input['station']
        begin_station(station, shift.shift_id, code, sample_input['revision_id'])
        record_tickets(station, shift.shift_id, code,
                       [Ticket(*row) for row in sample_input['tickets']])
        close_station(station, shift.shift_id, code, sample_input['revision_id'])
        return build_station_packet(station, sample_input['revision_id'])


class SparseStationTests(OfflineShiftCase):
    def setUp(self):
        super().setUp()
        self.sparse_sample = load_sparse_sample()

    def test_sparse_revision_seals_only_changed_windows_with_branch_evidence(self):
        packets = seal_sparse_station(self.sparse_sample)
        a1 = decode_sparse_packet(packets['A1'])
        self.assertEqual(a1.kind, 'sparse')
        self.assertEqual(a1.version, 2)
        self.assertEqual(a1.anchor_id, 'A0')
        self.assertEqual(a1.parent_id, 'A0')
        self.assertEqual([change.window for change in a1.changes],
                         ['2026-10-06T08:15'])
        self.assertEqual(a1.changes[0].kwh, 7)
        self.assertEqual(a1.changes[0].ticket_ids, ('A-t2',))
        self.assertEqual([entry.revision_id for entry in a1.branch], ['A1'])
        a2 = decode_sparse_packet(packets['A2'])
        self.assertEqual(a2.anchor_id, 'A0')
        self.assertEqual(a2.parent_id, 'A1')
        self.assertEqual([entry.revision_id for entry in a2.branch], ['A1', 'A2'])
        self.assertEqual(
            {entry.revision_id: entry.changed_windows for entry in a2.branch},
            {'A1': ('2026-10-06T08:15',),
             'A2': ('2026-10-06T08:15', '2026-10-06T08:30')},
        )
        self.assertEqual([change.kwh for change in a2.changes], [0, 4])
        # The sparse packet never carries untouched windows or full tickets.
        self.assertEqual(len(a2.changes), 2)
        self.assertTrue(all(len(change.ticket_ids) >= 1 for change in a2.changes))

    def test_zero_and_same_value_corrections_are_still_explicit(self):
        sample = self.sparse_sample
        with Store(':memory:') as station:
            shift = define_sample_shift(station, sample)
            code = sample['station_inputs'][0]['station']
            begin_station(station, shift.shift_id, code, 'A0')
            record_tickets(station, shift.shift_id, code,
                           [Ticket(*row) for row in sample['station_inputs'][0]['tickets']])
            close_station(station, shift.shift_id, code, 'A0')
            zero_rev = correct_station_sparse(
                station, 'A0', 'Z1', {'A-t2': ('2026-10-06T08:15', 0)})
            same_rev = correct_station_sparse(
                station, 'A0', 'Z2', {'A-t3': ('2026-10-06T08:30', 3)})
            self.assertTrue(zero_rev.sparse and same_rev.sparse)
            self.assertEqual(zero_rev.changed_windows, ('2026-10-06T08:15',))
            self.assertEqual(same_rev.changed_windows, ('2026-10-06T08:30',))
            self.assertEqual(zero_rev.usage_kwh, (1, 0, 3))
            self.assertEqual(same_rev.usage_kwh, (1, 2, 3))
            self.assertEqual(
                read_station_packet(station, zero_rev.packet_id), zero_rev.packet)
            self.assertEqual(build_station_packet(station, 'Z2'), same_rev.packet)

    def test_sparse_keeps_full_effective_tickets_and_reuses_anchor(self):
        sample = self.sparse_sample
        with Store(':memory:') as station:
            shift = define_sample_shift(station, sample)
            code = sample['station_inputs'][0]['station']
            begin_station(station, shift.shift_id, code, 'A0')
            record_tickets(station, shift.shift_id, code,
                           [Ticket(*row) for row in sample['station_inputs'][0]['tickets']])
            close_station(station, shift.shift_id, code, 'A0')
            a1 = correct_station_sparse(
                station, 'A0', 'A1', {'A-t2': ('2026-10-06T08:15', 7)})
            a2 = correct_station_sparse(
                station, 'A1', 'A2',
                {'A-t2': ('2026-10-06T08:15', 0),
                 'A-t3': ('2026-10-06T08:30', 4)})
            self.assertEqual(a1.anchor_id, 'A0')
            self.assertEqual(a2.anchor_id, 'A0')
            self.assertEqual(a1.parent_id, 'A0')
            self.assertEqual(a2.parent_id, 'A1')
            self.assertEqual(tuple(ticket.ticket_id for ticket in a2.tickets),
                             ('A-t1', 'A-t2', 'A-t3'))
            self.assertEqual(a2.usage_kwh, (1, 0, 4))
            # Fixed-style correction errors still apply.
            with self.assertRaises(ValueError):
                correct_station_sparse(station, 'A1', 'A-bad',
                                       {'A-other': ('2026-10-06T08:15', 1)})
            with self.assertRaises(ValueError):
                correct_station_sparse(station, 'A1', 'A-bad',
                                       {'A-t2': ('2026-10-06T08:30', 1)})
            with self.assertRaises(KeyError):
                correct_station_sparse(station, 'A-unknown', 'A-bad',
                                       {'A-t2': ('2026-10-06T08:15', 1)})
            with self.assertRaises(ValueError):
                correct_station_sparse(station, 'A1', 'A1',
                                       {'A-t2': ('2026-10-06T08:15', 1)})
            self.assertEqual(
                [revision.revision_id for revision in
                 list_station_revisions(station, shift.shift_id, code)],
                ['A0', 'A1', 'A2'])

    def test_sparse_packets_survive_station_reopen_and_keep_original_bytes(self):
        sample = self.sparse_sample
        station_path = self.root / 'alpha.sqlite'
        with Store(station_path) as station:
            shift = define_sample_shift(station, sample)
            code = sample['station_inputs'][0]['station']
            begin_station(station, shift.shift_id, code, 'A0')
            record_tickets(station, shift.shift_id, code,
                           [Ticket(*row) for row in sample['station_inputs'][0]['tickets']])
            close_station(station, shift.shift_id, code, 'A0')
            entry = sample['corrections'][0]
            correct_station_sparse(
                station, entry['parent'], entry['revision'],
                {ticket_id: tuple(change)
                 for ticket_id, change in entry['tickets'].items()})
        with Store(station_path) as station:
            revision = get_station_revision(station, 'A1')
            self.assertTrue(revision.sparse)
            self.assertEqual(revision.anchor_id, 'A0')
            self.assertEqual(build_station_packet(station, 'A1'), revision.packet)
            self.assertEqual(read_station_packet(station, revision.packet_id),
                             revision.packet)
            self.assertEqual(decode_sparse_packet(revision.packet).revision_id, 'A1')

    def test_malformed_sparse_packets_are_rejected(self):
        packets = seal_sparse_station(self.sparse_sample)
        payload = json.loads(packets['A1'].decode('utf-8'))
        bad_payloads = (
            {**payload, 'version': 1}, {**payload, 'kind': 'fixed'},
            {**payload, 'closed': False}, {**payload, 'anchor_id': 'A1'},
            {**payload, 'changes': []},
            {**payload, 'branch': [{**payload['branch'][0], 'parent_id': 'A9'}]},
            {**payload, 'changes': [{**payload['changes'][0], 'kwh': -1}]},
            {**payload, 'changes': [{**payload['changes'][0], 'ticket_ids': []}]},
        )
        for item in bad_payloads:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    decode_sparse_packet(json_bytes(item))
        with self.assertRaises(ValueError):
            decode_sparse_packet(b'not-json')


class SparseAcceptanceTests(OfflineShiftCase):
    def setUp(self):
        super().setUp()
        self.sparse_sample = load_sparse_sample()
        self.packets = seal_sparse_station(self.sparse_sample)
        self.beta_packet = seal_other_station(self.sparse_sample)

    def test_out_of_order_acceptance_replay_and_conflict(self):
        with Store(self.center_path) as center:
            prepare_center(center, self.sparse_sample)
            # Sparse A2 is received before anchor A0 and the other station.
            target = accept_packet(center, self.packets['A2'])
            anchor = accept_packet(center, self.packets['A0'])
            other = accept_packet(center, self.beta_packet)
            self.assertEqual(count_receipts(center), 3)
            # Identical bytes re-delivered return the first receipt.
            self.assertEqual(accept_packet(center, self.packets['A2']), target)
            self.assertEqual(find_receipt(center, target.packet_id), target)
            self.assertEqual(get_receipt(center, anchor.receipt_id).raw,
                             self.packets['A0'])
            self.assertEqual(count_receipts(center), 3)
            # Same packet number with different content is rejected.
            payload = json.loads(self.packets['A2'].decode('utf-8'))
            altered = dict(payload)
            altered['changes'] = [dict(change, kwh=9) for change in payload['changes']]
            with self.assertRaises(ValueError):
                accept_packet(center, json_bytes(altered))
            self.assertEqual(count_receipts(center), 3)
            scenario('sparse_replay', {'revision': target.revision_id},
                     3, count_receipts(center), 3, count_receipts(center),
                     ['exchange/accept.py', 'exchange/identity.py', 'station/sparse.py'],
                     'Out-of-order sparse originals keep one receipt and reject same-id variants.')

    def test_sparse_packet_for_unregistered_shift_is_rejected(self):
        with Store(self.center_path) as center:
            define_sample_shift(center, self.sparse_sample)
            foreign_sample = {**self.sparse_sample, 'shift_id': 'S-99'}
            foreign = seal_sparse_station(foreign_sample)
            with self.assertRaises(ValueError):
                accept_packet(center, foreign['A1'])
            self.assertEqual(count_receipts(center), 0)


class SparseReviewTests(OfflineShiftCase):
    def setUp(self):
        super().setUp()
        self.sparse_sample = load_sparse_sample()
        self.packets = seal_sparse_station(self.sparse_sample)
        self.beta_packet = seal_other_station(self.sparse_sample)

    def _center_with(self, center, revisions):
        baseline = prepare_center(center, self.sparse_sample)
        receipts = {}
        for revision in revisions:
            raw = self.beta_packet if revision == 'B0' else self.packets[revision]
            receipts[revision] = accept_packet(center, raw)
        return baseline, receipts

    def test_missing_intermediate_signs_when_all_its_windows_are_covered(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(
                center, ('A2', 'A0', 'B0', 'P', 'A3'))
            report = issue_sparse(
                center, baseline.baseline_id, receipts['A0'].receipt_id,
                receipts['A2'].receipt_id, receipts['B0'].receipt_id)
            self.assertIsInstance(report, SparseReportRecord)
            self.assertEqual(report.usage_kwh, (1, 0, 4))
            self.assertEqual(report.window_kw, (4, 0, 16))
            self.assertEqual((report.peak_kw, report.limit_kw, report.over_limit),
                             (16, 16, False))
            alpha_ids = tuple(pair[0] for pair in report.window_receipts)
            self.assertEqual(alpha_ids, (receipts['A0'].receipt_id,
                                         receipts['A2'].receipt_id,
                                         receipts['A2'].receipt_id))
            self.assertTrue(all(pair[1] == receipts['B0'].receipt_id
                                for pair in report.window_receipts))
            self.assertEqual(report.anchor_receipt_id, receipts['A0'].receipt_id)
            self.assertEqual(report.target_receipt_id, receipts['A2'].receipt_id)
            self.assertEqual(report.other_receipt_id, receipts['B0'].receipt_id)
            # P is a valid target on its own branch off A0, but it can never
            # substitute for the missing A1 on A3's target branch.
            p_report = issue_sparse(
                center, baseline.baseline_id, receipts['A0'].receipt_id,
                receipts['P'].receipt_id, receipts['B0'].receipt_id)
            self.assertEqual(p_report.usage_kwh, (1, 7, 3))
            with self.assertRaises(ValueError):
                issue_sparse(center, baseline.baseline_id, receipts['A0'].receipt_id,
                             receipts['A3'].receipt_id, receipts['B0'].receipt_id)
            scenario('sparse_covered_gap', {'target': 'A2', 'missing': ['A1']},
                     [1, 0, 4], list(report.usage_kwh),
                     ['A0', 'A2', 'A2'],
                     [get_receipt(center, rid).revision_id for rid in alpha_ids],
                     ['review/sparse.py', 'exchange/selection.py', 'station/sparse.py'],
                     'A1 only changed window 2, which A2 changes again, so the covered gap signs.')

    def test_still_supplying_original_blocks_signing_until_backfilled(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(
                center, ('A2', 'A0', 'B0', 'A3', 'A4'))
            with self.assertRaises(ValueError) as rejected:
                issue_sparse(center, baseline.baseline_id, receipts['A0'].receipt_id,
                             receipts['A3'].receipt_id, receipts['B0'].receipt_id)
            # A failed signing leaves no report or acknowledgment.
            self.assertEqual(report_counts(center), (0, 0))
            backfill = accept_packet(center, self.packets['A1'])
            report = issue_sparse(
                center, baseline.baseline_id, receipts['A0'].receipt_id,
                receipts['A3'].receipt_id, receipts['B0'].receipt_id)
            self.assertEqual((report.usage_kwh, report.peak_kw, report.over_limit),
                             ((1, 7, 4), 28, True))
            self.assertEqual(
                tuple(pair[0] for pair in report.window_receipts),
                (receipts['A0'].receipt_id, backfill.receipt_id,
                 receipts['A3'].receipt_id))
            scenario('sparse_backfill', {'target': 'A3', 'backfilled': 'A1'},
                     'ValueError', type(rejected.exception).__name__,
                     (1, 7, 4), report.usage_kwh,
                     ['review/sparse.py', 'review/history.py'],
                     'Window 2 still needed A1; delivering it lets A3 sign at 28 kW over limit.')

    def test_same_value_correction_switches_the_window_source(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(center, ('A0', 'B0', 'A4'))
            report = issue_sparse(
                center, baseline.baseline_id, receipts['A0'].receipt_id,
                receipts['A4'].receipt_id, receipts['B0'].receipt_id)
            self.assertEqual((report.usage_kwh, report.peak_kw, report.over_limit),
                             ((1, 2, 3), 12, False))
            self.assertEqual(
                tuple(pair[0] for pair in report.window_receipts),
                (receipts['A0'].receipt_id, receipts['A0'].receipt_id,
                 receipts['A4'].receipt_id))

    def test_comparison_history_requires_its_own_branch_original(self):
        comparison = seal_sparse_station(
            self.sparse_sample, self.sparse_sample['comparison_history'])
        with Store(':memory:') as center:
            baseline = prepare_center(center, self.sparse_sample)
            anchor = accept_packet(center, comparison['A0'])
            target = accept_packet(center, comparison['A2'])
            other = accept_packet(center, self.beta_packet)
            with self.assertRaises(ValueError):
                issue_sparse(center, baseline.baseline_id, anchor.receipt_id,
                             target.receipt_id, other.receipt_id)
            self.assertEqual(report_counts(center), (0, 0))

    def test_fixed_report_rejects_sparse_packets_and_unknown_ids_raise_keyerror(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(center, ('A0', 'A2', 'B0'))
            with self.assertRaises(ValueError):
                issue_fixed(center, baseline.baseline_id,
                            receipts['A2'].receipt_id, receipts['B0'].receipt_id)
            kwargs = dict(baseline_id=baseline.baseline_id,
                          anchor_receipt=receipts['A0'].receipt_id,
                          target_receipt=receipts['A2'].receipt_id,
                          other_receipt=receipts['B0'].receipt_id)
            for name, value in (('baseline_id', 'BASE-nope'),
                                ('anchor_receipt', 'rc-nope'),
                                ('target_receipt', 'rc-nope2'),
                                ('other_receipt', 'rc-nope3')):
                broken = dict(kwargs, **{name: value})
                with self.assertRaises(KeyError):
                    issue_sparse(center, **broken)
            with self.assertRaises(ValueError):
                issue_sparse(center, kwargs['baseline_id'],
                             receipts['A0'].receipt_id, receipts['A0'].receipt_id,
                             receipts['B0'].receipt_id)
            self.assertEqual(report_counts(center), (0, 0))

    def test_target_naming_another_anchor_is_rejected(self):
        # A sparse target whose branch names another anchor cannot be reviewed
        # against the selected anchor even when both originals are on the shift.
        foreign_station = {**self.sparse_sample,
                           'station_inputs': [{**self.sparse_sample['station_inputs'][0],
                                               'revision_id': 'C0'}]}
        other_anchor_packets = seal_sparse_station(
            foreign_station,
            [{'parent': 'C0', 'revision': 'C1',
              'tickets': {'A-t1': (self.sparse_sample['windows'][0], 5)}}])
        with Store(':memory:') as center:
            baseline = prepare_center(center, self.sparse_sample)
            anchor = accept_packet(center, self.packets['A0'])
            other = accept_packet(center, self.beta_packet)
            accept_packet(center, other_anchor_packets['C0'])
            foreign_target = accept_packet(center, other_anchor_packets['C1'])
            with self.assertRaises(ValueError):
                issue_sparse(center, baseline.baseline_id, anchor.receipt_id,
                             foreign_target.receipt_id, other.receipt_id)
            self.assertEqual(report_counts(center), (0, 0))

    def test_wrong_station_and_wrong_kind_receipts_are_rejected(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(center, ('A0', 'A1', 'B0'))
            # The other-station receipt cannot serve as the anchor.
            with self.assertRaises(ValueError):
                issue_sparse(center, baseline.baseline_id, receipts['B0'].receipt_id,
                             receipts['A1'].receipt_id, receipts['B0'].receipt_id)
            # The fixed anchor cannot serve as the sparse target.
            with self.assertRaises(ValueError):
                issue_sparse(center, baseline.baseline_id, receipts['A0'].receipt_id,
                             receipts['A0'].receipt_id, receipts['B0'].receipt_id)
            # A sparse packet cannot serve as the other full-shift station.
            with self.assertRaises(ValueError):
                issue_sparse(center, baseline.baseline_id, receipts['A0'].receipt_id,
                             receipts['A1'].receipt_id, receipts['A1'].receipt_id)

    def test_reopen_keeps_signed_usage_sources_and_receipts(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(center, ('A2', 'A0', 'B0', 'A1'))
            first = issue_sparse(
                center, baseline.baseline_id, receipts['A0'].receipt_id,
                receipts['A2'].receipt_id, receipts['B0'].receipt_id)
            second = issue_sparse(
                center, baseline.baseline_id, receipts['A0'].receipt_id,
                receipts['A1'].receipt_id, receipts['B0'].receipt_id)
            saved = (first, second)
        with Store(self.center_path) as center:
            for original in saved:
                reopened = read_report(center, original.report_id)
                self.assertEqual(reopened, original)
                self.assertEqual(get_report_receipt(center, original.report_id),
                                 original.ack)
            payload = json.loads(export_report(center, first.report_id))
            self.assertEqual(payload['window_receipts'],
                             [list(pair) for pair in first.window_receipts])
            csv_text = export_report(center, first.report_id, 'csv')
            self.assertEqual(len(csv_text.strip().splitlines()), 4)
            # Legacy fixed reports remain readable in the same reopened store.
            fixed = issue_fixed(center, baseline.baseline_id, receipts['A0'].receipt_id,
                                receipts['B0'].receipt_id)
            self.assertNotIsInstance(fixed, SparseReportRecord)
            self.assertEqual(read_report(center, fixed.report_id), fixed)

    def test_sparse_rollback_leaves_no_report_and_can_retry(self):
        with Store(self.center_path) as center:
            baseline, receipts = self._center_with(center, ('A2', 'A0', 'B0'))
            arguments = (baseline.baseline_id, receipts['A0'].receipt_id,
                         receipts['A2'].receipt_id, receipts['B0'].receipt_id)
            fail_report_commit(center)
            with self.assertRaises(sqlite3.IntegrityError) as failed:
                issue_sparse(center, *arguments)
            self.assertEqual(failed.exception.sqlite_errorcode,
                             sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
            self.assertFalse(center.connection.in_transaction)
            self.assertEqual(report_counts(center), (0, 0))
            allow_report_commit(center)
            report = issue_sparse(center, *arguments)
            self.assertEqual(report_counts(center), (1, 1))
            self.assertEqual(report.peak_kw, 16)
            # Already received station packets remain reclaimable after failure.
            self.assertEqual(get_receipt(center, receipts['A2'].receipt_id),
                             receipts['A2'])
