"""
Scryfall card lookup agent.
Builds a name-keyed index from the local bulk data file on first run,
then caches it as a compact JSON file for fast subsequent lookups.
"""

import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import gzip
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BULK_DATA_DIR = BASE_DIR / "Scryfall src"
CACHE_DIR = BASE_DIR / "cache"

SCRYFALL_BULK_API = "https://api.scryfall.com/bulk-data"
BULK_DATA_TYPE   = "default_cards"
STALE_HOURS      = 24
_USER_AGENT      = "MTG-DeckReview/1.0 (local tool)"
SCRYFALL_PAGE_DELAY_SECONDS = 0.25
SCRYFALL_MAX_RETRIES = 5

CARD_FIELDS = [
    "name", "cmc", "color_identity", "colors", "defense", "keywords",
    "mana_cost", "oracle_id", "oracle_text", "power", "toughness",
    "type_line", "legalities", "produced_mana", "layout", "card_faces",
    "game_changer", "rarity", "set_name", "scryfall_uri", "prices",
]

_INDEX: dict[str, dict] | None = None

OTAG_INDEX_PATH = CACHE_DIR / "otag_index.json"
CARD_INDEX_PATH = CACHE_DIR / "card_index.json"
CARD_INDEX_GZ_PATH = CACHE_DIR / "card_index.json.gz"
OTAG_INDEX_GZ_PATH = CACHE_DIR / "otag_index.json.gz"
INDEX_METADATA_PATH = CACHE_DIR / "index_metadata.json"

TRACKED_OTAGS: list[str] = [
    "ramp", "mana-rock", "mana-dork",                   # Ramp
    "draw", "catalog", "play-from-top",                  # Card Advantage
    "removal", "counterspell", "exile-target",           # Removal
    "board-wipe",                                        # Mass Disruption
    "tutor",                                             # Plan Cards / CA
    "graveyard-matters", "tribal", "synergy-mill",       # Plan Cards
    "power-matters", "pp-counters-matter",               # Plan Cards
    "protection",                                        # Hexproof/shroud givers
    "pump",                                              # Anthem / +N/+N effects
    "reanimation",                                       # Return from graveyard
    "lifegain",                                          # Life gain effects
]

_OTAG_INDEX: dict[str, list[str]] | None = None


