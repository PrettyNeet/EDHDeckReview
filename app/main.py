"""
FastAPI application — MTG Commander Deck Review OS
Endpoints:
  POST /api/review             — full deck review from uploaded .txt file
  POST /api/review/text        — full deck review from raw text body
  GET  /api/index/status       — Scryfall index build status
  POST /api/index/build        — (re)build the Scryfall card index
  GET  /api/bulk-data/status   — local file age + remote metadata from Scryfall API
  POST /api/bulk-data/update   — download latest bulk data + rebuild index (background)
  GET  /api/bulk-data/progress — poll download/rebuild progress
  GET  /api/card/{name}        — look up a single card
  GET  /api/suggest            — card name autocomplete
  GET  /health                 — health check
"""

import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Ensure the project root is on sys.path so relative imports work
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.card_lookup import (
    build_index, lookup, suggest_names,
    check_bulk_data_freshness, fetch_bulk_data_metadata, download_bulk_data,
    build_otag_index, OTAG_INDEX_PATH,
)
from app.agents.deck_parser import parse_decklist_text
from app.agents.validator import validate
from app.agents import synergy as synergy_agent
from app.agents import bracket as bracket_agent
from app.agents import plan_analyzer
from app.agents import ai_advisor
from app.agents import edhrec as edhrec_agent
from app.agents import moxfield as moxfield_agent
from app.agents.role_catalog import get_role_catalog

CACHE_DIR = ROOT / "cache"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

BUDGET_TIERS = {
    "budget": {"label": "Budget", "max_card_price": 5.0},
    "moderate": {"label": "Moderate", "max_card_price": 15.0},
    "upgraded": {"label": "Upgraded", "max_card_price": 30.0},
    "premium": {"label": "Premium", "max_card_price": 60.0},
    "unlimited": {"label": "No Limit", "max_card_price": None},
}


