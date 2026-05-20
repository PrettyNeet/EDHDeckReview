# Project Reference

Low-token reference for future work. Read this first; open [architecture.md](../architecture.md) only when you need deeper implementation detail.

## What This Project Is

FastAPI app for reviewing MTG Commander decklists locally or on Vercel using:

- Local Scryfall bulk data compiled into `cache/card_index.json`
- Optional compressed deploy caches: `cache/card_index.json.gz`, `cache/otag_index.json.gz`, and `cache/index_metadata.json`
- Rule-based deck analysis agents
- Optional Anthropic/OpenAI/Ollama-powered review suggestions
- Optional EDHREC commander recommendations
- Optional Moxfield import flow
- Optional Supabase Auth + `allowed_users` invite whitelist for hosted use

Primary entrypoint: [app/main.py](../app/main.py)
Vercel entrypoint: [index.py](../index.py)

## Core Pipeline

`decklist text`
→ `deck_parser.parse_decklist_text()`
→ `validator.validate()`
→ `synergy.analyze()`
→ `bracket.evaluate()`
→ `plan_analyzer.analyze_plan()`
→ `edhrec.fetch_commander_synergy()` best-effort
→ `edhrec.fetch_average_deck()` + `edhrec.compute_creativity()` best-effort
→ `ai_advisor.generate_review()` unless skipped or `FEATURE_AI_REVIEW_ENABLED=false`
→ JSON response

## Current Product Shape

- Single-page frontend with no build step: [frontend/index.html](../frontend/index.html), [frontend/app.js](../frontend/app.js), [frontend/style.css](../frontend/style.css)
- Review inputs: validated `.txt` file upload, pasted text, or Moxfield URL
- Review inputs also include intended bracket, budget target, optional AI provider/model when enabled, and optional commander-role targets
- Review outputs: overview, plan analysis, validation, synergy, bracket, Analysis, full card list
- Bracket system is `1–5`, not `1–4`
- File uploads save JSON into `results/` locally only; Vercel returns JSON without writing results
- Results view has a `New Deck Review` button that returns to the submission page

## Source Of Truth By Area

- API routes and orchestration: [app/main.py](../app/main.py)
- Supabase invite auth dependency: [app/auth.py](../app/auth.py)
- Vercel deployment entrypoint: [index.py](../index.py)
- Scryfall index and freshness/update flow: [app/agents/card_lookup.py](../app/agents/card_lookup.py)
- Deck parsing: [app/agents/deck_parser.py](../app/agents/deck_parser.py)
- Commander legality validation: [app/agents/validator.py](../app/agents/validator.py)
- Rule-based synergy analysis: [app/agents/synergy.py](../app/agents/synergy.py)
- Power bracket logic: [app/agents/bracket.py](../app/agents/bracket.py)
- RoughDeckPlan analysis: [app/agents/plan_analyzer.py](../app/agents/plan_analyzer.py)
- AI review implementation: [app/agents/ai_advisor.py](../app/agents/ai_advisor.py)
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
- `health` and `/api/index/status` treat either `cache/card_index.json` or `cache/card_index.json.gz` as index-ready.
- Hosted deploys refresh compressed cache artifacts with `scripts/refresh_deploy_cache.py` and `.github/workflows/refresh-scryfall-cache.yml`; runtime rebuild/download endpoints are disabled on Vercel.
- AI review is optional and feature-flagged. It uses `AI_PROVIDER`/request fields to choose Anthropic, OpenAI, or Ollama only when `FEATURE_AI_REVIEW_ENABLED=true`.
- AI suggestions are post-validated against the local bulk index before returning to the UI: suggested adds must exist, be Commander-legal, fit commander color identity, not already be in the deck, and respect the selected budget target when one is set.
- When AI review is disabled, the first-page AI provider/model controls are hidden, backend model calls are blocked, and the Analysis tab still shows EDHREC recommendations and creativity data.
- Bracket combo detection is based on completed two-card combo pairs, not isolated combo-adjacent cards. Early two-card combos push toward Bracket 4+, while slower completed combos can remain in Bracket 3.
- `.env` is loaded by both `run.py` and `app/agents/ai_advisor.py`, so provider keys work from `python run.py`, `uvicorn`, or IDE launch paths.
- Visible card names should generally be Scryfall links. Current coverage includes commander header details, Synergy, Bracket, AI suggestions, EDHREC rows, Plan role/map sections, and Card List.
- EDHREC table metric columns (`Synergy`, `Inclusion`, `Decks`, `Price`) are centered in the UI.
- Bulk-data refresh writes progress to `cache/download_progress.json` and the frontend polls it.
- Creativity score diffs the user's deck (non-commander, non-basic-land cards) against the EDHREC average deck for that commander, producing a 0–100 score with labels: Stock Build / Tuned / Refined / Innovative / Brewer. Displayed in the Analysis tab. Response field `creativity` is `null` if EDHREC has no average deck for that commander.
- Otag-based classification uses `cache/otag_index.json` (built by `python build_otag_index.py`). When present, `classify_role()` in `synergy.py` and `assign_roles()` in `plan_analyzer.py` use it as the primary source and fall back to regex for any card not in the index. The app works without it (pure regex mode).
- Supabase Auth is enabled when configured. Public endpoints are `/`, static assets, `/health`, and `/api/config`; protected API endpoints require a valid Supabase session and an active `public.allowed_users` row.
- Users create/reset their Supabase password from the web login panel; the backend whitelist remains the source of authorization.
- Action logging writes durable Supabase rows to `public.user_action_logs` when `ACTION_LOGGING_ENABLED` is on. It logs Moxfield imports and review submissions/completions/failures with full decklist text, user identity, request IDs, timings, options, and summarized results. Logging failures are non-fatal.

## Important Endpoints

- `GET /health`
- `GET /api/config`
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
python scripts/refresh_deploy_cache.py   # refresh compressed deploy cache for Vercel
python run.py
```

Open `http://localhost:8000`

## AI Provider Env

- `AI_PROVIDER=auto|anthropic|openai|ollama`
- `ANTHROPIC_API_KEY=...`
- `ANTHROPIC_MODEL=claude-sonnet-4-6`
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=gpt-4o-mini`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=llama3.1`

## Hosted Env / Feature Flags

- `INVITE_AUTH_ENABLED=true|false`
- `SUPABASE_URL=...`
- `SUPABASE_ANON_KEY=...`
- `SUPABASE_SERVICE_ROLE_KEY=...`
- `FEATURE_AI_REVIEW_ENABLED=true|false` (`false` by default on Vercel, `true` locally)
- `ACTION_LOGGING_ENABLED=true|false`
- `ACTION_LOG_IP_HASH_SALT=...`

## Hosted SQL

- `docs/supabase-action-logging.sql` creates `public.user_action_logs` for durable analytics.

## When Editing

- Backend feature changes usually start in [app/main.py](../app/main.py) plus one agent module.
- UI changes usually need matching edits in all three frontend files.
- For UI/UX changes, read [docs/design-brief.md](design-brief.md) first — it defines the design system (tokens, fonts, component patterns) so new work stays visually consistent.
- If behavior and docs disagree, trust the code first, especially `app/main.py` and the relevant agent.
