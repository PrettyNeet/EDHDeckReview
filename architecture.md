# MTG Commander Deck Review — Architecture Reference

This document describes every file's purpose, structure, key functions, and the data that flows between them. Read this before planning any change.

---

## Project Layout

```
DeckReview/
├── app/
│   ├── main.py                   FastAPI app, API routes, review pipeline
│   ├── models/
│   │   └── card.py               All dataclasses (CardEntry, ValidationResult, etc.)
│   └── agents/
│       ├── card_lookup.py        Scryfall index builder and card lookup
│       ├── deck_parser.py        .txt → list[CardEntry]
│       ├── validator.py          Commander format rules
│       ├── synergy.py            Role bars, mana curve, synergy clusters, missing staples
│       ├── bracket.py            Power bracket 1–5 assignment
│       ├── plan_analyzer.py      RoughDeckPlan framework evaluation
│       ├── ai_advisor.py         Anthropic/OpenAI/Ollama integration (Advisor review)
│       ├── edhrec.py             EDHREC JSON scraper
│       └── moxfield.py           Moxfield URL → decklist text
├── frontend/
│   ├── index.html                Single-page UI structure
│   ├── app.js                    All frontend logic (render, sort, fetch)
│   └── style.css                 Dark-theme CSS
├── Scryfall src/
│   └── default-cards-*.json     Raw Scryfall bulk data (~500 MB JSON, gitignored)
├── cache/
│   └── card_index.json           Compiled name-keyed card lookup cache (~37k entries)
├── results/                      Saved review JSON outputs (per-submission)
├── decks/                        Sample .txt decklists for testing
├── RoughDeckPlan.csv             Source data for the plan framework targets
├── requirements.txt              fastapi, uvicorn, anthropic, python-multipart
└── run.py / build_index.py       Dev entry points (uvicorn wrapper, standalone index builder)
```

---

## Data Flow (end to end)

```
User input (file / paste / Moxfield URL)
  │
  ▼
POST /api/review  (or /api/review/text)
  │
  ├─ deck_parser.parse_decklist_text()
  │    └─ card_lookup.lookup() per card     →  list[CardEntry]
  │
  ├─ validator.validate()                   →  ValidationResult
  ├─ synergy.analyze()                      →  mana_curve, type_breakdown,
  │                                             role_breakdown, synergy_clusters,
  │                                             missing_staples, avg_cmc
  ├─ bracket.evaluate()                     →  BracketAssessment
  ├─ plan_analyzer.analyze_plan()           →  plan dict (coverage, curve, playtest…)
  ├─ edhrec.fetch_commander_synergy()       →  high_synergy_cards, top_cards
  │    └─ card_lookup.lookup() per card        (enriches with plan_roles)
  └─ ai_advisor.generate_review()           →  ai_summary, ai_suggestions
       (optional, skippable)
  │
  ▼
analysis dict  →  JSON response  →  frontend renderResults()
```

---

## Backend Files

### `app/models/card.py`

All shared dataclasses. **No logic** — pure data containers.

| Class | Purpose |
|---|---|
| `CardEntry` | One card slot. Holds raw name, Scryfall data, `is_commander` flag. |
| `ValidationResult` | `valid: bool`, `errors: list[str]`, `warnings: list[str]` |
| `SynergyCluster` | `name`, `description`, `cards: list[str]`, `strength` (low/medium/high) |
| `BracketAssessment` | `bracket: int` (1-5), `label`, `reasoning`, GC/fast-mana/combo counts |
| `DeckAnalysis` | Aggregate result object (not actively used in pipeline — main.py builds dict directly) |

**Key `CardEntry` properties** (computed from `type_line`/`oracle_text`):
- `is_commander`, `is_basic_land`, `is_creature`, `is_land`, `is_artifact`, `is_enchantment`, `is_instant`, `is_sorcery`, `is_planeswalker`, `is_legendary`
- `can_be_commander` — `True` if Legendary Creature or has "can be your commander" text
- `to_dict()` — serializes via `dataclasses.asdict()`

