# MTG Commander Deck Review

An AI-powered Commander deck analysis tool. Submit a `.txt` decklist and receive a full report covering rules validation, synergy detection, bracket assessment, and card suggestions — all backed by a local Scryfall card database.

For a compact implementation-oriented overview, start with [docs/project-reference.md](docs/project-reference.md). Use [architecture.md](architecture.md) when you need deeper file-by-file detail.

> AI analysis current hallucinates a lot, not recommended to use that functionality at this time

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Build the Scryfall card index

This only needs to run once. It processes the local bulk data file and writes a compact lookup cache (~30 seconds).

```bash
python build_index.py
```

### 3. Start the server

```bash
python run.py
```

Open **http://localhost:8000** in your browser.

### 4. Configure an AI provider (optional)

Copy `.env.example` to `.env` and fill in at least one provider:

```bash
cp .env.example .env
```

```env
AI_PROVIDER=auto          # auto | anthropic | openai | ollama
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

The server loads `.env` automatically on startup. Without a configured provider the Advisor tab falls back to rule-based suggestions.

---

## Running fully local with Ollama

Ollama lets you run the Advisor with no API key or internet requirement after the initial model download.

### Install Ollama

| Platform | Link |
|---|---|
| macOS / Linux / Windows | https://ollama.com/download |
| Docker | `docker run -d -p 11434:11434 ollama/ollama` |

### Pull a model

Any instruction-following model works. Recommended options:

| Model | Command | Notes |
|---|---|---|
| Llama 3.1 8B | `ollama pull llama3.1:8b` | Good balance of speed and quality (~5 GB) |
| Llama 3.1 70B | `ollama pull llama3.1:70b` | Best quality, needs ~40 GB RAM |
| Mistral 7B | `ollama pull mistral` | Fast, low memory (~4 GB) |
| Gemma 3 12B | `ollama pull gemma3:12b` | Strong reasoning (~8 GB) |
| Phi-4 Mini | `ollama pull phi4-mini` | Very fast on CPU (~2.5 GB) |

Browse all available models at https://ollama.com/library.

### Configure the app

Set these in your `.env`:

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

Then start the server normally:

```bash
python run.py
```

The Advisor tab will show which provider handled the review (`ollama / llama3.1:8b`). Larger models produce noticeably better cut/add recommendations; 7–8B models are usable but may miss subtle synergy nuances.

**WSL note:** if Ollama is running on the Windows host and the app is running inside WSL, replace `localhost` with the Windows host IP (usually `172.x.x.1`) or use `host.docker.internal` if running in Docker. If both are in the same WSL instance, `http://localhost:11434` works as-is.

---

## Decklist Format

Plain text, one card per line:

```
1 Sol Ring
1 Command Tower
4 Forest
```

Quantity prefixes `1`, `1x`, and `1X` are all accepted. Section headers and comments are ignored:

```
// Ramp
1 Cultivate
1 Kodama's Reach

# Interaction
1 Swords to Plowshares
```

