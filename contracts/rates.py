KWH_TO_KW = 4


def require_nonnegative_int(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')
    return value


def kwh_to_kw(kwh):
    return KWH_TO_KW * require_nonnegative_int(kwh, 'kWh')


def validate_limit_kw(limit_kw):
    return require_nonnegative_int(limit_kw, 'limit kW')


def limit_verdict(peak_kw, limit_kw):
    return require_nonnegative_int(peak_kw, 'peak kW') > validate_limit_kw(limit_kw)
