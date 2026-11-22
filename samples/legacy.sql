BEGIN IMMEDIATE;
INSERT INTO shifts(shift_id, definition, locked) VALUES
('S-01', '{"contract_id":"C-17","limit_kw":8,"shift_id":"S-01","stations":["冷站甲","泵站乙"],"windows":["2026-10-05T08:00","2026-10-05T08:15"]}', 1);
INSERT INTO baselines(baseline_id, shift_id, parent_id, vector) VALUES
('BASE-01', 'S-01', NULL, '[1,0]');
INSERT INTO baseline_drafts(draft_id, shift_id, frozen_id) VALUES ('BD-01', 'S-01', 'BASE-01');
INSERT INTO baseline_values(draft_id, window, kwh) VALUES
('BD-01', '2026-10-05T08:00', '1'), ('BD-01', '2026-10-05T08:15', '0');
INSERT INTO receipts(receipt_id, packet_id, contract_id, shift_id, station, revision_id, fingerprint, raw, ack) VALUES
('rc-37560db6bc8e53cb3c443857d8eabba10f03f915c9528204dfd356a84c599776',
 'pkt-6d575316166e5f93091ed2131c0a01e44c75026a58fb04a01bcb27d3481023d8',
 'C-17', 'S-01', '冷站甲', 'A-01', '734bbf82f996e589bd91839f5b01212e3418ab527c1fb3e61d7a8bc78cadad44',
 CAST('{"closed":true,"contract_id":"C-17","packet_id":"pkt-6d575316166e5f93091ed2131c0a01e44c75026a58fb04a01bcb27d3481023d8","revision_id":"A-01","shift_id":"S-01","station":"冷站甲","ticket_ids":["A-t1"],"usage_kwh":[1,0],"version":1,"windows":["2026-10-05T08:00","2026-10-05T08:15"]}' AS BLOB),
 'ack-7e69eac63fa1b1df9c721d2f9c83216c831bff028031b88cafbe9c62b5dcdea6'),
('rc-0758083cf0205ca815d42ffb5042f7c1af2ac901fccd828bfcd8def0d0d62967',
 'pkt-109e3759bc0cae1844b00abed63e4131bb9a4e415db81a88400e1ed9a8171218',
 'C-17', 'S-01', '泵站乙', 'B-01', 'e030d4b7585ca1be11efad26607af801fabdc2e680aadcebb0efb2c05a9b316a',
 CAST('{"closed":true,"contract_id":"C-17","packet_id":"pkt-109e3759bc0cae1844b00abed63e4131bb9a4e415db81a88400e1ed9a8171218","revision_id":"B-01","shift_id":"S-01","station":"泵站乙","ticket_ids":["B-t1"],"usage_kwh":[0,2],"version":1,"windows":["2026-10-05T08:00","2026-10-05T08:15"]}' AS BLOB),
 'ack-6e03af68226d3f0627d10698371d26c3494b7212c0f1752c45e88c22655d7e43');
INSERT INTO reports(serial, report_id, baseline_id, receipt_a, receipt_b, snapshot) VALUES (
  1, 'rp-1', 'BASE-01',
  'rc-37560db6bc8e53cb3c443857d8eabba10f03f915c9528204dfd356a84c599776',
  'rc-0758083cf0205ca815d42ffb5042f7c1af2ac901fccd828bfcd8def0d0d62967',
  '{"baseline_id":"BASE-01","baseline_kwh":[1,0],"contract_id":"C-17","limit_kw":8,"over_limit":false,"peak_kw":8,"receipts":[{"ack":"ack-7e69eac63fa1b1df9c721d2f9c83216c831bff028031b88cafbe9c62b5dcdea6","fingerprint":"734bbf82f996e589bd91839f5b01212e3418ab527c1fb3e61d7a8bc78cadad44","packet_id":"pkt-6d575316166e5f93091ed2131c0a01e44c75026a58fb04a01bcb27d3481023d8","receipt_id":"rc-37560db6bc8e53cb3c443857d8eabba10f03f915c9528204dfd356a84c599776","revision_id":"A-01","station":"冷站甲","usage_kwh":[1,0]},{"ack":"ack-6e03af68226d3f0627d10698371d26c3494b7212c0f1752c45e88c22655d7e43","fingerprint":"e030d4b7585ca1be11efad26607af801fabdc2e680aadcebb0efb2c05a9b316a","packet_id":"pkt-109e3759bc0cae1844b00abed63e4131bb9a4e415db81a88400e1ed9a8171218","receipt_id":"rc-0758083cf0205ca815d42ffb5042f7c1af2ac901fccd828bfcd8def0d0d62967","revision_id":"B-01","station":"泵站乙","usage_kwh":[0,2]}],"shift_id":"S-01","usage_kwh":[2,2],"window_kw":[8,8],"windows":["2026-10-05T08:00","2026-10-05T08:15"]}'
);
INSERT INTO report_acks(report_id, ack) VALUES ('rp-1', 'ra-1');
COMMIT;
