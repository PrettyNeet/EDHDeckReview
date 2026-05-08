"""
Standalone script to build the Scryfall otag index.
Queries Scryfall for each tracked otag and writes cache/otag_index.json.
Takes ~10–60 seconds depending on network speed.

Usage:
    python build_otag_index.py
    python build_otag_index.py --force   # rebuild even if cache exists
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.agents.card_lookup import build_otag_index

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebuild even if cache exists")
    args = parser.parse_args()
    build_otag_index(force=args.force)
