from collections.abc import Mapping

from contracts.rates import require_nonnegative_int


def missing_windows(windows, values):
    if not isinstance(values, Mapping):
        raise ValueError('baseline values must map windows to kWh')
    return tuple(window for window in windows if window not in values)


def baseline_is_complete(windows, values):
    return not missing_windows(windows, values) and len(windows) == len(values)


def require_complete_baseline(windows, values):
    missing = missing_windows(windows, values)
    if missing:
        raise ValueError(f'baseline is missing windows: {", ".join(missing)}')
    if not baseline_is_complete(windows, values):
        raise ValueError('baseline contains an unregistered window')
    return tuple(require_nonnegative_int(values[window], 'baseline kWh')
                 for window in windows)
