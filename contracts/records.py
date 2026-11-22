import re
from dataclasses import dataclass
from typing import TypeAlias

from contracts.rates import validate_limit_kw


StationCode: TypeAlias = str
WindowKey: TypeAlias = str
_IDENTIFIER = re.compile(r'[^\W_][\w-]{0,127}')


def require_id(value, name):
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f'invalid {name}')
    return value


@dataclass(frozen=True)
class ShiftRecord:
    contract_id: str
    shift_id: str
    stations: tuple[StationCode, StationCode]
    limit_kw: int
    windows: tuple[WindowKey, ...]


def validate_shift_record(record):
    if not isinstance(record, ShiftRecord):
        raise ValueError('expected a shift record')
    require_id(record.contract_id, 'contract ID')
    require_id(record.shift_id, 'shift ID')
    if not isinstance(record.stations, (list, tuple)) or len(record.stations) != 2:
        raise ValueError('exactly two stations are required')
    first, second = (require_id(station, 'station') for station in record.stations)
    if first == second:
        raise ValueError('stations must be different')
    validate_limit_kw(record.limit_kw)
    if not isinstance(record.windows, tuple) or not record.windows:
        raise ValueError('a shift requires an ordered window set')
    return record