def _parse_commander_roles(raw: Optional[str]) -> list[str]:
    """Parse user-supplied target commander roles from JSON or comma text."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(role).strip() for role in parsed if str(role).strip()]
    except json.JSONDecodeError:
        pass
    return [role.strip() for role in raw.split(",") if role.strip()]


def _parse_optional_commander_roles(raw: Optional[str]) -> Optional[list[str]]:
    if raw is None:
        return None
    return _parse_commander_roles(raw)


def _parse_budget_tier(raw: Optional[str]) -> Optional[dict]:
    """Parse the selected budget tier into a structured payload."""
    if not raw:
        return None
    key = raw.strip().lower()
    tier = BUDGET_TIERS.get(key)
    if not tier:
        return None
    return {"tier": key, **tier}


def _parse_tcgplayer_price(card_data: Optional[dict]) -> Optional[float]:
    """Read the cached Scryfall/TCGplayer USD price for a card if available."""
    if not card_data:
        return None
    prices = card_data.get("prices") or {}
    value = prices.get("usd") or prices.get("usd_foil")
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, 2) if parsed > 0 else None


FRONTEND_DIR = ROOT / "frontend"
PROGRESS_FILE = CACHE_DIR / "download_progress.json"

# Guard against concurrent downloads
_download_lock = threading.Lock()

app = FastAPI(
    title="MTG Commander Deck Review",
    version="1.0.0",
    description="AI-powered Commander deck analysis and suggestions",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Static frontend ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>MTG Deck Review</h1><p>Frontend not found.</p>")


@app.get("/api/commander-roles")
async def commander_roles_catalog():
    """Return EDHREC-derived theme and typal role metadata for the Plan tab."""
    return JSONResponse(content=get_role_catalog())


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    index_ready = (CACHE_DIR / "card_index.json").exists()
    bulk = check_bulk_data_freshness()
    return {
        "status": "ok",
        "index_ready": index_ready,
        "bulk_data": {
            "found":      bulk["found"],
            "age_hours":  bulk.get("age_hours"),
            "age_human":  bulk.get("age_human"),
            "is_stale":   bulk.get("is_stale", True),
            "filename":   bulk.get("filename"),
        },
    }


# ─── Index management ────────────────────────────────────────────────────────

@app.get("/api/index/status")
async def index_status():
    cache_path = CACHE_DIR / "card_index.json"
    if cache_path.exists():
        stat = cache_path.stat()
        return {
            "ready": True,
            "size_mb": round(stat.st_size / 1_048_576, 1),
            "modified": stat.st_mtime,
        }
    return {"ready": False}


@app.post("/api/index/build")
async def trigger_index_build(force: bool = False):
    """Build (or rebuild) the Scryfall card index. Can take 20-40 seconds."""
    try:
        path = build_index(force=force)
        stat = path.stat()
        return {
            "success": True,
            "path": str(path),
            "size_mb": round(stat.st_size / 1_048_576, 1),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Otag index ───────────────────────────────────────────────────────────────

@app.get("/api/otag-index/status")
async def otag_index_status():
    """Return readiness and size of the Scryfall otag index cache."""
    if OTAG_INDEX_PATH.exists():
        stat = OTAG_INDEX_PATH.stat()
        return {
            "ready": True,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": stat.st_mtime,
        }
    return {"ready": False}


@app.post("/api/otag-index/build")
async def trigger_otag_index_build(force: bool = False):
    """
    Build (or rebuild) the Scryfall otag index.
    Queries the Scryfall search API for each tracked otag — takes ~10–60 seconds.
    """
    try:
        path = build_otag_index(force=force)
        return {"success": True, "size_kb": round(path.stat().st_size / 1024, 1)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Bulk data management ─────────────────────────────────────────────────────

@app.get("/api/bulk-data/status")
async def bulk_data_status(check_remote: bool = False):
    """
    Return the age of the local bulk data file.
    Pass ?check_remote=true to also query the Scryfall API for the latest
    available version (adds a network round-trip).
    """
    local = check_bulk_data_freshness()
    result: dict = {"local": local, "remote": None}

    if check_remote:
        try:
            result["remote"] = fetch_bulk_data_metadata()
        except Exception as exc:
            result["remote_error"] = str(exc)

    return result


@app.get("/api/bulk-data/progress")
async def bulk_data_progress():
    """Poll the progress of an in-flight download/rebuild."""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"status": "idle"}


def _run_download_and_rebuild():
    """
    Background worker: fetch latest metadata from Scryfall, download the file,
    then rebuild the card index. Writes progress to PROGRESS_FILE throughout.
    """
    CACHE_DIR.mkdir(exist_ok=True)

    def _progress(status: str, pct: int = 0, **extra):
        payload = {"status": status, "pct": pct, **extra}
        try:
            PROGRESS_FILE.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    try:
        _progress("fetching_metadata", 0, message="Querying Scryfall bulk-data API...")
        meta = fetch_bulk_data_metadata()
        _progress(
            "metadata_ready", 2,
            message=f"Found: {meta['name']} — starting download...",
            download_uri=meta["download_uri"],
            remote_updated_at=meta.get("updated_at"),
            size_mb=round((meta.get("size_bytes") or 0) / 1_048_576, 1),
        )

        download_bulk_data(meta["download_uri"], progress_path=PROGRESS_FILE)

        _progress("rebuilding_index", 99, message="Rebuilding card index...")
        build_index(force=True)

        _progress("done", 100, message="Bulk data and index are up to date.")

    except Exception as exc:
        _progress("error", 0, message=str(exc))


@app.post("/api/bulk-data/update")
async def update_bulk_data(background_tasks: BackgroundTasks):
    """
    Fetch the latest Scryfall bulk data and rebuild the card index.
    Runs in the background — poll /api/bulk-data/progress for status.
    Returns 409 if a download is already running.
    """
    if not _download_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A download is already in progress.")

    def _task_with_lock():
        try:
            _run_download_and_rebuild()
        finally:
            _download_lock.release()

    background_tasks.add_task(_task_with_lock)
    return {"started": True, "poll": "/api/bulk-data/progress"}


# ─── Card lookup ──────────────────────────────────────────────────────────────

@app.get("/api/card/{name}")
async def get_card(name: str):
    card = lookup(name)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card '{name}' not found.")
    return card


@app.get("/api/suggest")
async def autocomplete(q: str, limit: int = 8):
    suggestions = suggest_names(q, limit=limit)
    return {"suggestions": suggestions}


# ─── Moxfield import ──────────────────────────────────────────────────────────

@app.get("/api/moxfield")
async def import_moxfield(url: str):
    """Fetch a Moxfield deck URL and convert it to plain-text decklist format."""
    result = moxfield_agent.fetch_and_convert(url)
    if result["error"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ─── Core review pipeline ─────────────────────────────────────────────────────

def _run_review(
    decklist_text: str,
    commander_hint: Optional[str],
    intended_bracket: Optional[int],
    skip_ai: bool,
    ai_provider: Optional[str] = None,
    ai_model: Optional[str] = None,
    commander_roles_override: Optional[list[str]] = None,
    budget_tier: Optional[dict] = None,
) -> dict:
    """Execute the full review pipeline and return the analysis dict."""

    # 1. Parse + enrich with Scryfall
    entries = parse_decklist_text(decklist_text, commander_hint=commander_hint)
    if not entries:
        raise HTTPException(status_code=400, detail="No cards parsed from the decklist.")

    commanders = [e for e in entries if e.is_commander]
    commander_name = commanders[0].name if commanders else None
    partner_name = commanders[1].name if len(commanders) > 1 else None

    # 2. Validate
    validation_result = validate(entries)

    # 3. Synergy analysis (clusters, type breakdown, mana curve)
    synergy_data = synergy_agent.analyze(entries)

    # 4. Bracket evaluation
    bracket_result = bracket_agent.evaluate(entries, intended_bracket=intended_bracket)

    # 5. Plan analysis (RoughDeckPlan.csv framework)
    cmd_color_identity = sorted({c for e in entries if e.is_commander for c in e.color_identity})
    plan_data = plan_analyzer.analyze_plan(
        entries,
        color_identity=cmd_color_identity,
        commander_roles_override=commander_roles_override,
    )

    # 6. EDHREC synergy data (best-effort; non-fatal if unavailable)
    edhrec_data = {"available": False, "high_synergy_cards": [], "top_cards": []}
    if commander_name:
        try:
            edhrec_data = edhrec_agent.fetch_commander_synergy(commander_name)
        except Exception:
            pass

    # Enrich each EDHREC card with its plan roles (Lands / Ramp / Card Advantage / …)
    if edhrec_data.get("available"):
        for card_list_key in ("high_synergy_cards", "top_cards"):
            for card in edhrec_data.get(card_list_key, []):
                card_data = lookup(card["name"])
                if card_data:
                    tl = card_data.get("type_line", "")
                    txt = card_data.get("oracle_text", "")
                    from types import SimpleNamespace
                    if card.get("tcgplayer_price") is None:
                        card["tcgplayer_price"] = _parse_tcgplayer_price(card_data)
                    card["scryfall_uri"] = card_data.get("scryfall_uri")
                    proxy = SimpleNamespace(
                        oracle_text=txt,
                        type_line=tl,
                        cmc=card_data.get("cmc"),
                        power=card_data.get("power"),
                        is_land="Land" in tl,
                        is_creature="Creature" in tl,
                        is_planeswalker="Planeswalker" in tl,
                        is_enchantment="Enchantment" in tl,
                        is_commander=False,
                        quantity=1,
                    )
                    card["plan_roles"] = plan_analyzer.assign_roles(proxy)
                else:
                    card["plan_roles"] = []

    # 7. Creativity score vs EDHREC average deck (best-effort; non-fatal)
    creativity_data = None
    if commander_name and edhrec_data.get("available"):
        try:
            avg_deck = edhrec_agent.fetch_average_deck(commander_name, bracket=bracket_result.bracket)
            if avg_deck.get("available") and avg_deck.get("card_names"):
                creativity_data = edhrec_agent.compute_creativity(entries, avg_deck["card_names"])
                if creativity_data and avg_deck.get("url"):
                    creativity_data["average_deck_url"] = avg_deck["url"]
        except Exception:
            pass

    # 8. Build unified analysis dict
    found_count = sum(e.quantity for e in entries if e.found)
    analysis = {
        "commander": commander_name,
        "partner": partner_name,
        "color_identity": sorted({c for e in entries if e.is_commander for c in e.color_identity}),
        "card_count": sum(e.quantity for e in entries),
        "found_count": found_count,
        "cards": [e.to_dict() for e in entries],
        "validation": validation_result.to_dict(),
        "bracket": bracket_result.to_dict(),
        "synergy_clusters": synergy_data["synergy_clusters"],
        "mana_curve": synergy_data["mana_curve"],
        "type_breakdown": synergy_data["type_breakdown"],
        "role_breakdown": synergy_data["role_breakdown"],
        "missing_staples": synergy_data["missing_staples"],
        "synergy_warnings": synergy_data["warnings"],
        "avg_cmc": synergy_data["avg_cmc"],
        "intended_bracket": intended_bracket,
        "target_commander_roles": commander_roles_override or [],
        "budget": budget_tier,
        # Plan framework data
        "plan": plan_data,
        # EDHREC recommendations
        "edhrec": edhrec_data,
        "creativity": creativity_data,
        "ai_summary": None,
        "ai_suggestions": [],
        "ai_available": False,
        "ai_provider": None,
        "ai_model": None,
    }

    # 8. AI review (optional)
    if not skip_ai:
        ai_result = ai_advisor.generate_review(
            analysis,
            intended_bracket=intended_bracket,
            provider=ai_provider,
            model=ai_model,
        )
        analysis["ai_summary"] = ai_result.get("summary")
        analysis["ai_suggestions"] = ai_result.get("suggestions", [])
        analysis["ai_available"] = ai_result.get("available", False)
        analysis["ai_provider"] = ai_result.get("provider")
        analysis["ai_model"] = ai_result.get("model")
        if "full_response" in ai_result:
            analysis["ai_full_response"] = ai_result["full_response"]

    return analysis


@app.post("/api/review")
async def review_from_file(
    file: UploadFile = File(...),
    commander: Optional[str] = Form(None),
    intended_bracket: Optional[int] = Form(None),
    skip_ai: bool = Form(False),
    ai_provider: Optional[str] = Form(None),
    ai_model: Optional[str] = Form(None),
    commander_roles: Optional[str] = Form(None),
    budget_tier: Optional[str] = Form(None),
):
    """Upload a .txt decklist file for full review."""
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    analysis = _run_review(
        text,
        commander,
        intended_bracket,
        skip_ai,
        ai_provider,
        ai_model,
        _parse_optional_commander_roles(commander_roles),
        _parse_budget_tier(budget_tier),
    )

    # Save result to disk
    safe_name = (file.filename or "deck").replace(" ", "_").replace(".txt", "")
    out_path = RESULTS_DIR / f"{safe_name}_review.json"
    out_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis["saved_to"] = str(out_path)

    return JSONResponse(content=analysis)


@app.post("/api/review/text")
async def review_from_text(
    decklist: str = Form(...),
    commander: Optional[str] = Form(None),
    intended_bracket: Optional[int] = Form(None),
    skip_ai: bool = Form(False),
    ai_provider: Optional[str] = Form(None),
    ai_model: Optional[str] = Form(None),
    commander_roles: Optional[str] = Form(None),
    budget_tier: Optional[str] = Form(None),
):
    """Submit a decklist as raw text for full review."""
    analysis = _run_review(
        decklist,
        commander,
        intended_bracket,
        skip_ai,
        ai_provider,
        ai_model,
        _parse_optional_commander_roles(commander_roles),
        _parse_budget_tier(budget_tier),
    )
    return JSONResponse(content=analysis)
