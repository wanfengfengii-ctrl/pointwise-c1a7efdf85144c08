import sqlite3
from contextlib import contextmanager


SCHEMA_VERSION = 1
_SCHEMA = '''
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS shifts (
    shift_id TEXT PRIMARY KEY NOT NULL,
    definition TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1))
);
CREATE TABLE IF NOT EXISTS baselines (
    baseline_id TEXT PRIMARY KEY NOT NULL,
    shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
    parent_id TEXT REFERENCES baselines(baseline_id),
    vector TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS baselines_by_shift ON baselines(shift_id, baseline_id);
CREATE TABLE IF NOT EXISTS baseline_drafts (
    draft_id TEXT PRIMARY KEY NOT NULL,
    shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
    frozen_id TEXT UNIQUE REFERENCES baselines(baseline_id)
);
CREATE TABLE IF NOT EXISTS baseline_values (
    draft_id TEXT NOT NULL REFERENCES baseline_drafts(draft_id),
    window TEXT NOT NULL,
    kwh TEXT NOT NULL,
    PRIMARY KEY (draft_id, window)
);
CREATE TABLE IF NOT EXISTS station_drafts (
    shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
    station TEXT NOT NULL,
    revision_id TEXT NOT NULL UNIQUE,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    PRIMARY KEY (shift_id, station)
);
CREATE TABLE IF NOT EXISTS tickets (
    shift_id TEXT NOT NULL,
    station TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    window TEXT NOT NULL,
    kwh TEXT NOT NULL,
    PRIMARY KEY (shift_id, station, ticket_id),
    FOREIGN KEY (shift_id, station) REFERENCES station_drafts(shift_id, station)
);
CREATE TABLE IF NOT EXISTS station_revisions (
    revision_id TEXT PRIMARY KEY NOT NULL,
    shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
    station TEXT NOT NULL,
    parent_id TEXT REFERENCES station_revisions(revision_id),
    snapshot TEXT NOT NULL,
    packet_id TEXT NOT NULL UNIQUE,
    packet_raw BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS station_revisions_by_station
    ON station_revisions(shift_id, station, revision_id);
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id TEXT PRIMARY KEY NOT NULL,
    packet_id TEXT NOT NULL UNIQUE,
    contract_id TEXT NOT NULL,
    shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
    station TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    raw BLOB NOT NULL,
    ack TEXT NOT NULL UNIQUE,
    UNIQUE (contract_id, shift_id, station, revision_id)
);
CREATE TABLE IF NOT EXISTS reports (
    serial INTEGER PRIMARY KEY,
    report_id TEXT NOT NULL UNIQUE,
    baseline_id TEXT NOT NULL REFERENCES baselines(baseline_id),
    receipt_a TEXT NOT NULL REFERENCES receipts(receipt_id),
    receipt_b TEXT NOT NULL REFERENCES receipts(receipt_id),
    snapshot TEXT NOT NULL,
    CHECK (receipt_a <> receipt_b)
);
CREATE TABLE IF NOT EXISTS report_acks (
    report_id TEXT PRIMARY KEY NOT NULL REFERENCES reports(report_id),
    ack TEXT NOT NULL UNIQUE
);
PRAGMA user_version = 1;
COMMIT;
'''


class Store:
    """A local SQLite ledger. Each station and the center open their own store."""

    def __init__(self, path):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute('PRAGMA foreign_keys = ON')
            version = self.connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError(f'unsupported ledger schema {version}')
            self.connection.executescript(_SCHEMA)
        except BaseException:
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.connection.close()

    def begin_write(self):
        if self.connection.in_transaction:
            raise RuntimeError('a transaction is already active')
        self.connection.execute('BEGIN IMMEDIATE')

    def require_write(self):
        if not self.connection.in_transaction:
            raise RuntimeError('an active write transaction is required')

    @contextmanager
    def write(self):
        self.begin_write()
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
