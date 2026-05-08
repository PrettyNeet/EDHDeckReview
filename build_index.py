"""
Standalone script to pre-build the Scryfall card index.
Run this once before starting the server to avoid the first-request delay.

Usage:
    python build_index.py
    python build_index.py --force   # rebuild even if cache exists
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.agents.card_lookup import build_index

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebuild even if cache exists")
    args = parser.parse_args()
    build_index(force=args.force)
