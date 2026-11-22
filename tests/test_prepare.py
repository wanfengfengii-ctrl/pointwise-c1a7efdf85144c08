from unittest import TestCase

from baseline.coverage import baseline_is_complete, missing_windows
from baseline.freeze import frozen_baseline_exists
from demo import define_sample_shift, load_sample
from metering import (
    Store, amend_shift, begin_baseline, create_baseline_revision, define_shift,
    freeze_baseline, get_baseline_revision, get_frozen_baseline, get_shift,
    list_baseline_revisions, list_shift_windows, read_baseline_draft, record_baseline_value,
)
from tests.support import scenario


class PrepareTests(TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.sample = load_sample()
        self.shift = define_sample_shift(self.store, self.sample)
        self.first, self.second = self.shift.windows

    def test_zero_value_is_present(self):
        begin_baseline(self.store, 'S-01', 'BD-01')
        record_baseline_value(self.store, 'BD-01', self.first, 1)
        draft = record_baseline_value(self.store, 'BD-01', self.second, 0)
        self.assertTrue(baseline_is_complete(self.shift.windows, draft.values))
        self.assertEqual(missing_windows(self.shift.windows, draft.values), ())
        frozen = freeze_baseline(self.store, 'BD-01', 'BASE-01')
        readback = get_frozen_baseline(self.store, 'BASE-01')
        self.assertEqual(frozen.values, (1, 0))
        self.assertEqual(readback, frozen)
        self.assertEqual(freeze_baseline(self.store, 'BD-01', 'BASE-01'), frozen)
        with self.assertRaises(ValueError):
            record_baseline_value(self.store, 'BD-01', self.second, 2)
        with self.assertRaises(ValueError):
            amend_shift(self.store, 'S-01', self.shift.stations, 9, self.shift.windows)
        scenario('base_zero', {self.first: 1, self.second: 0}, (1, 0), frozen.values,
                 (1, 0), readback.values,
                 ['baseline/register.py', 'baseline/coverage.py', 'baseline/freeze.py'],
                 'Reads are explicit per window. The second reading is the integer zero.')

    def test_partial_freeze_rejected(self):
        begin_baseline(self.store, 'S-01', 'BD-01')
        record_baseline_value(self.store, 'BD-01', self.first, 1)
        draft = read_baseline_draft(self.store, 'BD-01')
        missing = missing_windows(self.shift.windows, draft.values)
        self.assertEqual(missing, (self.second,))
        with self.assertRaises(ValueError) as rejected:
            freeze_baseline(self.store, 'BD-01', 'BASE-01')
        before = list_baseline_revisions(self.store, 'S-01')
        self.assertEqual(before, ())
        self.assertFalse(frozen_baseline_exists(self.store, 'BASE-01'))
        self.assertIsNone(read_baseline_draft(self.store, 'BD-01').frozen_id)
        amend_shift(self.store, 'S-01', self.shift.stations, 8, self.shift.windows)
        record_baseline_value(self.store, 'BD-01', self.second, 0)
        saved = freeze_baseline(self.store, 'BD-01', 'BASE-01')
        self.assertEqual(saved.values, (1, 0))
        scenario('base_gap', {self.first: 1}, 'ValueError', type(rejected.exception).__name__,
                 [0, [1, 0]], [len(before), saved.values],
                 ['baseline/coverage.py', 'baseline/freeze.py', 'baseline/revisions.py'],
                 'The absent second key blocks freezing before version creation. Filling it allows retry.')

    def test_adjacent_windows_and_overlap(self):
        explicit = ((self.first, self.second), (self.second, '2026-10-05T08:30'))
        self.assertEqual(define_shift(self.store, 'C-17', 'S-01', self.shift.stations, 8,
                                      explicit), self.shift)
        for windows in [(self.first, '2026-10-05T08:14'), (self.second, self.first),
                        ((self.first, '2026-10-05T08:16'),), (self.first, self.first)]:
            with self.subTest(windows=windows), self.assertRaises(ValueError):
                define_shift(self.store, 'C-17', 'S-99', self.shift.stations, 8, windows)
        with self.assertRaises(KeyError):
            get_shift(self.store, 'S-99')
        with self.assertRaises(ValueError):
            define_shift(self.store, 'C-17', 'S-01', self.shift.stations, 7, self.shift.windows)
        self.assertEqual(list_shift_windows(self.store, 'S-01'), (self.first, self.second))

    def test_amendment_preserves_recorded_window(self):
        begin_baseline(self.store, 'S-01', 'BD-01')
        record_baseline_value(self.store, 'BD-01', self.first, 1)
        with self.assertRaises(ValueError):
            amend_shift(self.store, 'S-01', self.shift.stations, 9, (self.second,))
        self.assertEqual(get_shift(self.store, 'S-01'), self.shift)
        new = amend_shift(self.store, 'S-01', self.shift.stations, 9,
                          (self.first, '2026-10-05T08:30'))
        self.assertEqual(new.windows, (self.first, '2026-10-05T08:30'))
        self.assertEqual(read_baseline_draft(self.store, 'BD-01').values, {self.first: 1})

    def test_baseline_revision_is_complete_and_immutable(self):
        begin_baseline(self.store, 'S-01', 'BD-01')
        for bad in (-1, 0.5, True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                record_baseline_value(self.store, 'BD-01', self.first, bad)
        record_baseline_value(self.store, 'BD-01', self.first, 1)
        record_baseline_value(self.store, 'BD-01', self.second, 0)
        old = freeze_baseline(self.store, 'BD-01', 'BASE-01')
        with self.assertRaises(ValueError):
            create_baseline_revision(self.store, old.baseline_id, 'BASE-02', {self.first: 0})
        self.assertFalse(frozen_baseline_exists(self.store, 'BASE-02'))
        new = create_baseline_revision(self.store, old.baseline_id, 'BASE-02',
                                       {self.first: 0, self.second: 2})
        self.assertEqual((new.parent_id, new.values), ('BASE-01', (0, 2)))
        self.assertEqual(get_baseline_revision(self.store, 'BASE-01'), old)
        self.assertEqual(list_baseline_revisions(self.store, 'S-01'), (old, new))
        with self.assertRaises(KeyError):
            create_baseline_revision(self.store, 'BASE-99', 'BASE-03', {})