---

### `app/agents/card_lookup.py`

Scryfall card database. Owns the name-keyed index (`cache/card_index.json`).

**Key constants:**
- `CARD_FIELDS` — the subset of Scryfall fields kept per card (name, cmc, color_identity, oracle_text, type_line, game_changer, rarity, scryfall_uri, legalities, card_faces, `prices`, etc.)
- `STALE_HOURS = 24` — bulk data freshness threshold
- `BULK_DATA_TYPE = "default_cards"` — which Scryfall bulk export is used

**Key functions:**
| Function | Notes |
|---|---|
| `build_index(force=False)` | Reads `Scryfall src/default-cards-*.json`, auto-detects plain JSON vs gzip-compressed JSON, deduplicates by oracle_id, writes `cache/card_index.json`. ~30 sec on first run. |
| `lookup(card_name)` | Returns card dict or `None`. Normalizes name (lowercase, strip accents/apostrophes). |
| `suggest_names(partial, limit=8)` | Substring match for autocomplete (`GET /api/suggest`). |
| `check_bulk_data_freshness()` | Returns age of local bulk file; `is_stale` = True after 24 h. |
| `fetch_bulk_data_metadata()` | Calls Scryfall bulk-data API, returns download URI + metadata. |
| `download_bulk_data(uri)` | Streams bulk JSON to `Scryfall src/`, atomically replaces old file, clears `_INDEX`. |

**Index building logic:** Two-pass deduplication by `oracle_id` — prefers Commander-legal printings. Double-faced cards flatten front face fields to root. Split cards (`Fire // Ice`) are indexed under both half-names. If an older in-memory or on-disk index is missing `prices`, the module rebuilds so downstream price lookups can work.

---

### `app/agents/deck_parser.py`

Converts raw text → `list[CardEntry]`.

**Supported input formats:**
```
1 Rhystic Study
1x Sol Ring
Commander: Atraxa, Praetor's Voice   ← explicit tag
// Section headers are skipped
# Hash comments are skipped
```

**Commander detection order:**
1. `commander_hint` parameter (from UI input field)
2. Explicit `Commander:` tag lines
3. Auto-detect: first `Legendary Creature` (or "can be your commander") in the list

After parsing, every entry is enriched via `card_lookup.lookup()`. The `found` flag distinguishes matched vs unmatched cards throughout the pipeline.

---

### `app/agents/validator.py`

Enforces Commander format rules. Returns `ValidationResult`.

**Checks (in order):**
1. Commander present (1–2 max)
2. Commander is legal (Legendary Creature or "can be your commander")
3. Partner pair validity (Partner / Partner With / Friends Forever)
4. Colorless commander warning
5. Card count = 100
6. Singleton (exempt: basic lands, "a deck can have any number of cards named…")
7. Color identity subset of commander's identity
8. Scryfall legality (`legalities.commander == "legal"`)
9. Manual ban list (`BANNED_CARDS` set — covers recent bans Scryfall may lag on)

---

### `app/agents/synergy.py`

Rule-based analysis. No external calls.

**Outputs:**
- `mana_curve` — `{0..7+: count}`, CMC buckets for non-land cards
- `type_breakdown` — `{Creatures, Instants, Sorceries, Artifacts, Enchantments, Planeswalkers, Lands: count}`
- `role_breakdown` — `{ramp, draw, removal, boardwipes, tutors, threats, synergy, lands: count}` (single primary role per card)
- `synergy_clusters` — list of `SynergyCluster` dicts; threshold: 3+ cards match a rule
- `missing_staples` — format staples not in deck, filtered to commander's color identity
- `warnings` — list of threshold warnings (e.g. "Low ramp count")
- `avg_cmc` — float, non-land cards only

