# UI/UX Design Brief — MTG Commander Deck Review

Reference this document before making any frontend changes. It defines the design system, layout conventions, and component patterns for the application.

---

## Aesthetic Direction — "Arcane Forge"

The app should feel like a craftsperson's instrument for deck construction: dark forged-steel surfaces with molten-gold accents. Data-dense but precise, with genuine craft rather than generic SaaS aesthetics. The MTG gold/multicolor card identity is the visual anchor — warm amber-gold signals "premium" and "important" throughout the UI.

**Tone:** Utilitarian luxury. Not flashy, not bare. Think a high-end workshop, not a game HUD.

---

## Typography

Fonts are loaded from Google Fonts via `@import` at the top of `style.css`. Do not substitute with system fonts.

| Role | Font | Usage |
|---|---|---|
| Display | `Cinzel` (400, 600, 700) | Logo, `commander-header h2`, bracket numbers, sequence turn labels, creativity score, download overlay title |
| Body / UI | `DM Sans` (300–700) | All labels, body copy, buttons, option groups, tab nav, table cells |
| Mono / Data | `Fira Code` (400, 600) | Decklist textarea, numeric data (bar counts, CMC, price), `code` elements |

**Rules:**
- Never use Inter, Roboto, Arial, or system-ui as a primary font.
- Cinzel is for landmark labels only — do not use it for body copy or data.
- Fira Code is for anything that benefits from tabular-nums alignment.

---

## Color System

All colors are CSS custom properties on `:root` in `style.css`. Always use tokens; never hardcode hex values in new CSS rules.

### Surfaces (dark → elevated)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#09090e` | Page background |
| `--bg2` | `#0d0e18` | Primary panel (`panel`) |
| `--bg3` | `#131420` | Inner panel (`panel-inner`), inputs, tables |
| `--bg4` | `#1a1c2c` | Elevated elements: stat cards, coverage cards, code blocks, tag backgrounds |

### Borders
| Token | Value | Use |
|---|---|---|
| `--border` | `#222436` | Default border on all surfaces |
| `--border-hi` | `#2c2f50` | Hover/active border highlight |

### Accent (gold)
| Token | Value | Use |
|---|---|---|
| `--accent` | `#c8a44a` | Primary interactive: links, active tab, focus ring base, button background |
| `--accent2` | `#e4c068` | Hover state of accent, large display numbers (stat values, bracket numbers), logo text |
| `--accent-dim` | `#7a6228` | Bar fill gradient end, dim decorative uses |
| `--accent-glow` | `rgba(200,164,74,.14)` | Focus ring shadow (`0 0 0 3px var(--accent-glow)`), panel glows |

### Text
| Token | Value | Use |
|---|---|---|
| `--text` | `#d4d7eb` | Primary body copy, table cell content |
| `--text2` | `#a4abc5` | Secondary labels, option group labels, table subtext, placeholder-adjacent text |
| `--text3` | `#b1b2be` | Tertiary / decorative — divider labels, empty state notes, very dim hints |

### Status colors (do not repurpose)
| Token | Use |
|---|---|
| `--green` `#4ade80` | Valid, OK, high synergy, keep rules |
| `--red` `#f87171` | Error, invalid, remove actions, mull rules |
| `--yellow` `#fbbf24` | Warning, close/medium states |
| `--blue` `#60a5fa` | Card Advantage role chip, Instant type |
| `--orange` `#fb923c` | Mass Disruption role chip, Planeswalker type |

### Hardcoded chart colors (in `app.js`)
These are used for canvas/inline bar fills and must stay in sync with the token palette if updated:

```js
TYPE_COLORS  = { Creatures: '#c8a44a', Sorceries: '#e4c068', Instants: '#60a5fa', ... }
ROLE_COLORS  = { synergy: '#c8a44a', tutors: '#e4c068', ramp: '#4ade80', ... }
COVERAGE_COLORS = { 'Plan Cards': '#c8a44a', ... }
```

---

## Spacing & Radius

| Token | Value |
|---|---|
| `--radius` | `12px` — outer panels |
| `--radius-sm` | `7px` — inner panels, inputs, buttons, tags |

Standard gaps: `gap: 8px` (tight lists), `gap: 14px` (grid columns), `gap: 16px` (panel children), `gap: 24px` (panel stack).

---

## Component Patterns

### Panels
Two levels: `.panel` (outer, `--bg2`) wraps `.panel-inner` (inner, `--bg3`). `.panel` has a full drop shadow. `.panel-inner` has a 1px border only.

`.panel h2` uses `Cinzel`, gold (`--accent2`), uppercase, `1rem`. This is the panel's section title.
`.panel-inner h3` uses `DM Sans`, `#c0c4d8`, uppercase, `0.72rem`, `letter-spacing: 1px`. This is a sub-section label — it should feel like a label, not a heading.

