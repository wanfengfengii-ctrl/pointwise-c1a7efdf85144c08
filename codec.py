import hashlib
import json


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def json_bytes(value):
    return canonical_json(value).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def stable_id(prefix, *parts):
    return f'{prefix}-{digest(json_bytes(parts))}'