**`SYNERGY_RULES`** — 20 hardcoded lambda rules (Token Generation, Sacrifice Engine, Counter Manipulation, Spellslinger, Landfall, etc.). Each rule is `{name, check: Callable[[CardEntry], bool], description}`. A cluster becomes "high" at 8+ cards, "medium" at 5+, "low" at 3+.

**`STAPLES_BY_COLOR`** — ~4–7 staples per color + colorless (Sol Ring, Command Tower, etc.). Always checked against the commander's color identity.

> **Note:** `classify_role()` here is for the simple role bar chart only. Multi-role tagging lives in `plan_analyzer.assign_roles()`.

---

### `app/agents/bracket.py`

Assigns bracket 1–5 based on the official Commander bracket system.

**Bracket definitions:**

| Bracket | Label | Key rules |
|---|---|---|
| 1 | Exhibition | No GC, no extra turns, no MLD, no combos. Expect 9+ turns. |
| 2 | Core | No GC, no MLD, no chaining extra turns, no combos. Expect 8+ turns. |
| 3 | Upgraded | Up to 3 GC allowed. No MLD, no extra-turn chains, no early combos. Expect 6+ turns. |
| 4 | Optimized | No restrictions beyond ban list. Lethal and consistent. Expect 4+ turns. |
| 5 | cEDH | Meticulously built for the cEDH metagame. Wins any turn. |

**Detection sets/patterns:**
- `FAST_MANA_CARDS` — Mana Crypt, Mana Vault, Jeweled Lotus, Chrome Mox, etc.
- `EXTRA_TURN_PATTERN` / `EXTRA_COMBAT_PATTERN` — regex on oracle text
- `MLD_CARDS` — Armageddon, Obliterate, etc.
- `STAX_PATTERN` — regex for taxing effects
- `COMBO_PAIRS` — completed two-card combo pairs used for bracket inference
- `EARLY_COMBO_PAIRS` — a subset of `COMBO_PAIRS` treated as early-game / Bracket 4+ pressure
- `CEDH_COMMANDERS` — ~13 known cEDH commanders by name

**Assignment logic (waterfall):**
1. Bracket 5 if: cEDH commander OR (3+ fast mana AND early/high combo pressure)
2. Bracket 4 if: 4+ GC, or (2+ fast mana AND 2+ GC), or early/multiple completed combos
3. Bracket 3 if: 1+ GC, slower completed combo, 1+ fast mana, extra turns, or MLD
4. Bracket 2 if: exactly 1 extra turn OR stax (no GC)
5. Bracket 1 otherwise

**Combo nuance:** A lone combo-adjacent card no longer bumps the deck by itself. The evaluator only counts completed two-card pairs. Early-game two-card combos push toward Brackets 4–5; slower completed pairs can remain in Bracket 3.

**Stax/MLD bumps:** Force bracket ≥ 3 if MLD present or 3+ stax effects, even if other criteria place lower.

---

### `app/agents/plan_analyzer.py`

The largest agent. Evaluates the deck against the **RoughDeckPlan framework**.

**Framework targets (from `RoughDeckPlan.csv`):**

| Category | Target | Notes |
|---|---|---|
| Lands | 38 | Can lower with consistent ramp |
| Card Advantage | 12 | Never go below this |
| Ramp | 12 | 10 minimum |
| Removal | 12 | Targeted: 1 card removes 1 card |
| Mass Disruption | 6 | Min 2 boardwipes |
| Plan Cards | 30 | Enablers + payoffs + enhancers |

**`assign_roles(entry)` — multi-role tagger.** Returns `list[str]` from the 6 categories. One card can appear in multiple categories (overlap). Overlap detection: cards in 3+ categories are flagged.

**`commander_focus_advice(roles, color_identity)` — returns structured dict:**
```python
{"text": "...", "suggested_cards": [{"name": "...", "url": "https://scryfall.com/search?q=!..."}]}
```
Card suggestions are filtered to only cards legal in the commander's color identity using the `ci` field in `ROLE_SUGGESTIONS`. Colorless cards (`ci: []`) always pass.

