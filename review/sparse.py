"""Sparse review: sign a shift from an anchor, a sparse target and the other station."""
from baseline.freeze import get_frozen_baseline
from contracts.rates import kwh_to_kw, limit_verdict
from contracts.register import get_shift
from exchange.receipts import get_receipt
from exchange.selection import verify_receipt_packet
from review.history import save_report
from station.packets import station_packet_id
from station.sparse import SPARSE_KIND


def _revision_receipt(store, shift, station, revision_id):
    row = store.connection.execute('''
        SELECT receipt_id FROM receipts
        WHERE contract_id = ? AND shift_id = ? AND station = ? AND revision_id = ?
    ''', (shift.contract_id, shift.shift_id, station, revision_id)).fetchone()
    if row is None:
        return None
    return get_receipt(store, row['receipt_id'])


def _require_kind(shift, receipt, expected_station, sparse):
    packet = verify_receipt_packet(shift, receipt)
    is_sparse = getattr(packet, 'kind', None) == SPARSE_KIND
    if is_sparse != sparse:
        wanted = 'a sparse packet' if sparse else 'a full fixed packet'
        raise ValueError(f'receipt for {expected_station} must be {wanted}')
    if packet.station != expected_station:
        raise ValueError(f'receipt does not belong to {expected_station}')
    return packet


def resolve_sparse_branch(store, shift, anchor_packet, target_packet):
    """Resolve every window of the target branch to an actually received original.

    Missing intermediate revisions are allowed only when every window they changed
    was changed again by a later revision on the same branch. Side branches never
    qualify because only the target's own branch entries are inspected. Returns the
    effective per-window totals and the receipt ID supplying each window.
    """
    if target_packet.anchor_id != anchor_packet.revision_id:
        raise ValueError('sparse target does not name the selected anchor')
    entries = target_packet.branch
    missing_gap_windows = set()
    received_steps = []
    for entry in entries:
        receipt = _revision_receipt(store, shift, target_packet.station, entry.revision_id)
        if receipt is None:
            missing_gap_windows.update(entry.changed_windows)
            continue
        packet = verify_receipt_packet(shift, receipt)
        if getattr(packet, 'kind', None) != SPARSE_KIND:
            raise ValueError(f'branch revision {entry.revision_id} is not a sparse packet')
        expected_prefix = entries[:len(packet.branch)]
        if (packet.anchor_id != anchor_packet.revision_id
                or packet.parent_id != entry.parent_id
                or packet.packet_id != station_packet_id(
                    shift.contract_id, shift.shift_id, target_packet.station,
                    entry.revision_id)
                or tuple(item.revision_id for item in packet.branch)
                != tuple(item.revision_id for item in expected_prefix)
                or tuple(item.changed_windows for item in packet.branch)
                != tuple(item.changed_windows for item in expected_prefix)):
            raise ValueError(
                f'branch evidence for {entry.revision_id} does not match its original')
        received_steps.append((packet, receipt.receipt_id))
        missing_gap_windows.difference_update(entry.changed_windows)
    if missing_gap_windows:
        raise ValueError('a still-supplying original packet for a changed window is missing')
    totals = list(anchor_packet.usage_kwh)
    sources = [None] * len(shift.windows)
    positions = {window: index for index, window in enumerate(shift.windows)}
    for packet, receipt_id in received_steps:
        for change in packet.changes:
            index = positions[change.window]
            totals[index] = change.kwh
            sources[index] = receipt_id
    anchor_receipt = _revision_receipt(store, shift, anchor_packet.station,
                                       anchor_packet.revision_id)
    if anchor_receipt is None:
        raise ValueError('anchor original packet has not been received')
    for index in range(len(shift.windows)):
        if sources[index] is None:
            sources[index] = anchor_receipt.receipt_id
    return tuple(totals), tuple(sources)


def issue_sparse(store, baseline_id, anchor_receipt, target_receipt, other_receipt):
    store.begin_write()
    try:
        baseline = get_frozen_baseline(store, baseline_id)
        shift = get_shift(store, baseline.shift_id)
        station_a, station_b = shift.stations
        anchor_record = get_receipt(store, anchor_receipt)
        target_record = get_receipt(store, target_receipt)
        other_record = get_receipt(store, other_receipt)
        if len({anchor_record.receipt_id, target_record.receipt_id,
                other_record.receipt_id}) != 3:
            raise ValueError('the three sparse-review receipts must be distinct')
        anchor_packet = _require_kind(shift, anchor_record, station_a, sparse=False)
        target_packet = _require_kind(shift, target_record, station_a, sparse=True)
        other_packet = _require_kind(shift, other_record, station_b, sparse=False)
        if baseline.shift_id != shift.shift_id or len(baseline.values) != len(shift.windows):
            raise ValueError('baseline does not cover the selected shift')
        alpha_usage, alpha_sources = resolve_sparse_branch(
            store, shift, anchor_packet, target_packet,
        )
        usage = tuple(base + alpha + beta for base, alpha, beta in
                      zip(baseline.values, alpha_usage, other_packet.usage_kwh, strict=True))
        window_kw = tuple(kwh_to_kw(value) for value in usage)
        peak_kw = max(window_kw)
        window_receipts = tuple(
            (alpha, other_record.receipt_id) for alpha in alpha_sources
        )
        report = save_report(store, {
            'sparse': True,
            'contract_id': shift.contract_id,
            'shift_id': shift.shift_id,
            'baseline_id': baseline.baseline_id,
            'windows': shift.windows,
            'baseline_kwh': baseline.values,
            'usage_kwh': usage,
            'window_kw': window_kw,
            'peak_kw': peak_kw,
            'limit_kw': shift.limit_kw,
            'over_limit': limit_verdict(peak_kw, shift.limit_kw),
            'anchor_receipt_id': anchor_record.receipt_id,
            'target_receipt_id': target_record.receipt_id,
            'other_receipt_id': other_record.receipt_id,
            'window_receipts': window_receipts,
        })
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    return report
