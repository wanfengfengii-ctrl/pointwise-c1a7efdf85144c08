import json

from codec import json_bytes
from demo import define_sample_shift
from metering import (
    Store, Ticket, accept_packet, amend_shift, begin_station, build_station_packet,
    close_station, count_receipts, define_shift, find_receipt, get_receipt, get_ticket,
    list_tickets, read_station_packet, record_ticket, record_tickets,
)
from station.packets import decode_station_packet
from tests.support import OfflineShiftCase, scenario


class DeliveryTests(OfflineShiftCase):
    def test_bad_window_and_ticket_replay_keep_valid_draft(self):
        with Store(self.station_paths[0]) as store:
            shift = define_sample_shift(store, self.sample)
            station = shift.stations[0]
            foreign = '2026-10-05T09:00'
            define_shift(store, shift.contract_id, 'S-02', shift.stations, 8, (foreign,))
            begin_station(store, shift.shift_id, station, 'A-01')
            window = shift.windows[0]
            original = record_ticket(store, shift.shift_id, station, 'A-t1', window, 1)
            self.assertEqual(record_ticket(store, shift.shift_id, station, 'A-t1', window, 1),
                             original)
            with self.assertRaises(ValueError):
                record_ticket(store, shift.shift_id, station, 'A-t1', window, 3)
            with self.assertRaises(ValueError) as rejected:
                record_tickets(store, shift.shift_id, station,
                               (Ticket('A-t2', window, 4), Ticket('A-wrong', foreign, 9)))
            self.assertEqual(get_ticket(store, shift.shift_id, station, 'A-t1'), original)
            self.assertEqual(list_tickets(store, shift.shift_id, station), (original,))
            with self.assertRaises(KeyError):
                close_station(store, shift.shift_id, station, 'A-unknown')
            closed = close_station(store, shift.shift_id, station, 'A-01')
            self.assertEqual(closed.usage_kwh, (1, 0))
            self.assertEqual(decode_station_packet(closed.packet).ticket_ids, ('A-t1',))
            with self.assertRaises(ValueError):
                close_station(store, shift.shift_id, station, 'A-01')
            with self.assertRaises(ValueError):
                record_ticket(store, shift.shift_id, station, 'A-t2', window, 1)
            with self.assertRaises(ValueError):
                amend_shift(store, shift.shift_id, shift.stations, 9, shift.windows)
        with Store(self.station_paths[0]) as store:
            raw = build_station_packet(store, 'A-01')
            self.assertEqual(raw, read_station_packet(store, closed.packet_id))
            self.assertEqual(raw, closed.packet)
        scenario('bad_window', {'valid': [window, 1], 'replay': [window, 1], 'foreign': foreign},
                 'ValueError', type(rejected.exception).__name__, (1, 0), closed.usage_kwh,
                 ['station/tickets.py', 'contracts/windows.py', 'station/settle.py'],
                 'Exactly one valid ticket adds one kWh to the first registered window.')

    def test_receipt_replay_reuses_first_receipt(self):
        raw, _ = self.station_packets()
        payload = json.loads(raw)
        reordered = dict(reversed(list(payload.items())))
        self.assertEqual(json_bytes(reordered), raw)
        with Store(self.center_path) as center:
            define_sample_shift(center, self.sample)
            first = accept_packet(center, raw)
        with Store(self.center_path) as center:
            replay = accept_packet(center, json_bytes(reordered))
            count = count_receipts(center)
            self.assertEqual(replay, first)
            self.assertEqual(count, 1)
            self.assertEqual(find_receipt(center, first.packet_id), first)
            self.assertEqual(get_receipt(center, first.receipt_id).raw, raw)
            other_encoding = json.dumps(reordered, ensure_ascii=False).encode('utf-8')
            self.assertNotEqual(other_encoding, raw)
            with self.assertRaises(ValueError):
                accept_packet(center, other_encoding)
            self.assertEqual(count_receipts(center), 1)
        scenario('receipt_replay', {'station': first.station, 'revision': first.revision_id,
                                    'packet_id': first.packet_id},
                 1, count, True, replay == first and replay.raw == raw,
                 ['station/packets.py', 'exchange/identity.py', 'exchange/accept.py',
                  'exchange/receipts.py'],
                 'One canonical fixed content delivered twice has exactly one receipt and its original bytes.')

    def test_receipt_conflict_rejects_changed_bytes(self):
        raw, _ = self.station_packets()
        payload = json.loads(raw)
        payload['usage_kwh'] = [2, 0]
        altered = json_bytes(payload)
        self.assertEqual(decode_station_packet(altered).usage_kwh, (2, 0))
        with Store(self.center_path) as center:
            define_sample_shift(center, self.sample)
            first = accept_packet(center, raw)
            self.assertEqual(decode_station_packet(altered).packet_id, first.packet_id)
            with self.assertRaises(ValueError) as rejected:
                accept_packet(center, altered)
            readback = get_receipt(center, first.receipt_id)
            self.assertEqual(readback, first)
            self.assertEqual(count_receipts(center), 1)
        scenario('receipt_conflict', {'packet_id': first.packet_id, 'first': [1, 0], 'replay': [2, 0]},
                 'ValueError', type(rejected.exception).__name__, True, readback == first,
                 ['exchange/identity.py', 'exchange/accept.py', 'exchange/receipts.py'],
                 'A later, structurally valid vector sharing the first packet ID cannot replace the first receipt.')

    def test_invalid_packets_leave_no_receipts(self):
        raw, _ = self.station_packets()
        payload = json.loads(raw)
        bad_payloads = (
            {**payload, 'version': 2}, {**payload, 'closed': False},
            {**payload, 'usage_kwh': [True, 0]}, {**payload, 'usage_kwh': [1]},
            {**payload, 'packet_id': 'pkt-other'}, {**payload, 'ticket_ids': ['A-t1', 'A-t1']},
            {**payload, 'windows': ['2026-10-05T09:00', '2026-10-05T09:15']},
        )
        with Store(self.center_path) as center:
            define_sample_shift(center, self.sample)
            for item in bad_payloads:
                with self.subTest(payload=item), self.assertRaises(ValueError):
                    accept_packet(center, json_bytes(item))
            with self.assertRaises(ValueError):
                accept_packet(center, b'\xff')
            self.assertEqual(count_receipts(center), 0)
            with self.assertRaises(KeyError):
                find_receipt(center, payload['packet_id'])