**`COMMANDER_ROLES`** — expanded EDHREC-like taxonomy for commander text matching. It covers broad archetypes such as Tokens, +1/+1 Counters, Artifacts, Combo, Lifegain, Aggro, Spellslinger, Aristocrats, Reanimator, Lands Matter, Treasure, Equipment, Control, Burn, Enchantress, Ramp, Mill, Voltron, cEDH, Blink, Discard, Graveyard, Landfall, Flying, Infect, Card Draw, Stax, Storm, Group Hug, Vehicles, Self-Mill, Cascade, Energy, Ninjutsu, Lifedrain, ETB, Proliferate, Food, Mutate, Politics, Activated Abilities, Flashback, Madness, Scry, Shrines, and related niche themes. `detect_commander_roles()` returns the first three matches.

**`ROLE_SUGGESTIONS`** — ~100 curated cards mapped to commander roles (Token Engine, Enchantress, Spellslinger, etc.), each with a `ci` (color identity) list for filtering. `ROLE_SUGGESTION_ALIASES` maps newer/broader labels such as Tokens, Artifacts, Lifegain, Lands Matter, +1/+1 Counters, and Card Draw back to the closest curated suggestion pack.

`analyze_plan()` also accepts `commander_roles_override`. When provided, those user target roles replace detected roles for focus advice, Plan subcategorization, sequencing, and Advisor prompt context. The response keeps `detected_commander_roles` and `commander_roles_source` so the UI can show what was detected versus user-targeted.

**`analyze_plan(entries, color_identity=None, commander_roles_override=None)` — main entry point. Returns:**
```python
{
  "commander_roles": [...],
  "detected_commander_roles": [...],
  "commander_roles_source": "detected|user",
  "commander_focus_advice": {"text": ..., "suggested_cards": [...]},
  "coverage": {"categories": {cat: {actual, target, delta, pct, status, overlap_count}}},
  "card_roles": [{name, roles, is_overlap, plan_subcategory, ...}],
  "curve_evaluation": {"comparison": {cmc: {actual, target}}, "notes": [...]},
  "path_to_victory": {confidence, summary, commander_earliest_turn, payoff_count, low_cmc_payoffs},
  "playtest_simulation": {opening_hand, by_turn_5, by_turn_7, assessments, category_counts},
  "mulligan_guide": {ideal_hand_profile, mulligan_triggers, engine_pieces, early_ramp_pieces},
  "sequencing_guide": [{turn, priority, notes}],
}
```

---

### `app/agents/ai_advisor.py`

Optional model-powered deck review. Supports Anthropic, OpenAI, and local Ollama providers.

**Default models:** Anthropic `claude-sonnet-4-6`; OpenAI `gpt-4o-mini`; Ollama `llama3.1`.

The module loads project-root `.env` itself before provider checks. This is intentional so API keys and Ollama settings are discovered even when the app is started through `uvicorn` or an IDE instead of `python run.py`.

**`generate_review(analysis_data, intended_bracket, provider, model)` — returns:**
```python
{"summary": str, "suggestions": [str], "full_response": str, "available": bool, "provider": str, "model": str}
```
Falls back to `_fallback_summary()` / `_fallback_suggestions()` if no provider key is available.

`analysis_data` may also contain a structured `budget` object (`tier`, `label`, `max_card_price`). When present, the prompt tells the model to avoid expensive single-card recommendations above that cap.

Provider behavior:
- `provider="auto"` prefers Anthropic when `ANTHROPIC_API_KEY` is set, then OpenAI when `OPENAI_API_KEY` is set, then Ollama.
- OpenAI uses the Responses API (`/v1/responses`) through `urllib`.
- Ollama posts to `{OLLAMA_BASE_URL}/api/chat` with `stream: false`; default URL is `http://localhost:11434`.

