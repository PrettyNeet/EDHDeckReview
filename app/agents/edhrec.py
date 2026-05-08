"""
EDHREC synergy fetcher.
Fetches high-synergy card recommendations for a commander from the EDHREC JSON endpoint.
URL pattern: https://json.edhrec.com/pages/commanders/{slug}.json
"""

import re
import json
import urllib.request
import html
from typing import Optional

from types import SimpleNamespace

from app.agents.card_lookup import _normalize_name, lookup
from app.agents.plan_analyzer import assign_roles, subcategorize_plan_card

EDHREC_JSON_BASE    = "https://json.edhrec.com/pages/commanders"
EDHREC_PAGE_BASE    = "https://edhrec.com/commanders"
EDHREC_AVGDECK_BASE = "https://json.edhrec.com/pages/average-decks"
_USER_AGENT = "MTG-DeckReview/1.0 (local tool)"

_BASIC_LAND_NAMES = frozenset({
    "plains", "island", "swamp", "mountain", "forest",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest", "wastes",
})


def _coerce_price(value) -> Optional[float]:
    """Convert loose EDHREC price values into a float."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2) if value > 0 else None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        try:
            parsed = float(cleaned)
        except ValueError:
            return None
        return round(parsed, 2) if parsed > 0 else None
    return None


def _first_price(*values) -> Optional[float]:
    for value in values:
        price = _coerce_price(value)
        if price is not None:
            return price
    return None


def _extract_tcgplayer_price(cardview: dict) -> Optional[float]:
    """
    Pull the best-available TCGplayer price from an EDHREC cardview.
    EDHREC's JSON shape is not perfectly stable, so check a few common spots.
    """
    prices = cardview.get("prices")
    tcgplayer = None
    if isinstance(prices, dict):
        tcgplayer = prices.get("tcgplayer")

    if isinstance(tcgplayer, dict):
        return _first_price(
            tcgplayer.get("price"),
            tcgplayer.get("market_price"),
            tcgplayer.get("market"),
            tcgplayer.get("mid"),
            tcgplayer.get("low"),
        )

    if isinstance(tcgplayer, (int, float, str)):
        return _coerce_price(tcgplayer)

    card = cardview.get("card")
    card_prices = card.get("prices") if isinstance(card, dict) else None
    card_tcgplayer = card_prices.get("tcgplayer") if isinstance(card_prices, dict) else None
    if isinstance(card_tcgplayer, dict):
        return _first_price(
            card_tcgplayer.get("price"),
            card_tcgplayer.get("market_price"),
            card_tcgplayer.get("market"),
            card_tcgplayer.get("mid"),
            card_tcgplayer.get("low"),
        )

    return _first_price(
        cardview.get("tcgplayer_price"),
        cardview.get("price"),
        cardview.get("market_price"),
    )


def slugify(name: str) -> str:
    """Convert a commander name to an EDHREC URL slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s]", "", slug)   # remove non-alphanumeric
    slug = re.sub(r"\s+", "-", slug.strip())   # spaces -> dashes
    slug = re.sub(r"-+", "-", slug)            # collapse multiple dashes
    return slug


def fetch_commander_synergy(commander_name: str) -> dict:
    """
    Fetch EDHREC data for a commander.
    Returns high-synergy cards and top cards with synergy scores and inclusion rates.
    On failure returns {"available": False, "error": "..."}.
    """
    slug = slugify(commander_name)
    url = f"{EDHREC_JSON_BASE}/{slug}.json"
    page_url = f"{EDHREC_PAGE_BASE}/{slug}"
    json_error = None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        json_error = str(exc)
        data = None

    high_synergy: list[dict] = []
    top_cards: list[dict] = []

    if data is not None:
        # Navigate EDHREC JSON structure
        cardlists = []
        try:
            cardlists = (
                data.get("container", {})
                    .get("json_dict", {})
                    .get("cardlists", [])
            )
        except AttributeError:
            pass

        for section in cardlists:
            tag = section.get("tag", "").lower().replace(" ", "")
            views = section.get("cardviews", [])
            if tag == "highsynergycards":
                high_synergy = _parse_cardviews(views, "High Synergy", min_synergy=0.0)
            elif tag == "topcards":
                top_cards = _parse_cardviews(views, "Top", min_synergy=0.05)

    if not high_synergy and not top_cards:
        try:
            high_synergy, top_cards = _fetch_from_commander_page(page_url)
        except Exception as exc:
            return {
                "available": False,
                "error": json_error or str(exc),
                "fallback_error": str(exc) if json_error else None,
                "slug": slug,
                "url": page_url,
                "high_synergy_cards": [],
                "top_cards": [],
            }

    return {
        "available": True,
        "slug": slug,
        "url": page_url,
        "error": json_error,
        "high_synergy_cards": high_synergy[:24],
        "top_cards": top_cards[:24],
    }


