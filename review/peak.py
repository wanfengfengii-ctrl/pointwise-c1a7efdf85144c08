from dataclasses import dataclass

from contracts.rates import kwh_to_kw, limit_verdict


@dataclass(frozen=True)
class FixedPeak:
    usage_kwh: tuple[int, ...]
    window_kw: tuple[int, ...]
    peak_kw: int
    limit_kw: int
    over_limit: bool


def build_window_totals(baseline, station_a, station_b):
    return tuple(base + first + second for base, first, second in
                 zip(baseline, station_a, station_b, strict=True))


def verdict_for_peak(peak_kw, limit_kw):
    return limit_verdict(peak_kw, limit_kw)


def calculate_fixed_peak(shift, baseline, pair):
    first, second = pair
    if baseline.shift_id != shift.shift_id or len(baseline.values) != len(shift.windows):
        raise ValueError('baseline does not cover the selected shift')
    usage = build_window_totals(baseline.values, first.usage_kwh, second.usage_kwh)
    window_kw = tuple(kwh_to_kw(value) for value in usage)
    peak_kw = max(window_kw)
    return FixedPeak(usage, window_kw, peak_kw, shift.limit_kw,
                     verdict_for_peak(peak_kw, shift.limit_kw))