**Prompt structure:** Sends the full analysis dict as a structured prompt covering commander identity, framework coverage, focus advice, synergy clusters, curve notes, playtest simulation, mulligan guide, and the full card list. Instructs the selected model to produce:
1. 2–3 sentence deck summary
2. 5–8 `Cut: [X] → Add: [Y]` suggestions
3. Coverage gap notes
4. Closing power-level assessment

**`_build_prompt`** handles both the old (string) and new (dict) format of `commander_focus_advice`.

**`_parse_response`** splits model text into `(summary, suggestions)` by detecting lines starting with "Cut", "→", or numbered list items.

**Suggestion sanitization:** Parsed suggestions are post-validated against the local Scryfall index before they are returned. Suggested adds must:
- exist in the local bulk data
- be Commander-legal
- fit the commander's color identity
- not already be in the deck
- fit the selected budget cap when one is set

Invalid suggestions are dropped, and the frontend prefers the sanitized `ai_suggestions` list over the raw `ai_full_response` suggestion block when both exist.

---

### `app/agents/edhrec.py`

Fetches EDHREC recommendations for the commander.

**Endpoint:** `https://json.edhrec.com/pages/commanders/{slug}.json`

**`slugify(name)`** — lowercases, strips non-alphanumeric, replaces spaces with dashes.

**JSON navigation path:** `data → container → json_dict → cardlists[]`. Sections are matched by `tag.lower().replace(" ", "")` — must be `"highsynergycards"` or `"topcards"`.

**Per-card fields extracted:**
- `name`, `synergy` (decimal → %, e.g. 0.7 → 70%), `num_decks`, `potential_decks`
- `inclusion_pct = num_decks / potential_decks * 100`
- `tcgplayer_price` when EDHREC exposes it
- `source` — `"High Synergy"` or `"Top"`

Returns up to 24 cards per section. Cards are enriched in `main.py` with `plan_roles`, `scryfall_uri`, and a price fallback from cached Scryfall `prices.usd` / `prices.usd_foil` when EDHREC omits TCGplayer data.

---

### `app/agents/moxfield.py`

Imports a deck from Moxfield.

**Endpoint:** `https://api.moxfield.com/v2/decks/all/{deck_id}`

**`to_decklist_text(data)`** — converts Moxfield JSON to plain-text format:
- Commanders: emits both `Commander: Name` tag and `1 Name` quantity line (required so deck_parser creates a `CardEntry` and the EDHREC fetch finds `commander_name`)
- Mainboard entries: `{qty} {name}`
- Companions treated as mainboard

Returns `(text, primary_commander_name)`.

---

### `app/main.py`

FastAPI application. Owns the review pipeline and all HTTP endpoints.

**Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serves `frontend/index.html` |
| `GET` | `/static/*` | Serves `frontend/` directory |
| `GET` | `/health` | Index ready status + bulk data age |
| `GET` | `/api/index/status` | Cache file size and mtime |
| `POST` | `/api/index/build` | Build/rebuild card index (blocks ~30 s) |
| `GET` | `/api/bulk-data/status` | Local file age; `?check_remote=true` queries Scryfall |
| `POST` | `/api/bulk-data/update` | Starts background download + rebuild |
| `GET` | `/api/bulk-data/progress` | Polls `cache/download_progress.json` |
| `GET` | `/api/card/{name}` | Single card lookup |
| `GET` | `/api/suggest` | Autocomplete (`?q=Rhyst`) |
| `GET` | `/api/moxfield` | Import Moxfield deck (`?url=...`) |
| `POST` | `/api/review` | Full review from uploaded `.txt` file |
| `POST` | `/api/review/text` | Full review from form-posted text |

