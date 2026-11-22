import json
from pathlib import Path
from tempfile import TemporaryDirectory

from metering import (
    Store, Ticket, accept_packet, begin_baseline, begin_station, build_station_packet,
    close_station, correct_station, define_shift, export_report, freeze_baseline,
    issue_fixed, read_report, record_baseline_value, record_tickets,
)


SAMPLE_DIR = Path(__file__).resolve().parent / 'samples'


def load_sample():
    return json.loads((SAMPLE_DIR / 'two-station.json').read_text(encoding='utf-8'))


def define_sample_shift(store, sample):
    return define_shift(store, sample['contract_id'], sample['shift_id'], sample['stations'],
                        sample['limit_kw'], sample['windows'])


def prepare_center(store, sample):
    shift = define_sample_shift(store, sample)
    draft_id = sample['draft_id']
    begin_baseline(store, shift.shift_id, draft_id)
    for window, value in zip(shift.windows, sample['baseline_kwh'], strict=True):
        record_baseline_value(store, draft_id, window, value)
    return freeze_baseline(store, draft_id, sample['baseline_id'])


def collect_station(path, sample, station_input):
    with Store(path) as store:
        shift = define_sample_shift(store, sample)
        station = station_input['station']
        revision_id = station_input['revision_id']
        begin_station(store, shift.shift_id, station, revision_id)
        tickets = tuple(Ticket(*item) for item in station_input['tickets'])
        record_tickets(store, shift.shift_id, station, tickets)
        closed = close_station(store, shift.shift_id, station, revision_id)
        return build_station_packet(store, closed.revision_id)


def main():
    sample = load_sample()
    with TemporaryDirectory(prefix='haijia-metering-') as directory:
        root = Path(directory)
        center_path = root / 'center.sqlite'
        station_paths = (root / 'a.sqlite', root / 'b.sqlite')
        packets = tuple(collect_station(path, sample, station_input) for path, station_input in
                        zip(station_paths, sample['station_inputs'], strict=True))
        with Store(center_path) as center:
            baseline = prepare_center(center, sample)
            first, second = (accept_packet(center, raw) for raw in packets)
            original = issue_fixed(center, baseline.baseline_id, first.receipt_id, second.receipt_id)
        change = sample['correction']
        with Store(station_paths[0]) as station:
            revised = correct_station(station, change['parent'], change['revision_id'],
                                      {change['ticket_id']: (change['window'], change['kwh'])})
        with Store(center_path) as center:
            updated = accept_packet(center, revised.packet)
            latest = issue_fixed(center, baseline.baseline_id, updated.receipt_id, second.receipt_id)
        with Store(center_path) as center:
            old = read_report(center, original.report_id)
            new = read_report(center, latest.report_id)
            if old != original or new != latest:
                raise RuntimeError('signed report changed on reopening')
            if (old.usage_kwh, old.peak_kw, old.over_limit) != ((2, 2), 8, False):
                raise RuntimeError('original sample has the wrong demand')
            if (new.usage_kwh, new.peak_kw, new.over_limit) != ((3, 2), 12, True):
                raise RuntimeError('corrected sample has the wrong demand')
            print(export_report(center, old.report_id))
            print(export_report(center, new.report_id))


if __name__ == '__main__':
    main()
