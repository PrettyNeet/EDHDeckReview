"""Refresh deployable Scryfall cache files for Vercel."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.card_lookup import (  # noqa: E402
    CACHE_DIR,
    CARD_INDEX_GZ_PATH,
    CARD_INDEX_PATH,
    INDEX_METADATA_PATH,
    OTAG_INDEX_GZ_PATH,
    OTAG_INDEX_PATH,
    build_index,
    build_otag_index,
    download_bulk_data,
    fetch_bulk_data_metadata,
)


def _gzip_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(exist_ok=True)
    with src.open("rb") as in_file, gzip.open(dest, "wb", compresslevel=9) as out_file:
        shutil.copyfileobj(in_file, out_file)


def _json_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as f:
        return len(json.load(f))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true", help="Use existing local bulk data.")
    parser.add_argument("--skip-otag", action="store_true", help="Do not rebuild the otag index.")
    args = parser.parse_args()

    CACHE_DIR.mkdir(exist_ok=True)
    metadata = None
    bulk_path = None
    if not args.skip_download:
        metadata = fetch_bulk_data_metadata()
        bulk_path = download_bulk_data(metadata["download_uri"])

    build_index(force=True)
    if not args.skip_otag:
        build_otag_index(force=True)

    _gzip_file(CARD_INDEX_PATH, CARD_INDEX_GZ_PATH)
    if OTAG_INDEX_PATH.exists():
        _gzip_file(OTAG_INDEX_PATH, OTAG_INDEX_GZ_PATH)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scryfall_updated_at": metadata.get("updated_at") if metadata else None,
        "source_filename": bulk_path.name if bulk_path else None,
        "card_count": _json_count(CARD_INDEX_PATH),
        "otag_count": _json_count(OTAG_INDEX_PATH) if OTAG_INDEX_PATH.exists() else 0,
        "card_index_gzip_bytes": CARD_INDEX_GZ_PATH.stat().st_size,
        "otag_index_gzip_bytes": OTAG_INDEX_GZ_PATH.stat().st_size if OTAG_INDEX_GZ_PATH.exists() else 0,
    }
    INDEX_METADATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