**`_run_review(decklist_text, commander_hint, intended_bracket, skip_ai, ai_provider, ai_model, commander_roles_override, budget_tier)`** — the core pipeline:
1. `parse_decklist_text()` → `list[CardEntry]`
2. `validate(entries)` → `ValidationResult`
3. `synergy.analyze(entries)` → synergy dict
4. `bracket.evaluate(entries)` → `BracketAssessment`
5. `plan_analyzer.analyze_plan(entries, color_identity=cmd_color_identity, commander_roles_override=...)` → plan dict
6. `edhrec.fetch_commander_synergy(commander_name)` → EDHREC dict (best-effort, non-fatal)
7. Enrich each EDHREC card with `plan_roles`, `scryfall_uri`, and `tcgplayer_price` fallback via `SimpleNamespace` proxy + cached lookup data
8. `ai_advisor.generate_review(analysis, intended_bracket, provider=ai_provider, model=ai_model)` (skipped if `skip_ai=True`)
9. Stores `budget`, `ai_available`, `ai_provider`, and `ai_model` in the response
10. Returns merged `analysis` dict as JSON

---

## Frontend Files

### `frontend/index.html`

Single-page app shell. All content is rendered into `<section>` elements by `app.js`.

**Key element IDs:**

| ID | Purpose |
|---|---|
| `upload-panel` | File drop zone, Moxfield URL input, paste area, options |
| `loading-panel` | Spinner shown during review |
| `results-panel` | Container for all result tabs |
| `commander-header` | Commander/partner names, color pips, bracket label, and enriched card details |
| `tab-overview` | Stat cards, mana curve, type donut, role bars, warnings |
| `tab-plan` | Framework coverage, CMC curve, playtest table, mulligan, sequencing, card role table with filtered-view clipboard export |
| `tab-validation` | Error/warning lists |
| `tab-synergy` | Synergy cluster cards, missing staples |
| `tab-bracket` | 5-box bracket display + GC cards |
| `tab-ai` | Advisor summary, sanitized suggestions, budget-aware EDHREC table |
| `tab-cards` | Filterable/sortable full card list |

**Tables with `data-sort` headers** (sort state managed by `initTableSort()`):
- `#card-table` — qty, name, type_line, cmc, rarity, game_changer
- `#card-role-table` — name, cmc, roles, plan_subcategory, is_overlap
- `#edhrec-missing-table` / `#edhrec-included-table` — name, synergy, inclusion_pct, num_decks, tcgplayer_price, plan_roles, source

---

### `frontend/app.js`

All frontend logic. No build step — plain ES2020.

**Module-level state:**
```javascript
let currentAnalysis = null;   // last API response
let allCards = [];            // for card list filtering
let _allCardRoles = [];       // for plan tab card role table
let _cmcMapCache = {};        // {name → cmc} built from cards array
let _cardRoleCurrentView = [];// current filtered/sorted Plan role rows
let _cardRoleCardMap = new Map(); // card role name → enriched card entry
let _edhrecMissing = [];      // EDHREC cards not in deck
let _edhrecIncluded = [];     // EDHREC cards already in deck
```

**Sort state objects** (mutated in place by `initTableSort()`):
```javascript
const _cardSort   = { col: 'name',    dir: 1  };   // card list tab
const _roleSort   = { col: 'name',    dir: 1  };   // plan tab role table
const _edhrecSort = { col: 'synergy', dir: -1 };   // Advisor tab EDHREC tables
```

**Sort utilities:**
- `sortArr(arr, col, dir)` — creates sorted copy; handles numeric columns (`quantity`, `cmc`, `synergy`, `inclusion_pct`, `num_decks`, `tcgplayer_price`), rarity order (common→mythic), and arrays (joined to string)
- `initTableSort(tableEl, sortState, onSort)` — attaches click listeners to all `th[data-sort]`, updates indicators, calls `onSort()` on click
- `updateSortIndicators(tableEl, col, dir)` — toggles `.sort-asc` / `.sort-desc` CSS classes

**Render functions** (called from `renderResults(data)`):

