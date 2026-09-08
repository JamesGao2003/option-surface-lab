"""Compatibility entry point. V2 corrects put RIC expiry suffixes.
Upload fetch_options_v2.py to CodeBook; run %run fetch_options_v2.py.
"""
from fetch_options_v2 import canonicalize, make_option_ric, atomic_pickle, run
from fetch_options_v2 import parse_option_ric as _parse, to_long as _long

# Legacy reading is only for auditing the exact earlier cache, not requesting data.
def parse_option_ric(ric):
    return _parse(ric, allow_legacy_suffix=True)

def to_long(options):
    return _long(options, allow_legacy_suffix=True)

if __name__ == "__main__":
    payload = run()