def _parse_cardviews(views: list, source: str, min_synergy: float = 0.0) -> list[dict]:
    result = []
    for cv in views:
        name = cv.get("name", "")
        if not name:
            continue
        synergy = cv.get("synergy") or 0
        num_decks = cv.get("num_decks") or 0
        potential = cv.get("potential_decks") or 0
        inclusion_pct = round(num_decks / potential * 100, 1) if potential else 0

        if synergy < min_synergy:
            continue

        result.append({
            "name": name,
            "synergy": round(synergy * 100, 1),   # decimal -> percentage
            "num_decks": num_decks,
            "inclusion_pct": inclusion_pct,
            "tcgplayer_price": _extract_tcgplayer_price(cv),
            "source": source,
        })
    return result


def _parse_deck_count(text: str) -> int:
    raw = text.strip().upper().replace(",", "")
    multiplier = 1
    if raw.endswith("K"):
        raw = raw[:-1]
        multiplier = 1_000
    elif raw.endswith("M"):
        raw = raw[:-1]
        multiplier = 1_000_000
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return 0


def _extract_section_cards(lines: list[str], header: str, source: str) -> list[dict]:
    try:
        start = lines.index(header) + 1
    except ValueError:
        return []

    stop_headers = {
        "High Synergy Cards", "Top Cards", "Game Changers", "Creatures", "Instants",
        "Sorceries", "Utility Artifacts", "Enchantments", "Planeswalkers",
        "Utility Lands", "Mana Artifacts", "Lands", "New Cards", "Back to Top",
    }

    results: list[dict] = []
    i = start
    while i + 2 < len(lines):
        line = lines[i]
        if line in stop_headers and i > start:
            break

        meta = lines[i + 1] if i + 1 < len(lines) else ""
        synergy_line = lines[i + 2] if i + 2 < len(lines) else ""

        if (
            line
            and "inclusion" not in line.lower()
            and "synergy" not in line.lower()
            and "inclusion" in meta.lower()
            and "synergy" in synergy_line.lower()
        ):
            name = line.strip()
            meta_match = re.search(
                r"(?P<inclusion>[\d.]+)%inclusion\s+(?P<num>[\d.]+[KM]?)\s+decks\s+(?P<potential>[\d.]+[KM]?)\s+decks",
                meta,
                re.IGNORECASE,
            )
            synergy_match = re.search(r"([+-]?[\d.]+)%\s+synergy", synergy_line, re.IGNORECASE)
            if meta_match and synergy_match:
                results.append({
                    "name": name,
                    "synergy": float(synergy_match.group(1)),
                    "num_decks": _parse_deck_count(meta_match.group("num")),
                    "inclusion_pct": float(meta_match.group("inclusion")),
                    "tcgplayer_price": None,
                    "source": source,
                })
                i += 3
                continue
        i += 1

    return results