To explicitly tag your commander (useful if it isn't the first legendary creature in the list):

```
Commander: Atraxa, Praetors' Voice
```

Split cards use the full double-sided name or either half:

```
1 Fire // Ice
1 Fire          ← also works
```

---

## Web Interface

### Submit panel

| Field | Purpose |
|---|---|
| File upload / paste | Drag-and-drop a `.txt` file or paste directly into the text area |
| Commander override | Force a specific card to be treated as the commander |
| Intended Bracket | Your self-assessed power level (1–5); mismatches are flagged |
| Budget Target | Applies a per-card recommendation cap so Advisor / EDHREC suggestions fit the deck's price band |
| Advisor Provider / Model | Choose Auto, Anthropic, OpenAI, or Ollama and optionally override the model for that review |
| Skip AI review | Skips the model API call for a faster response |

### Results tabs

| Tab | Contents |
|---|---|
| **Overview** | Card count, average mana value, color identity, mana curve chart, type breakdown donut, role bar chart, deck warnings |
| **Plan** | RoughDeckPlan framework analysis — editable commander role/bracket targets, coverage gauges, CMC curve vs target, path to victory, 5–7 turn playtest simulation, mulligan guide, sequencing guide, full card role map |
| **Validation** | Pass/fail status, full list of errors and warnings |
| **Synergy** | Detected synergy clusters with strength ratings, missing staple suggestions |
| **Bracket** | Visual bracket indicator (1–5), reasoning notes, list of game-changer cards |
| **Advisor** | Model-generated or rule-based deck summary, validated cut/add recommendations informed by plan coverage gaps, and EDHREC recommendations with role and price data when available |
| **Card List** | Full enriched card table — filterable by name and type, sortable, links to Scryfall |

The commander header shows enriched commander and partner card details when available: linked name, colorized mana cost, type line, mana value, stats/defense, rarity, keywords, and oracle text. Named cards throughout the results are intended to be clickable Scryfall links without changing the surrounding layout.

The Plan tab includes target controls for iteration. Users can add/remove commander role tags and change the planned bracket, then re-run the analysis so focus advice and Advisor suggestions aim at that target.

The Plan tab also links card names in the 5–7 turn simulation notes, sequencing guide, mulligan guide, and role-map sections. The Advisor tab's EDHREC tables include `Synergy`, `Inclusion`, `Decks`, `Price`, role chips, and budget-aware filtering. Price prefers EDHREC's TCGplayer value when present and otherwise falls back to the local Scryfall index.

---

## API Endpoints

All endpoints are served at `http://localhost:8000`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Server status, index readiness, and bulk data age |
| `GET` | `/api/index/status` | Index file size and build time |
| `POST` | `/api/index/build?force=true` | (Re)build the card index |
| `GET` | `/api/bulk-data/status` | Local bulk file age + optional remote metadata |
| `GET` | `/api/bulk-data/status?check_remote=true` | Same + live query to `api.scryfall.com/bulk-data` |
| `POST` | `/api/bulk-data/update` | Download latest file from Scryfall + rebuild index (background) |
| `GET` | `/api/bulk-data/progress` | Poll download/rebuild progress |
| `GET` | `/api/card/{name}` | Look up a single card by name |
| `GET` | `/api/suggest?q={prefix}` | Autocomplete card names |
| `GET` | `/api/moxfield?url={deck_url}` | Import a Moxfield deck into plain-text decklist format |
| `POST` | `/api/review` | Full review from uploaded `.txt` file (multipart form) |
| `POST` | `/api/review/text` | Full review from raw text body (form field `decklist`) |

### `/api/review` form fields

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | Yes | `.txt` decklist |
| `commander` | string | No | Override commander detection |
| `intended_bracket` | int (1–5) | No | Player's declared bracket |
| `budget_tier` | string | No | `budget`, `moderate`, `upgraded`, or `premium` |
| `commander_roles` | JSON array or comma string | No | User target commander role tags for Plan/Advisor analysis |
| `ai_provider` | string | No | `auto`, `anthropic`, `openai`, or `ollama` |
| `ai_model` | string | No | Per-review model override |
| `skip_ai` | bool | No | Skip model API call |

### Response shape

```json
{
  "commander": "Atraxa, Praetors' Voice",
  "partner": null,
  "color_identity": ["B", "G", "U", "W"],
  "card_count": 100,
  "avg_cmc": 2.8,
  "cards": [ ...enriched card objects... ],
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": []
  },
  "bracket": {
    "bracket": 3,
    "label": "Optimized (Bracket 3)",
    "game_changer_count": 5,
    "game_changer_cards": ["Rhystic Study", ...],
    "fast_mana_count": 1,
    "combo_potential": "low",
    "reasoning": ["5 game-changer cards detected.", ...]
  },
  "synergy_clusters": [ ...cluster objects... ],
  "mana_curve": {"0":2,"1":8,"2":14,...},
  "type_breakdown": {"Creatures":22,"Instants":8,...},
  "role_breakdown": {"ramp":10,"draw":9,...},
  "missing_staples": ["Demonic Tutor", ...],
  "synergy_warnings": ["Low ramp count (6)..."],
  "intended_bracket": 3,
  "budget": {"tier":"moderate","label":"Moderate","max_card_price":15.0},
  "target_commander_roles": ["Tokens", "Voltron"],
  "ai_available": true,
  "ai_provider": "openai",
  "ai_model": "gpt-4o-mini",
  "plan": {
    "commander_roles": ["Proliferate Engine"],
    "commander_focus_advice": "...",
    "coverage": {
      "categories": {
        "Lands":           {"actual":38,"target":38,"pct":100,"status":"ok","delta":0},
        "Card Advantage":  {"actual":10,"target":12,"pct":83,"status":"close","delta":-2},
        "Ramp":            {"actual":12,"target":12,"pct":100,"status":"ok","delta":0},
        "Removal":         {"actual":11,"target":12,"pct":92,"status":"close","delta":-1},
        "Mass Disruption": {"actual":5,"target":6,"pct":83,"status":"close","delta":-1},
        "Plan Cards":      {"actual":42,"target":30,"pct":140,"status":"ok","delta":12}
      },
      "overlap_cards": ["Cultivate", ...],
      "overlap_count": 15
    },
    "curve_evaluation": {
      "comparison": {"0":{"actual":0,"target":0,"diff":0},...},
      "notes": ["CMC 4 is light (5 actual vs 10 target)..."],
      "total_nonland": 62
    },
    "path_to_victory": {
      "confidence": "High",
      "summary": "...",
      "commander_earliest_turn": 2,
      "low_cmc_payoffs": ["Doubling Season", ...],
      "ramp_count": 12,
      "payoff_count": 7
    },
    "playtest_simulation": {
      "opening_hand": {"Lands":2.7,"Ramp":0.9,"Card Advantage":0.7,...},
      "by_turn_5":    {"Lands":3.2,"Ramp":1.1,"Card Advantage":0.8,...},
      "by_turn_7":    {"Lands":3.7,"Ramp":1.3,"Card Advantage":0.9,...},
      "assessments":  ["Land drops look solid...", ...],
      "category_counts": {"Lands":38,"Ramp":12,...}
    },
    "mulligan_guide": {
      "engine_pieces": ["Rhystic Study", ...],
      "early_ramp_pieces": ["Sol Ring", ...],
      "ideal_hand_profile": ["3–4 lands...", "1 early ramp piece...", ...],
      "mulligan_triggers": ["Fewer than 2 lands", ...]
    },
    "sequencing_guide": [
      {"turn":1,"priority":"Land drop","notes":"..."},
      ...
    ],
    "card_roles": [
      {"name":"Sol Ring","roles":["Ramp"],"plan_subcategory":null,"is_overlap":false},
      {"name":"Rhystic Study","roles":["Card Advantage","Plan Cards"],"plan_subcategory":"Enabler","is_overlap":true},
      ...
    ]
  },
  "ai_summary": "...",
  "ai_suggestions": ["Cut: X → Add: Y — reason", ...]
}
```

Each card object in `cards` contains:

```json
{
  "quantity": 1,
  "raw_name": "Sol Ring",
  "name": "Sol Ring",
  "cmc": 1.0,
  "color_identity": [],
  "colors": [],
  "defense": null,
  "keywords": [],
  "mana_cost": "{1}",
  "oracle_text": "...",
  "power": null,
  "toughness": null,
  "type_line": "Artifact",
  "legalities": {"commander": "legal", ...},
  "game_changer": false,
  "rarity": "uncommon",
  "scryfall_uri": "https://scryfall.com/...",
  "is_commander": false,
  "found": true,
  "error": null
}
```

---

## Architecture

```
DeckReview/
├── run.py                  Server entry point
├── build_index.py          Standalone index builder
├── build_otag_index.py     Optional otag classification cache builder
├── requirements.txt
├── .env                    Provider API keys and model defaults (not committed)
├── .env.example            Template — copy to .env and fill in
│
├── app/
│   ├── main.py             FastAPI app, route definitions, pipeline orchestration
│   ├── models/
│   │   └── card.py         Dataclasses: CardEntry, ValidationResult,
│   │                       SynergyCluster, BracketAssessment, DeckAnalysis
│   └── agents/
│       ├── card_lookup.py  Scryfall index builder and card lookup
│       ├── deck_parser.py  Decklist text parser
│       ├── validator.py    Commander rules enforcement
│       ├── synergy.py      Synergy cluster detection and role analysis
│       ├── bracket.py      Bracket 1–5 power level assessment
│       ├── plan_analyzer.py RoughDeckPlan framework evaluation
│       ├── edhrec.py       EDHREC commander recommendations
│       ├── moxfield.py     Moxfield URL → decklist conversion
│       └── ai_advisor.py   Anthropic/OpenAI/Ollama integration and fallback suggestions
│
├── frontend/
│   ├── index.html          Single-page web UI
│   ├── style.css           Dark theme, responsive layout
│   └── app.js              Fetch calls, rendering, tab navigation, charts
│
├── cache/                  Generated files — not committed, rebuilt locally
│   ├── card_index.json     Name → card lookup (build_index.py)
│   └── otag_index.json     Card → otag classification (build_otag_index.py, optional)
│
├── decks/                  Drop your .txt decklists here
├── results/                JSON review outputs saved here automatically
└── Scryfall src/           Bulk data — not committed, downloaded via UI or Scryfall API
    └── default-cards-*.json
```

---

## Agent Logic

### `card_lookup.py` — Scryfall Index

The bulk data file contains ~114,000 card entries across all printings. The index builder:

1. Iterates all English, non-digital cards
2. Groups by `oracle_id` (canonical card identity across printings)
3. **Prefers Commander-legal printings** — if a card has a legal printing and a non-legal one (e.g. a digital-only reprinting), the legal version wins
4. Strips accents and apostrophes from names so `"Atraxa, Praetors' Voice"` and `"Atraxa, Praetors' Voice"` both resolve to the same key
5. Indexes split card half-names separately so `"Fire"` resolves to `"Fire // Ice"`
6. Writes the result to `cache/card_index.json` (~37,700 entries, loads in under a second)

Rebuild the index with `python build_index.py --force` if you update the bulk data file.

---

### `deck_parser.py` — Deck Parser

Reads a `.txt` file line by line:

- Skips blank lines, `//` comments, `#` comments, and `SB:` sideboard markers
- Parses `[qty][x] [card name]` with a regex
- Detects `Commander: [name]` tags for explicit commander declaration
- Looks up every card in the index and copies the relevant fields onto a `CardEntry` object
- Auto-detects the commander as the first Legendary Creature if no explicit tag is present
- Handles Partner pairs — if two cards are flagged as commander, both are retained

---

### `validator.py` — Rules Validator

Enforces the official Commander rules (https://mtgcommander.net/index.php/rules/):

| Check | Rule |
|---|---|
| Commander presence | At least one card must be designated as the commander |
| Commander validity | Must be a Legendary Creature or have "can be your commander" in oracle text |
| Partner validity | Two-commander pairs must share Partner, Partner With (named), or Friends Forever |
| Card count | Exactly 100 cards total (commanders included) |
| Singleton | Max 1 copy per card; Basic Lands and cards with "a deck can have any number" are exempt |
| Color identity | Every card's `color_identity` must be a subset of the combined commander color identity |
| Legality | Uses Scryfall's `legalities.commander` field; also cross-references a hardcoded ban list for recent bans |

Color identity is determined by mana symbols in mana cost, rules text, and color indicators — exactly as Scryfall computes it in the `color_identity` field.

---

### `synergy.py` — Synergy Analyzer

**Role classification** categorizes each card into one of: `ramp`, `draw`, `removal`, `boardwipes`, `tutors`, `threats`, `synergy`, `lands`. This is done by matching oracle text against compiled regex patterns.

**Mana curve** buckets non-land cards by CMC (0–6, then 7+) and counts them.

**Synergy clusters** — 19 rule-based detectors, each with a `check` function over a `CardEntry`. A cluster is reported only when 3 or more cards match. Clusters are rated:
- **High** — 8+ cards
- **Medium** — 5–7 cards
- **Low** — 3–4 cards

Detected themes include: Flying Matters, Deathtouch Package, Lifelink, Token Generation, Sacrifice Engine, Graveyard Recursion, Counter Manipulation, Enchantress Package, Artifact Synergy, Spellslinger, Landfall, Tribal Synergy, Copy/Clone, Blink/Flicker, Extra Turns, Storm/Combo, Commander Damage, Mana Doubling, Card Draw Engine, Stax/Taxing.

**Missing staples** are checked per color: a short list of high-impact cards per color symbol in the commander's identity are compared against the decklist, and any absent ones are flagged.

**Warnings** are generated when the deck falls below recommended thresholds: fewer than 8 ramp pieces, fewer than 8 draw effects, fewer than 6 interactive pieces, or fewer than 33 lands.

---

### `bracket.py` — Bracket Evaluator

Maps to the current five-bracket system implemented in [`app/agents/bracket.py`](app/agents/bracket.py):

| Bracket | Label | Criteria |
|---|---|---|
| 1 | Exhibition | No game changers, no fast mana, no combos, no extra turns |
| 2 | Core | Mechanically focused, light disruption only, no game changers |
| 3 | Upgraded | 1–3 game changers, slower completed two-card combo, or fast mana / stronger synergy |
| 4 | Optimized | 4+ game changers, early two-card combo, heavier fast mana, or multiple completed combos |
| 5 | cEDH | Known cEDH commander or cEDH-level fast mana plus early combo pressure |

The `game_changer` field on Scryfall card objects directly corresponds to EDHREC's bracket-defining card list (496 cards as of this build).

Additional signals:
- **Fast mana** — Mana Crypt, Mana Vault, Chrome Mox, Mox Diamond, Jeweled Lotus, etc. Three or more alongside early combo pressure can push to Bracket 5.
- **Combo potential** — based on completed two-card combo pairs, not isolated combo-adjacent cards. Early-game two-card combos push toward Brackets 4–5; slower completed combos can remain in Bracket 3.
- **Mass land destruction** — Armageddon, Ravages of War, etc. force Bracket 3 minimum.
- **Heavy stax** — 3+ taxing effects push toward Bracket 3.
- **Known cEDH commanders** — a list of commonly played cEDH commanders auto-suggests Bracket 5.

If the player's declared bracket differs from the computed bracket, a mismatch note is added to the reasoning.

---

### `ai_advisor.py` — Advisor

Builds a structured prompt containing the commander, color identity, bracket, type/role breakdown, top synergy clusters, missing staples, validation issues, and the full card list. It can call Anthropic via the installed SDK, OpenAI via the Responses API, or a local Ollama server via `/api/chat`.

The response is parsed for:
- A summary paragraph (first non-suggestion lines)
- Suggestion bullets (lines matching `Cut: X → Add: Y` pattern)

Provider selection is controlled by request fields or environment variables:

| Variable | Purpose |
|---|---|
| `AI_PROVIDER` | `auto`, `anthropic`, `openai`, or `ollama`; defaults to `auto` |
| `ANTHROPIC_API_KEY` | Enables Anthropic advisor calls |
| `ANTHROPIC_MODEL` | Optional Anthropic model override |
| `OPENAI_API_KEY` | Enables OpenAI advisor calls |
| `OPENAI_MODEL` | Optional OpenAI model override; defaults to `gpt-4o-mini` |
| `OLLAMA_BASE_URL` | Optional Ollama URL; defaults to `http://localhost:11434` |
| `OLLAMA_MODEL` | Optional Ollama model; defaults to `llama3.1` |

Falls back gracefully if no provider key is set — generates rule-based suggestions from the synergy and role data instead.

Model suggestions are sanitized against the local bulk index before they are returned to the frontend. Suggested adds must exist in the local Scryfall data, be Commander-legal, fit commander color identity, not already be in the deck, and respect the selected budget target if one is set.

The API response includes `ai_available`, `ai_provider`, and `ai_model` so the frontend can show what actually handled the review. OpenAI uses the Responses API, and Ollama uses `/api/chat` with non-streaming responses.

---

### `plan_analyzer.py` — Plan Framework Analyzer

Implements the **RoughDeckPlan.csv** deckbuilding framework. Every analysis in this agent is aware that cards can fill multiple roles simultaneously — the system explicitly tracks and surfaces overlap.

#### Framework Categories & Targets

| Category | Target | Notes |
|---|---|---|
| **Lands** | 38 | Enough to hit land drops through turn 6 with 7 draw effects and mulligans. Can reduce with consistent mana dorks or extra ramp. |
| **Card Advantage** | 12 | Cards that spend 1 card to net 1+n cards. Never go below this — it's what gets you your engine and synergy pieces. |
| **Ramp** | 12 | Mana acceleration. Minimum 10 for an average deck. Ramp that only covers a missed land drop does not count as real ramp. |
| **Removal** | 12 | Targeted disruption: 1 card removes 1 other card. Stops opponents from executing their plan. |
| **Mass Disruption** | 6 | Not just board wipes — at least 2 actual wipes, the rest can be mass bounce, mass tax, mass exile, etc. Variety in what it handles matters. |
| **Plan Cards** | 30 | Cards that execute the deck's goal: enablers (set up the plan), payoffs (reward the plan), and enhancers (multiply it). |

The raw sum is 110. With 8–10 cards filling two categories simultaneously (overlap), the deck nets to 100 cards. Overlap is intentional and desirable — it maximises slot efficiency.

#### Multi-Role Tagging

Every card is checked against all six categories and can receive multiple labels. A card like Rhystic Study gets both **Card Advantage** and **Plan Cards** (as an Enabler). Cultivate gets both **Ramp** and (depending on context) **Plan Cards**. The card role table in the Plan tab shows every card's full category membership, overlap status, and Plan sub-type.

#### Commander Role Detection

The commander's oracle text is matched against an expanded EDHREC-style taxonomy covering common archetypes such as Tokens, +1/+1 Counters, Artifacts, Combo, Lifegain, Aggro, Spellslinger, Aristocrats, Reanimator, Lands Matter, Treasure, Equipment, Control, Burn, Enchantress, Ramp, Mill, Voltron, cEDH, Blink, Discard, Graveyard, Landfall, Flying, Infect, Card Draw, Stax, Storm, Group Hug, Vehicles, Self-Mill, Cascade, Energy, Ninjutsu, Lifedrain, ETB, Proliferate, Food, Mutate, Politics, Activated Abilities, Flashback, Madness, Scry, Shrines, and many more.

The detected roles drive the **Focus Advice** — targeted guidance on which of the other five categories to prioritise given what the commander is already doing. Related labels map back to curated suggestion packs where possible, and suggestions are filtered by commander color identity.

#### CMC Curve Evaluation

Actual non-land CMC distribution is compared to the ideal target:

| CMC | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7+ |
|---|---|---|---|---|---|---|---|---|
| Target | 0 | 9 | 18 | 15 | 10 | 5 | 5 | 5 |

Buckets more than 40% below target are flagged as **sticky points** — turns where you are likely to have mana but nothing impactful to cast, slowing your curve and reducing your chances of winning on curve.

#### Path to Victory

Estimates whether the deck can present a meaningful threat by turn 5:

- Counts ramp pieces and calculates how many turns early the commander can land (`ramp_bonus = min(ramp_count // 4, 2)`)
- Identifies low-CMC payoffs (≤ 4 mana) that can apply pressure independently of the commander
- Rates confidence as **High / Medium / Low** based on ramp count and payoff density

#### Playtesting Simulation (5–7 Turns)

Uses expected-value approximation (hypergeometric distribution mean) to simulate seeing cards over the first 5–7 turns:

```
E[category hits in N draws] = (category_count / deck_size) * N
```

Three windows are evaluated: opening hand (7 cards), by turn 5 (12 cards seen), by turn 7 (14 cards seen). The simulation answers:

- Do you hit consistent land drops? (want ~2.8–4.0 in opening hand)
- Do you have ramp in your opening hand? (want ≥ 0.8 expected)
- Is a card advantage engine online by turn 5? (want ≥ 1.2 expected)
- Is the game plan visible by turn 5? (want ≥ 2.0 plan cards expected)

Failure on any of these generates a specific assessment note.

#### Mulligan Guide

Built from the deck's actual cards rather than a generic template:

- **Engine pieces** — Card Advantage cards at CMC ≤ 4 (can realistically be cast in the first few turns)
- **Early ramp** — Ramp cards at CMC ≤ 2 (true acceleration, not late-game ramp)
- **Ideal hand profile** — constructed from the above and the commander's CMC
- **Mulligan triggers** — conditions that make a hand unkeepable regardless of curve

#### Sequencing Guide

Produces a turn-by-turn deployment plan using the cards actually in the deck at each CMC. The template adapts based on the commander's CMC — if the commander costs 6, it inserts a dedicated "Commander turn" at turn 6 rather than turn 4.

---

## Commander Rules Reference

- Official rules: https://mtgcommander.net/index.php/rules/
- Wizards format page: https://magic.wizards.com/en/formats/commander
- EDHREC bracket guide: https://edhrec.com/guides/edhrec-guide-to-commander-brackets
- Scryfall bulk data: https://scryfall.com/docs/api/bulk-data
- Scryfall API docs: https://scryfall.com/docs/api
