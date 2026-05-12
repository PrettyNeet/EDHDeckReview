# Project Reference

Low-token reference for future work. Read this first; open [architecture.md](../architecture.md) only when you need deeper implementation detail.

## What This Project Is

Local FastAPI app for reviewing MTG Commander decklists using:

- Local Scryfall bulk data compiled into `cache/card_index.json`
- Rule-based deck analysis agents
- Optional Anthropic/OpenAI/Ollama-powered review suggestions
- Optional EDHREC commander recommendations
- Optional Moxfield import flow

Primary entrypoint: [app/main.py](../app/main.py)

## Core Pipeline

`decklist text`
→ `deck_parser.parse_decklist_text()`
→ `validator.validate()`
→ `synergy.analyze()`
→ `bracket.evaluate()`
→ `plan_analyzer.analyze_plan()`
→ `edhrec.fetch_commander_synergy()` best-effort
→ `edhrec.fetch_average_deck()` + `edhrec.compute_creativity()` best-effort
→ `ai_advisor.generate_review()` unless skipped
→ JSON response

## Current Product Shape

- Single-page frontend with no build step: [frontend/index.html](../frontend/index.html), [frontend/app.js](../frontend/app.js), [frontend/style.css](../frontend/style.css)
- Review inputs: file upload, pasted text, or Moxfield URL
- Review inputs also include intended bracket, budget target, AI provider/model, and optional commander-role targets
- Review outputs: overview, plan analysis, validation, synergy, bracket, Advisor, full card list
- Bracket system is `1–5`, not `1–4`
- File uploads save JSON into `results/`; `/api/review/text` returns JSON without saving

## Source Of Truth By Area

- API routes and orchestration: [app/main.py](../app/main.py)
- Scryfall index and freshness/update flow: [app/agents/card_lookup.py](../app/agents/card_lookup.py)
- Deck parsing: [app/agents/deck_parser.py](../app/agents/deck_parser.py)
- Commander legality validation: [app/agents/validator.py](../app/agents/validator.py)
- Rule-based synergy analysis: [app/agents/synergy.py](../app/agents/synergy.py)
- Power bracket logic: [app/agents/bracket.py](../app/agents/bracket.py)
- RoughDeckPlan analysis: [app/agents/plan_analyzer.py](../app/agents/plan_analyzer.py)
- Advisor review: [app/agents/ai_advisor.py](../app/agents/ai_advisor.py)
- EDHREC fetch: [app/agents/edhrec.py](../app/agents/edhrec.py)
- Moxfield import: [app/agents/moxfield.py](../app/agents/moxfield.py)
- Shared data models: [app/models/card.py](../app/models/card.py)

## Important Behavior Notes

- Commander detection priority is: explicit UI override → `Commander:` tag → first commander-eligible legend in list.
- `CardEntry` is the shared object passed through most of the backend.
- `plan_analyzer` is the largest logic module and the main hotspot for deckbuilding heuristics.
- Commander role detection uses EDHREC theme/typal CSV catalogs (`docs/edhdeckthemes.csv`, `docs/edhdecktypals.csv`) plus commander/deck evidence to rank target roles. The Plan tab also gets descriptions and grouped Theme/Typal options from `/api/commander-roles`.
- Plan tab target controls let the user edit/remove commander role tags and planned bracket, then re-run analysis. API field `commander_roles` is treated as user target roles.
- Plan tab Card Role Map has an `Export View` control that copies the current filtered/sorted card-role table to the clipboard as parser-compatible decklist text (`Commander:` tag lines plus `qty card name` lines), matching the import format.
- EDHREC data is non-fatal; failures are swallowed and the review still completes.
- EDHREC recommendation rows are enriched after fetch with `plan_roles`, `scryfall_uri`, and a `tcgplayer_price` value. If EDHREC omits price data, the app falls back to cached Scryfall `prices.usd` / `prices.usd_foil`.
- `card_lookup.build_index()` now reads either plain JSON or gzip-compressed Scryfall bulk files transparently and includes `prices` in the cached index.
- Advisor review is optional. It uses `AI_PROVIDER`/request fields to choose Anthropic, OpenAI, or Ollama, and falls back when no configured provider is available.
- Advisor suggestions are post-validated against the local bulk index before returning to the UI: suggested adds must exist, be Commander-legal, fit commander color identity, not already be in the deck, and respect the selected budget target when one is set.
- Bracket combo detection is based on completed two-card combo pairs, not isolated combo-adjacent cards. Early two-card combos push toward Bracket 4+, while slower completed combos can remain in Bracket 3.
- `.env` is loaded by both `run.py` and `app/agents/ai_advisor.py`, so provider keys work from `python run.py`, `uvicorn`, or IDE launch paths.
- Visible card names should generally be Scryfall links. Current coverage includes commander header details, Synergy, Bracket, Advisor suggestions, EDHREC rows, Plan role/map sections, and Card List.
- EDHREC table metric columns (`Synergy`, `Inclusion`, `Decks`, `Price`) are centered in the UI.
- Bulk-data refresh writes progress to `cache/download_progress.json` and the frontend polls it.
- Creativity score diffs the user's deck (non-commander, non-basic-land cards) against the EDHREC average deck for that commander, producing a 0–100 score with labels: Stock Build / Tuned / Refined / Innovative / Brewer. Displayed in the Advisor tab. Response field `creativity` is `null` if EDHREC has no average deck for that commander.
- Otag-based classification uses `cache/otag_index.json` (built by `python build_otag_index.py`). When present, `classify_role()` in `synergy.py` and `assign_roles()` in `plan_analyzer.py` use it as the primary source and fall back to regex for any card not in the index. The app works without it (pure regex mode).

## Important Endpoints

- `GET /health`
- `GET /api/index/status`
- `POST /api/index/build`
- `GET /api/otag-index/status`
- `POST /api/otag-index/build`
- `GET /api/bulk-data/status`
- `POST /api/bulk-data/update`
- `GET /api/bulk-data/progress`
- `GET /api/card/{name}`
- `GET /api/suggest?q=...`
- `GET /api/commander-roles`
- `GET /api/moxfield?url=...`
- `POST /api/review`
- `POST /api/review/text`

## Useful Commands

```bash
pip install -r requirements.txt
python build_index.py
python build_otag_index.py   # optional but recommended — builds otag classification cache
python run.py
```

Open `http://localhost:8000`

## Advisor Provider Env

- `AI_PROVIDER=auto|anthropic|openai|ollama`
- `ANTHROPIC_API_KEY=...`
- `ANTHROPIC_MODEL=claude-sonnet-4-6`
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=gpt-4o-mini`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=llama3.1`

## When Editing

- Backend feature changes usually start in [app/main.py](../app/main.py) plus one agent module.
- UI changes usually need matching edits in all three frontend files.
- If behavior and docs disagree, trust the code first, especially `app/main.py` and the relevant agent.