def _fetch_from_commander_page(page_url: str) -> tuple[list[dict], list[dict]]:
    req = urllib.request.Request(page_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        html_text = resp.read().decode("utf-8", errors="replace")

    text = re.sub(r"<script\b[^>]*>.*?</script>", "\n", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    high_synergy = _extract_section_cards(lines, "High Synergy Cards", "High Synergy")
    top_cards = _extract_section_cards(lines, "Top Cards", "Top")
    if not high_synergy and not top_cards:
        raise ValueError("Could not parse EDHREC commander page.")
    return high_synergy, top_cards


# ── Average deck + creativity score ───────────────────────────────────────────

def _parse_average_deck_json(data: dict) -> list[str]:
    """
    Extract card names from the EDHREC average-deck JSON response.
    Tries multiple paths defensively since the shape varies by commander.
    Returns a deduplicated list of display-name strings.
    """
    names = []
    try:
        jd = data.get("container", {}).get("json_dict", {})

        # Path 1: cardlists array (same structure as commander page)
        for section in jd.get("cardlists", []):
            for cv in section.get("cardviews", []):
                name = cv.get("name", "").strip()
                if name:
                    names.append(name)

        # Path 2: decklist text blob in json_dict
        if not names:
            dl = jd.get("decklist", "")
            if isinstance(dl, str):
                for line in dl.splitlines():
                    name = re.sub(r"^\d+\s+", "", line.strip()).strip()
                    if name and not name.startswith(("#", "//")):
                        names.append(name)

        # Path 3: top-level decklist key
        if not names:
            dl = data.get("decklist", [])
            if isinstance(dl, list):
                for item in dl:
                    name = (str(item).strip() if not isinstance(item, dict)
                            else item.get("name", ""))
                    name = re.sub(r"^\d+\s+", "", name).strip()
                    if name:
                        names.append(name)
            elif isinstance(dl, str):
                for line in dl.splitlines():
                    name = re.sub(r"^\d+\s+", "", line.strip()).strip()
                    if name:
                        names.append(name)
    except Exception:
        pass

    return list(dict.fromkeys(n for n in names if n))


_EDHREC_BRACKET_LABEL = {
    1: "exhibition",
    2: "core",
    3: "upgraded",
    4: "optimized",
    5: "cedh",
}


def fetch_average_deck(commander_name: str, bracket: Optional[int] = None) -> dict:
    """
    Fetch the EDHREC average deck for a commander.
    When `bracket` is provided (1–5), tries the bracket-specific URL first and falls
    back to the general average deck if that returns no cards.
    Returns {"available": bool, "card_names": list[str], "slug": str, "url": str}.
    Non-fatal: returns available=False on any error.
    """
    slug = slugify(commander_name)
    bracket_label = _EDHREC_BRACKET_LABEL.get(bracket) if bracket else None

    candidates: list[tuple[str, str]] = []  # (json_url, page_url)
    if bracket_label:
        candidates.append((
            f"{EDHREC_AVGDECK_BASE}/{slug}/{bracket_label}.json",
            f"https://edhrec.com/average-decks/{slug}/{bracket_label}",
        ))
    candidates.append((
        f"{EDHREC_AVGDECK_BASE}/{slug}.json",
        f"https://edhrec.com/average-decks/{slug}",
    ))

    base = {"slug": slug, "card_names": []}
    last_exc = None
    for json_url, page_url in candidates:
        try:
            req = urllib.request.Request(
                json_url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            card_names = _parse_average_deck_json(data)
            if card_names:
                return {**base, "url": page_url, "available": True, "card_names": card_names}
        except Exception as exc:
            last_exc = exc

    err = {"available": False, "url": candidates[-1][1]}
    if last_exc:
        err["error"] = str(last_exc)
    return {**base, **err}


def _creativity_label(score: int) -> str:
    if score <= 20: return "Stock Build"
    if score <= 40: return "Tuned"
    if score <= 60: return "Refined"
    if score <= 80: return "Innovative"
    return "Brewer"


def compute_creativity(user_entries: list, average_card_names: list[str]) -> dict:
    """
    Diff user's deck vs EDHREC average deck and return a creativity payload.
    Excludes commanders and basic lands from both sides before comparing.
    """
    user_eligible = [e for e in user_entries if not e.is_commander and not e.is_basic_land]

    user_norm: dict[str, str] = {}
    for e in user_eligible:
        norm = _normalize_name(e.name or e.raw_name or "")
        if norm:
            user_norm[norm] = e.name or e.raw_name

    avg_norm: dict[str, str] = {}
    for name in average_card_names:
        n = _normalize_name(name)
        if n and n not in _BASIC_LAND_NAMES:
            avg_norm[n] = name

    user_set = set(user_norm)
    avg_set  = set(avg_norm)

    unique_norms   = user_set - avg_set
    overlap_norms  = user_set & avg_set
    avg_only_norms = avg_set  - user_set

    score = round(len(unique_norms) / max(len(user_set), 1) * 100)

    def _enrich(norms: set, norm_to_display: dict) -> list[dict]:
        result = []
        for norm in sorted(norms):
            display = norm_to_display[norm]
            cd = lookup(display) or {}
            tl = cd.get("type_line", "")
            txt = cd.get("oracle_text", "")
            proxy = SimpleNamespace(
                name=display,
                oracle_text=txt,
                type_line=tl,
                cmc=cd.get("cmc"),
                power=cd.get("power"),
                is_land="Land" in tl,
                is_creature="Creature" in tl,
                is_planeswalker="Planeswalker" in tl,
                is_enchantment="Enchantment" in tl,
                is_commander=False,
                quantity=1,
            )
            roles = assign_roles(proxy)
            subcategory = subcategorize_plan_card(proxy, []) if "Plan Cards" in roles else None
            prices = cd.get("prices") or {}
            usd = prices.get("usd") or prices.get("usd_foil")
            result.append({
                "name": display,
                "scryfall_uri": cd.get("scryfall_uri"),
                "type_line": tl or None,
                "color_identity": cd.get("color_identity") or [],
                "cmc": cd.get("cmc"),
                "plan_roles": roles,
                "plan_subcategory": subcategory,
                "usd_price": float(usd) if usd else None,
            })
        return result

    return {
        "score": score,
        "label": _creativity_label(score),
        "unique_to_user":  _enrich(unique_norms,   user_norm),
        "average_only":    _enrich(avg_only_norms,  avg_norm),
        "overlap_count":   len(overlap_norms),
        "user_card_count": len(user_set),
        "avg_card_count":  len(avg_set),
    }
