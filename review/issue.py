from dataclasses import asdict

from baseline.freeze import get_frozen_baseline
from contracts.register import get_shift
from exchange.selection import select_station_pair
from review.history import save_report
from review.peak import calculate_fixed_peak


def issue_inputs(store, baseline_id, receipt_a, receipt_b):
    baseline = get_frozen_baseline(store, baseline_id)
    shift = get_shift(store, baseline.shift_id)
    pair = select_station_pair(store, shift.shift_id, receipt_a, receipt_b)
    return shift, baseline, pair


def rollback_issue(store):
    store.connection.rollback()


def issue_fixed(store, baseline_id, receipt_a, receipt_b):
    store.begin_write()
    try:
        shift, baseline, pair = issue_inputs(store, baseline_id, receipt_a, receipt_b)
        result = calculate_fixed_peak(shift, baseline, pair)
        report = save_report(store, {
            'contract_id': shift.contract_id,
            'shift_id': shift.shift_id,
            'baseline_id': baseline.baseline_id,
            'windows': shift.windows,
            'baseline_kwh': baseline.values,
            'receipts': [asdict(source) for source in pair],
            **asdict(result),
        })
        store.connection.commit()
    except BaseException:
        rollback_issue(store)
        raise
    return report