| Function | Renders |
|---|---|
| `renderCommanderHeader(data)` | Name/color pips/bracket label plus enriched commander and partner detail cards |
| `renderOverview(data)` | Stat cards, mana curve bars, type donut (canvas), role bars |
| `renderPlan(data)` | All Plan tab sections including card role table |
| `renderCardRoleTable(cardRoles, cards)` | Populates `_allCardRoles`, `_cmcMapCache`, and `_cardRoleCardMap`, calls `filterCardRoleTable()` |
| `filterCardRoleTable(cmcMap)` | Applies text/category filter + sort, stores `_cardRoleCurrentView`, renders tbody |
| `copyCardRoleView()` | Copies the current Card Role Map view to the clipboard as import-compatible decklist text |
| `renderValidation(data)` | Error/warning lists |
| `renderSynergy(data)` | Cluster cards + missing staples |
| `renderBracket(data)` | 5-box bracket display (1=Exhibition…5=cEDH) + reasoning + GC cards |
| `renderAI(data)` | Advisor summary + suggestions + EDHREC section; calls `initEdhrecSort()` after setting innerHTML |
| `buildEdhrecSection(edhrec, deckNames)` | Returns HTML string; populates `_edhrecMissing` / `_edhrecIncluded` |
| `renderEdhrecRows(cards, inDeck)` | Returns `<tr>` HTML for EDHREC table rows with role tags |
| `initEdhrecSort()` | Attaches sort to both EDHREC tables; re-renders tbodies on sort |
| `renderCardList(cards)` | Sets `allCards`, calls `filterCards()` |
| `filterCards()` | Applies text/type filter + `_cardSort`, renders card list tbody |

**Card link helpers:**
- `renderCardLink(name, options)` renders a Scryfall link using the card's `scryfall_uri` when available and an exact Scryfall search fallback otherwise.
- `linkKnownCardNames(text, extraNames)` links known card names inside freeform text, including Bracket reasoning.
- `linkSuggestionText(text)` handles Advisor suggestion shapes such as `Cut: X -> Add: Y`, arrows, and comma-separated add/consider lists.

Clickable card-name coverage includes commander detail headers, Synergy cluster tags, missing staples, Bracket game changers/reasoning, Advisor suggestions, EDHREC rows, Plan role/map sections, low-CMC payoffs, mulligan pieces, and the Card List.

`renderPlan(data)` also links card names inside the playtest notes, mulligan keep/mulligan rules, and sequencing guide text. Commander mana symbols in the header are colorized, including hybrid-style gradients for mixed symbols.

**Static table sort initialization** (at page load):
```javascript
initTableSort(document.getElementById('card-table'), _cardSort, filterCards);
initTableSort(document.getElementById('card-role-table'), _roleSort, () => filterCardRoleTable(_cmcMapCache));
```

**Import flows:**
- File upload → `handleFile()` → reads into `paste-input`
- Paste → submitted directly
- Moxfield URL → `GET /api/moxfield?url=...` → fills `paste-input` + `commander-input`
- Submit → `submitDeck()` → `POST /api/review` → `renderResults()`

---

### `frontend/style.css`

Dark-theme CSS (~620 lines). Notable class groups:

| Class / selector | Purpose |
|---|---|
| `th[data-sort]`, `.sort-asc::after`, `.sort-desc::after` | Sort indicator arrows (↑/↓) on table headers |
| `a.focus-card-link` | Purple pill links for suggested cards in Commander Role panel |
| `a.card-name-link`, `a.inline-card-link` | Scryfall links for card names in tables, tags, suggestions, and freeform text |
| `.commander-detail-*`, `.commander-oracle`, `.mana-symbol` | Enriched commander/partner detail card layout |
| `.coverage-card`, `.coverage-bar-*` | Framework coverage bars in Plan tab |
| `.bracket-box`, `.bracket-box.active` | 5 bracket boxes in Bracket tab |
| `.edhrec-table`, `.edhrec-source-hs/top`, `.edhrec-budget-note` | EDHREC recommendation tables; numeric metric cells are centered and budget filtering is surfaced in the UI |
| `.role-tag`, `.role-Lands`, `.role-Card-Advantage`, etc. | Colored role chips in Plan + EDHREC tables |
| `.cluster-card`, `.strength-badge` | Synergy cluster cards |
| `.cluster-tag`, `.tag` | Clickable pill/tag styling used by Synergy, Bracket, Advisor, and Plan details |
| `.download-overlay`, `.download-bar-*` | Bulk data download progress overlay |
| `.mana.w/u/b/r/g` | Header mana symbol decorations |
| `.pip-W/U/B/R/G` | Inline color identity pips |

