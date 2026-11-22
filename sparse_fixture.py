"""Check the sparse-shift input data using the existing V1 business flow."""
import json

from demo import SAMPLE_DIR, define_sample_shift, prepare_center
from metering import (
    Store, Ticket, accept_packet, begin_station, build_station_packet, close_station,
    correct_station, issue_fixed, record_tickets,
)


def collect(sample, station_input, corrections=()):
    with Store(":memory:") as station:
        shift = define_sample_shift(station, sample)
        code = station_input["station"]
        root = station_input["revision_id"]
        begin_station(station, shift.shift_id, code, root)
        record_tickets(station, shift.shift_id, code,
                       [Ticket(*row) for row in station_input["tickets"]])
        close_station(station, shift.shift_id, code, root)
        packets = {root: build_station_packet(station, root)}
        for entry in corrections:
            revision = correct_station(station, entry["parent"], entry["revision"],
                                       entry["tickets"])
            packets[revision.revision_id] = build_station_packet(station, revision.revision_id)
        return packets


def main():
    sample = json.loads((SAMPLE_DIR / "sparse-shift.json").read_text(encoding="utf-8"))
    first, second = sample["station_inputs"]
    packets = collect(sample, first, sample["corrections"])
    comparison = collect(sample, first, sample["comparison_history"])
    other = collect(sample, second)
    if packets["A1"] == comparison["A1"] or packets["A2"] != comparison["A2"]:
        raise AssertionError("the two V1 histories should have identical A2 bytes only")

    expected = {"A0": ((1, 2, 3), 12, False), "A2": ((1, 0, 4), 16, False),
                "A3": ((1, 7, 4), 28, True), "A4": ((1, 2, 3), 12, False),
                "P": ((1, 7, 3), 28, True)}
    results = {}
    with Store(":memory:") as center:
        baseline = prepare_center(center, sample)
        beta = accept_packet(center, other["B0"])
        for revision in ("A2", "P", "A0", "A3", "A4"):
            alpha = accept_packet(center, packets[revision])
            report = issue_fixed(center, baseline.baseline_id, alpha.receipt_id, beta.receipt_id)
            result = (report.usage_kwh, report.peak_kw, report.over_limit)
            if result != expected[revision]:
                raise AssertionError(f"unexpected V1 result for {revision}: {result!r}")
            results[revision] = result
    print(json.dumps({"v1_reports_without_a1": results, "v1_a2_bytes_equal": True},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