### Buttons
| Class | Appearance | Use |
|---|---|---|
| `.btn-primary` | Gold fill, dark text, full-width | Primary submit actions |
| `.btn-secondary` | `--bg4` fill, `--border` border | Secondary actions, exports, re-run |
| `.btn-import` | Gold-tinted border, gold text | Moxfield import specifically |
| `.btn-update` | Pill shape, gold-tinted | Header status actions |

All buttons use `font-family: inherit` and transition on `background`, `border-color`, and `transform` (lift on hover).

### Focus States
All interactive inputs use a gold glow ring on focus:
```css
outline: none;
border-color: var(--accent);
box-shadow: 0 0 0 3px var(--accent-glow);
```

### Tags and Pills
`.tag` — neutral pill for card names in synergy/bracket/staples.
`.tag.gc-tag` — gold-tinted for game-changer cards.
`a.focus-card-link` — gold pill for suggested commander role focus cards.
`.editable-role-tag` — gold-tinted card for user-added target roles in Plan tab.
`.role-tag` — colored inline chip for framework categories (Lands, Ramp, etc.).

### Tables
All tables use `border-collapse: collapse` with `--bg4` header rows, `--border` row separators, and `--bg3` hover highlight. Headers are uppercase, `0.68rem`, `letter-spacing: 0.8px`. Numeric columns use `font-family: 'Fira Code'` with `font-variant-numeric: tabular-nums`.

### Status/Feedback
Use left-border colored strips for inline feedback items:
```css
border-left: 3px solid var(--yellow); /* warning */
border-left: 3px solid var(--red);    /* error */
border-left: 3px solid var(--accent); /* advisor suggestion */
```

---

## Layout Conventions

### Page structure
`<header>` (sticky, 56px, glass blur) → `<main>` (max-width 1120px, centered) → `.panel` stack.

### Grids
- `.grid-2` — two equal columns, 14px gap. Collapses to 1 column at ≤640px.
- `.grid-3` — three equal columns, 14px gap. Collapses to 1 column at ≤640px.
- `.coverage-grid` — `repeat(auto-fill, minmax(245px, 1fr))` for coverage cards.
- `.cluster-grid` — `repeat(auto-fill, minmax(285px, 1fr))` for synergy clusters.
- `.detected-role-list` — `repeat(auto-fill, minmax(300px, 1fr))` — 2-up on desktop, 1-up on mobile.

### Plan Tab layout order
1. Path to Victory (full width)
2. Commander Role (full width) — detected themes grid + editable user-added tags + controls
3. Framework Coverage (full width)
4. CMC Curve vs Target + Playtest Simulation (`.grid-2`)
5. Mulligan Guide + Sequencing Guide (`.grid-2`)
6. Card Role Map (full width)

---

## Commander Role Panel — Behavior Notes

The Commander Role section has two distinct sub-lists:

**Detected themes (`detected-role-list`):**
- Auto-detected by the backend from EDHREC catalogs + deck evidence.
- Rendered as a 2-column grid of `.detected-role-item` cards.
- Each card shows name, kind/confidence, description, and evidence cards.
- A `×` remove button fades in on hover. Clicking it removes the role from `_targetCommanderRoles` and marks the card `.detected-role-removed` (dim + strikethrough). It does not disappear, preserving context.

**User-added roles (`target-role-tags`):**
- Only shows roles the user manually added via the Add Role controls — detected roles are filtered out by `_detectedCommanderRoleNames` so they don't duplicate the detected list.
- Rendered as `.editable-role-tag` pills with an always-visible `×` button.
- Empty state: "No custom roles added."

Both lists feed into `getTargetCommanderRoles()` which is what the re-run API call receives (detected + user-added, minus any the user removed).

---

## Motion

- Tab switches: `background`/`color` transition `0.15s`.
- Bar/chart fills: `width` transition `0.4s–0.55s cubic-bezier(.4,0,.2,1)`.
- Hover lifts on cards/buttons: `transform: translateY(-1px)`, `0.1s–0.15s`.
- Hover fades (remove buttons, cluster tags): `opacity 0.15s`.
- Focus rings: `box-shadow 0.15s`.
- Download progress bar: `width 0.3s ease`.
- Stale data pulse: `opacity` keyframe, `2s infinite`.

Avoid adding animations that run continuously except for the stale pulse and the loading spinner. One entrance animation per interaction is enough.

---

## What to Avoid

- **Purple/violet accents** — the previous design used `#7c6af7`. This has been replaced entirely with gold. Do not reintroduce purple as a primary accent.
- **Generic system fonts** — Inter, Segoe UI, Arial, Roboto are forbidden as primary fonts.
- **Hardcoding hex values in new CSS** — always use a token from `:root`.
- **Continuous animations** on data content (charts, tables, tags).
- **Overusing Cinzel** — display font only for landmarks, not labels or body copy.
- **`auto-fit` on grids where items should fill width** — use `auto-fill` or `flex-direction: column` to avoid orphaned gaps.