---

## Key Cross-Cutting Concerns

### Commander Color Identity Filtering
The commander's color identity is computed in `main.py`:
```python
cmd_color_identity = sorted({c for e in entries if e.is_commander for c in e.color_identity})
```
Passed to `plan_analyzer.analyze_plan()` so `commander_focus_advice()` can filter suggested cards. Colorless cards (`ci: []`) always pass because `all()` on an empty iterable is `True`.

### EDHREC Role Enrichment
EDHREC cards don't go through `deck_parser`, so they lack the `CardEntry` properties that `assign_roles()` needs. `main.py` creates a `SimpleNamespace` proxy per card:
```python
proxy = SimpleNamespace(
    oracle_text=txt, type_line=tl, cmc=..., power=...,
    is_land=..., is_creature=..., is_planeswalker=...,
    is_enchantment=..., is_commander=False, quantity=1,
)
card["plan_roles"] = plan_analyzer.assign_roles(proxy)
```

If EDHREC does not expose a usable TCGplayer price for a card, `main.py` falls back to the local Scryfall cache using `prices.usd` or `prices.usd_foil`.

### Card Index Invalidation
`_INDEX` (module-level singleton in `card_lookup.py`) is set to `None` after a bulk data download. The next call to `lookup()` or `suggest_names()` triggers a rebuild automatically.

### Download Progress Polling
`POST /api/bulk-data/update` starts a background thread. The thread writes JSON to `cache/download_progress.json` at each stage. The frontend polls `GET /api/bulk-data/progress` every 1.5 s and updates the overlay bar.

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `AI_PROVIDER` | No | `auto`, `anthropic`, `openai`, or `ollama`; defaults to `auto` |
| `ANTHROPIC_API_KEY` | No | Enables Anthropic advisor calls |
| `ANTHROPIC_MODEL` | No | Anthropic model override |
| `OPENAI_API_KEY` | No | Enables OpenAI advisor calls |
| `OPENAI_MODEL` | No | OpenAI model override |
| `OLLAMA_BASE_URL` | No | Ollama URL; defaults to `http://localhost:11434` |
| `OLLAMA_MODEL` | No | Ollama model override |

---

## Adding a New Feature — Where to Touch

| Feature type | Files to modify |
|---|---|
| New bracket rule | `bracket.py` (add to sets/patterns + adjust waterfall logic) |
| New plan framework category | `plan_analyzer.py` (add to `TARGETS`, `assign_roles()`, `ROLE_SUGGESTIONS`) |
| New synergy cluster | `synergy.py` (`SYNERGY_RULES` list) |
| New validator check | `validator.py` (`validate()` function) |
| New API endpoint | `app/main.py` |
| New UI tab | `index.html` (add `tab-btn` + `tab-content`), `app.js` (add `render*` function, call from `renderResults()`), `style.css` |
| New sortable table | `index.html` (add `data-sort` to `<th>`), `app.js` (add sort state object, call `initTableSort()`, wire filter function to use `sortArr()`) |
| Change card fields from Scryfall | `card_lookup.py` (`CARD_FIELDS`), `card.py` (`CardEntry`), `deck_parser.py` (enrich block) |
