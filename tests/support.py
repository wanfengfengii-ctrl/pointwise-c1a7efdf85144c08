import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from demo import collect_station, load_sample, prepare_center
from metering import Store, accept_packet


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual,
             code_paths, oracle):
    record = dict(case_id=case_id, input=inputs, expected=expected, actual=actual,
                  downstream_expected=downstream_expected, downstream_actual=downstream_actual,
                  code_paths=code_paths, oracle=oracle)
    print('POINTWISE_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True))


class OfflineShiftCase(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='haijia-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.center_path = self.root / 'center.sqlite'
        self.station_paths = (self.root / 'a.sqlite', self.root / 'b.sqlite')
        self.sample = load_sample()

    def station_packets(self):
        return tuple(collect_station(path, self.sample, station) for path, station in
                     zip(self.station_paths, self.sample['station_inputs'], strict=True))

    def prepare_receipts(self, center):
        baseline = prepare_center(center, self.sample)
        first, second = (accept_packet(center, raw) for raw in self.station_packets())
        return baseline, first, second


def fail_report_commit(store):
    """The deferred reference fails at COMMIT after both report rows are written."""
    store.connection.executescript('''
        CREATE TEMP TABLE issue_gate (report_id TEXT PRIMARY KEY);
        CREATE TEMP TABLE blocked_acks (
            report_id TEXT REFERENCES issue_gate(report_id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE TEMP TRIGGER fail_report_commit AFTER INSERT ON main.report_acks
        BEGIN
            INSERT INTO blocked_acks(report_id) VALUES (NEW.report_id);
        END;
    ''')


def allow_report_commit(store):
    store.connection.execute('DROP TRIGGER temp.fail_report_commit')


def reopened_counts(path):
    from review.history import report_counts

    with Store(path) as store:
        return report_counts(store)