def _normalize_name(name: str) -> str:
    """Lowercase + strip accents + strip apostrophes for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", name.strip().lower())
    # Remove combining characters (accents) and apostrophes/curly quotes
    return "".join(
        c for c in nfkd
        if not unicodedata.combining(c) and c not in ("'", "’", "ʼ", "`")
    )


def _find_bulk_file() -> Path:
    """Return the most recent default-cards bulk file."""
    candidates = sorted(BULK_DATA_DIR.glob("default-cards-*.json"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No default-cards bulk file found in {BULK_DATA_DIR}")
    return candidates[0]


def _extract_card(raw: dict) -> dict:
    """Pull only the fields we care about from a raw Scryfall card object."""
    card = {k: raw.get(k) for k in CARD_FIELDS}
    # For double-faced cards flatten the relevant face fields if missing on root
    if raw.get("layout") in ("transform", "modal_dfc", "double_faced_token", "reversible_card"):
        faces = raw.get("card_faces", [])
        if faces:
            front = faces[0]
            for f in ("oracle_text", "power", "toughness", "defense", "mana_cost", "type_line"):
                if not card.get(f) and front.get(f):
                    card[f] = front[f]
    return card


def _load_bulk_cards(bulk_path: Path) -> list[dict]:
    """Read the Scryfall bulk file whether it is plain JSON or gzip-compressed JSON."""
    with bulk_path.open("rb") as f:
        magic = f.read(2)

    opener = gzip.open if magic == b"\x1f\x8b" else open
    with opener(bulk_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def build_index(force: bool = False) -> Path:
    """
    Build (or rebuild) the card name index from the Scryfall bulk data.
    Returns the path to the written cache file.
    Deduplicates by oracle_id keeping the canonical English printing but stores
    the minimum USD price found across all non-digital English printings.
    """
    global _INDEX
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CARD_INDEX_PATH

    if cache_path.exists() and not force:
        return cache_path

    print("Building Scryfall card index - this takes ~30 seconds on first run...")
    bulk_path = _find_bulk_file()

    raw_cards = _load_bulk_cards(bulk_path)

    # Pass 1: collect canonical legal printing per oracle_id + min USD price across all printings
    legal_by_oid: dict[str, dict] = {}
    any_by_oid: dict[str, dict] = {}
    min_usd_by_oid: dict[str, float] = {}

    for raw in raw_cards:
        if raw.get("lang") != "en":
            continue
        if raw.get("digital"):
            continue

        oid = raw.get("oracle_id", "")
        card = _extract_card(raw)
        legality = (card.get("legalities") or {}).get("commander", "")

        if oid:
            if legality in ("legal", "restricted") and oid not in legal_by_oid:
                legal_by_oid[oid] = card
            if oid not in any_by_oid:
                any_by_oid[oid] = card
            # Track cheapest non-foil USD price across all printings
            raw_prices = raw.get("prices") or {}
            usd_str = raw_prices.get("usd")
            if usd_str:
                try:
                    usd = float(usd_str)
                    if usd > 0:
                        if oid not in min_usd_by_oid or usd < min_usd_by_oid[oid]:
                            min_usd_by_oid[oid] = usd
                except (TypeError, ValueError):
                    pass
        else:
            # No oracle_id (tokens, etc.) — index directly
            key = _normalize_name(card["name"])
            any_by_oid[key] = card

    # Merge: prefer legal printings
    chosen: dict[str, dict] = {}
    all_oids = set(legal_by_oid) | set(any_by_oid)
    for oid in all_oids:
        card = legal_by_oid.get(oid) or any_by_oid.get(oid)
        # Overwrite stored price with the cheapest printing found
        if oid in min_usd_by_oid:
            prices = dict(card.get("prices") or {})
            prices["usd"] = str(round(min_usd_by_oid[oid], 2))
            card = dict(card)
            card["prices"] = prices
        chosen[oid] = card

    index: dict[str, dict] = {}
    for card in chosen.values():
        key = _normalize_name(card["name"])
        if key not in index:
            index[key] = card

        # Also index split/flip half-names (e.g. "Fire // Ice" -> "fire" and "ice")
        if " // " in card["name"]:
            parts = card["name"].split(" // ")
            # Skip "Name // Name" doubled names (meld cards, etc.)
            if len(set(parts)) > 1:
                for part in parts:
                    pk = _normalize_name(part)
                    if pk not in index:
                        index[pk] = card

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    _INDEX = index

    print(f"Card index built: {len(index):,} entries -> {cache_path}")
    return cache_path


def _load_index() -> dict[str, dict]:
    global _INDEX
    if _INDEX is not None:
        sample = next(iter(_INDEX.values()), {})
        if sample and "prices" not in sample:
            build_index(force=True)
        return _INDEX

    if _INDEX is None:
        cache_path = CARD_INDEX_PATH
        gz_path = CARD_INDEX_GZ_PATH
        if not cache_path.exists() and not gz_path.exists():
            build_index()
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                _INDEX = json.load(f)
        else:
            with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                _INDEX = json.load(f)
        sample = next(iter(_INDEX.values()), {})
        if sample and "prices" not in sample:
            build_index(force=True)
            with open(cache_path, "r", encoding="utf-8") as f:
                _INDEX = json.load(f)
    return _INDEX


def lookup(card_name: str) -> dict | None:
    """
    Look up a card by name. Returns the card dict or None if not found.
    Tries exact match first, then normalised match.
    """
    index = _load_index()
    key = _normalize_name(card_name)
    return index.get(key)


def search_by_prefix(prefix: str, limit: int = 10) -> list[dict]:
    """Return up to `limit` cards whose names start with `prefix`."""
    index = _load_index()
    key = _normalize_name(prefix)
    results = []
    for name_key, card in index.items():
        if name_key.startswith(key):
            results.append(card)
            if len(results) >= limit:
                break
    return results


def suggest_names(partial: str, limit: int = 8) -> list[str]:
    """Return card name suggestions for autocomplete."""
    index = _load_index()
    key = _normalize_name(partial)
    return [
        card["name"]
        for name_key, card in index.items()
        if key in name_key
    ][:limit]


# ─── Otag index ───────────────────────────────────────────────────────────────

def _load_otag_index() -> dict[str, list[str]]:
    global _OTAG_INDEX
    if _OTAG_INDEX is not None:
        return _OTAG_INDEX
    if not OTAG_INDEX_PATH.exists() and not OTAG_INDEX_GZ_PATH.exists():
        _OTAG_INDEX = {}
        return _OTAG_INDEX
    if OTAG_INDEX_PATH.exists():
        with open(OTAG_INDEX_PATH, "r", encoding="utf-8") as f:
            _OTAG_INDEX = json.load(f)
    else:
        with gzip.open(OTAG_INDEX_GZ_PATH, "rt", encoding="utf-8") as f:
            _OTAG_INDEX = json.load(f)
    return _OTAG_INDEX


def lookup_otags(card_name: str) -> list[str]:
    """Return tracked otags for a card, or [] if not in the otag index."""
    return _load_otag_index().get(_normalize_name(card_name), [])


def get_cards_by_otag(
    tags: list[str],
    commander_ci: list[str] | None = None,
    max_results: int = 40,
) -> list[dict]:
    """
    Return cards that have ANY of the given otags, filtered by commander color identity.
    Sorted: game_changer first, then ascending cmc.
    commander_ci=None skips color filtering (use for colorless staples).
    Returns dicts with 'name', 'color_identity', 'cmc', 'game_changer' keys.
    """
    otag_index = _load_otag_index()
    card_index = _load_index()
    ci_set = set(commander_ci) if commander_ci is not None else None
    tag_set = set(tags)

    results: list[dict] = []
    for norm_name, card_tags in otag_index.items():
        if not tag_set.intersection(card_tags):
            continue
        card = card_index.get(norm_name)
        if not card:
            continue
        card_ci = card.get("color_identity") or []
        if ci_set is not None and not set(card_ci).issubset(ci_set):
            continue
        results.append({
            "name": card["name"],
            "color_identity": card_ci,
            "cmc": card.get("cmc") or 0,
            "game_changer": card.get("game_changer", False),
        })

    results.sort(key=lambda c: (-c["game_changer"], c["cmc"]))
    return results[:max_results]


def build_otag_index(force: bool = False) -> Path:
    """
    Fetch all TRACKED_OTAGS from Scryfall's search API and write
    cache/otag_index.json.  Returns the path to the written file.
    Skips the network fetch if the cache already exists and force=False.
    """
    global _OTAG_INDEX
    CACHE_DIR.mkdir(exist_ok=True)
    if OTAG_INDEX_PATH.exists() and not force:
        return OTAG_INDEX_PATH

    print(f"Building otag index for {len(TRACKED_OTAGS)} tags...")
    index: dict[str, list[str]] = {}

    for tag in TRACKED_OTAGS:
        url: str | None = (
            f"https://api.scryfall.com/cards/search"
            f"?q=otag%3A{tag}&pretty=false"
        )
        page = 0
        while url:
            page += 1
            data = _fetch_scryfall_json_with_retries(url)

            for card in data.get("data", []):
                key = _normalize_name(card.get("name", ""))
                if key:
                    if key not in index:
                        index[key] = []
                    if tag not in index[key]:
                        index[key].append(tag)

            url = data.get("next_page") if data.get("has_more") else None
            time.sleep(SCRYFALL_PAGE_DELAY_SECONDS)

        print(f"  otag:{tag} — done ({page} page{'s' if page != 1 else ''})")

    with open(OTAG_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    _OTAG_INDEX = index
    print(f"Otag index built: {len(index):,} entries → {OTAG_INDEX_PATH}")

    # Clear the staple cache so next call picks up the fresh index
    try:
        from app.agents.synergy import _staples_for_color
        _staples_for_color.cache_clear()
    except ImportError:
        pass

    return OTAG_INDEX_PATH


def _fetch_scryfall_json_with_retries(url: str) -> dict:
    """Fetch Scryfall JSON with retry/backoff for transient rate limits."""
    last_error: Exception | None = None
    for attempt in range(SCRYFALL_MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"data": [], "has_more": False}
            last_error = exc
            if exc.code != 429 and exc.code < 500:
                raise
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = 2.0
            else:
                delay = min(2 ** attempt, 30)
            print(f"  Scryfall request limited/failed ({exc.code}); retrying in {delay:.1f}s...")
            time.sleep(delay)
        except urllib.error.URLError as exc:
            last_error = exc
            delay = min(2 ** attempt, 30)
            print(f"  Scryfall request failed ({exc.reason}); retrying in {delay:.1f}s...")
            time.sleep(delay)

    if last_error:
        raise last_error
    raise RuntimeError("Scryfall request failed without an exception.")


# ─── Bulk data freshness ──────────────────────────────────────────────────────

def check_bulk_data_freshness() -> dict:
    """
    Return age information for the local default-cards bulk file.
    Scryfall considers data older than 24 hours stale.
    """
    if INDEX_METADATA_PATH.exists():
        try:
            metadata = json.loads(INDEX_METADATA_PATH.read_text(encoding="utf-8"))
            updated_at = metadata.get("scryfall_updated_at") or metadata.get("generated_at")
            if updated_at:
                updated = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
                return {
                    "found": True,
                    "path": str(INDEX_METADATA_PATH),
                    "filename": metadata.get("source_filename") or "deploy cache",
                    "age_hours": round(age_hours, 2),
                    "age_human": _fmt_age(age_hours),
                    "is_stale": age_hours > STALE_HOURS,
                    "mtime_iso": updated.isoformat(),
                    "source": "deploy_cache",
                    "metadata": metadata,
                }
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    try:
        bulk_path = _find_bulk_file()
    except FileNotFoundError:
        return {
            "found": False,
            "path": None,
            "age_hours": None,
            "is_stale": True,
            "mtime_iso": None,
            "filename": None,
        }

    mtime = bulk_path.stat().st_mtime
    age_seconds = time.time() - mtime
    age_hours = age_seconds / 3600

    return {
        "found": True,
        "path": str(bulk_path),
        "filename": bulk_path.name,
        "age_hours": round(age_hours, 2),
        "age_human": _fmt_age(age_hours),
        "is_stale": age_hours > STALE_HOURS,
        "mtime_iso": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
    }


def _fmt_age(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"


def fetch_bulk_data_metadata() -> dict:
    """
    Call GET https://api.scryfall.com/bulk-data and return the metadata entry
    for the 'default_cards' dataset, including its download_uri and updated_at.
    Raises urllib.error.URLError on network failure.
    """
    req = urllib.request.Request(
        SCRYFALL_BULK_API,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    for entry in data.get("data", []):
        if entry.get("type") == BULK_DATA_TYPE:
            return {
                "type": entry["type"],
                "name": entry.get("name", "Default Cards"),
                "download_uri": entry["download_uri"],
                "updated_at": entry.get("updated_at"),
                "size_bytes": entry.get("size", 0),
                "compressed_size_bytes": entry.get("compressed_size", 0),
            }

    raise ValueError(f"'{BULK_DATA_TYPE}' not found in Scryfall bulk-data response.")


def download_bulk_data(
    download_uri: str,
    *,
    progress_path: Path | None = None,
) -> Path:
    """
    Stream-download the bulk data file into BULK_DATA_DIR.
    Writes a JSON progress file to `progress_path` (if given) during the download
    so callers can poll it for status updates.

    Steps:
      1. Download to a temp file in the same directory (atomic replacement)
      2. Move temp file to the final filename derived from the URI
      3. Delete any older default-cards-*.json files
      4. Invalidate the in-memory card index so the next lookup triggers a rebuild

    Returns the Path of the newly written file.
    """
    def _write_progress(status: str, pct: int = 0, **extra):
        if progress_path:
            payload = {"status": status, "pct": pct, **extra}
            try:
                progress_path.write_text(json.dumps(payload), encoding="utf-8")
            except OSError:
                pass

    BULK_DATA_DIR.mkdir(exist_ok=True)
    filename = download_uri.split("/")[-1]  # e.g. default-cards-20260507091337.json
    dest = BULK_DATA_DIR / filename

    _write_progress("connecting", 0, filename=filename)

    req = urllib.request.Request(
        download_uri,
        headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"},
    )

    # Write to a temp file first so a failed download doesn't clobber the existing data
    tmp_fd, tmp_path_str = tempfile.mkstemp(dir=BULK_DATA_DIR, suffix=".tmp")
    tmp_path = Path(tmp_path_str)

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            chunk_size = 1024 * 512  # 512 KB chunks

            with os.fdopen(tmp_fd, "wb") as f:
                tmp_fd = None  # fdopen takes ownership
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = int((downloaded / total) * 100) if total else 0
                    _write_progress(
                        "downloading",
                        pct,
                        downloaded_mb=round(downloaded / 1_048_576, 1),
                        total_mb=round(total / 1_048_576, 1),
                        filename=filename,
                    )

        # Atomic replace — rename temp to final destination
        _write_progress("saving", 99, filename=filename)
        shutil.move(str(tmp_path), str(dest))

        # Remove all other default-cards-*.json files (keep only the new one)
        for old in BULK_DATA_DIR.glob("default-cards-*.json"):
            if old != dest:
                try:
                    old.unlink()
                except OSError:
                    pass

        # Invalidate in-memory index so the next lookup triggers a rebuild
        global _INDEX
        _INDEX = None

        _write_progress("done", 100, filename=filename)
        return dest

    except Exception as exc:
        _write_progress("error", 0, message=str(exc), filename=filename)
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
