from datetime import datetime, timedelta

from contracts.records import WindowKey as WindowKey


_WINDOW_LENGTH = timedelta(minutes=15)


def _minute(value):
    if not isinstance(value, str):
        raise ValueError('window timestamps must be strings')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'invalid window timestamp {value!r}') from exc
    if parsed.tzinfo is not None or parsed.isoformat(timespec='minutes') != value:
        raise ValueError('window timestamps require YYYY-MM-DDTHH:MM')
    return parsed


def _end(start):
    try:
        return start + _WINDOW_LENGTH
    except OverflowError as exc:
        raise ValueError('window exceeds the calendar range') from exc


def validate_window_set(windows) -> tuple[WindowKey, ...]:
    if not isinstance(windows, (list, tuple)) or not windows:
        raise ValueError('at least one ordered window is required')
    previous_end = None
    for key in windows:
        start = _minute(key)
        if previous_end is not None and start < previous_end:
            raise ValueError('windows must be ordered and nonoverlapping')
        previous_end = _end(start)
    return tuple(windows)


def normalize_windows(windows) -> tuple[WindowKey, ...]:
    if not isinstance(windows, (list, tuple)):
        raise ValueError('windows must be a list or tuple')
    keys = []
    for window in windows:
        if isinstance(window, str):
            keys.append(window)
        elif isinstance(window, (list, tuple)) and len(window) == 2:
            start, end = window
            if _end(_minute(start)) != _minute(end):
                raise ValueError('a window must be fifteen minutes long')
            keys.append(start)
        else:
            raise ValueError('expected a window start or a start/end pair')
    return validate_window_set(keys)


def window_positions(windows) -> dict[WindowKey, int]:
    return {key: index for index, key in enumerate(validate_window_set(windows))}
