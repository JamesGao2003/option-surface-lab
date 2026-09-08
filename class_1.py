"""Assignment 1.1 entry point, adapted from the instructor's class_1.py.

Updates follow the instructor's Sep 7 announcement:
- MID_PRICE replaces the unsupported SETTLE field.
- Reflex is optional: export an interactive static HTML page for GitHub Pages.
- The original fetch -> pickle -> chart workflow is retained.

Run locally: python class_1.py --cache option_pipeline_data_v2.pkl
Fetch in CodeBook separately: %run fetch_options_v2.py
"""
import argparse
from pathlib import Path
from build_site import build
from fetch_options_v2 import parse_option_ric


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path(__file__).with_name('option_pipeline_data_v2.pkl'))
    args = parser.parse_args()
    build(args.cache)


if __name__ == '__main__':
    main()
