/* MTG Commander Deck Review — frontend app */

// ── State ─────────────────────────────────────────────────────────────────────
let currentAnalysis = null;
let allCards = [];
let _targetCommanderRoles = [];
let _commanderRoleCatalog = { themes: [], typals: [] };
let _commanderRoleByName = new Map();

// Per-table sort state (mutated in place by initTableSort)
const _cardSort       = { col: 'name',    dir: 1  };
const _roleSort       = { col: 'name',    dir: 1  };
const _edhrecSort     = { col: 'synergy', dir: -1 };
const _creativitySort = { col: 'name',    dir: 1  };
let _creativityUnique  = [];
let _creativitySkipped = [];

// EDHREC card arrays — stored so sort can re-render them
let _edhrecMissing  = [];
let _edhrecIncluded = [];

const BUDGET_TIERS = {
  budget: { label: 'Budget', max_card_price: 5 },
  moderate: { label: 'Moderate', max_card_price: 15 },
  upgraded: { label: 'Upgraded', max_card_price: 30 },
  premium: { label: 'Premium', max_card_price: 60 },
  unlimited: { label: 'No Limit', max_card_price: null },
};

// ── Sort utilities ────────────────────────────────────────────────────────────
const RARITY_ORDER = { common: 0, uncommon: 1, rare: 2, mythic: 3 };

function _getSortVal(obj, col) {
  const v = obj[col];
  if (Array.isArray(v)) return v.join(',');
  if (col === 'rarity') return RARITY_ORDER[v] ?? -1;
  return v ?? '';
}

function sortArr(arr, col, dir) {
  return [...arr].sort((a, b) => {
    let av = _getSortVal(a, col), bv = _getSortVal(b, col);
    // Numeric columns
    if (['quantity','cmc','synergy','inclusion_pct','num_decks','tcgplayer_price','usd_price'].includes(col)) {
      av = av === '' ? -Infinity : Number(av);
      bv = bv === '' ? -Infinity : Number(bv);
    }
    if (col === 'rarity') { av = Number(av); bv = Number(bv); }
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
}

function updateSortIndicators(tableEl, col, dir) {
  tableEl.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === col) th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
  });
}

function initTableSort(tableEl, sortState, onSort) {
  tableEl.querySelectorAll('th[data-sort]').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      if (sortState.col === th.dataset.sort) sortState.dir *= -1;
      else { sortState.col = th.dataset.sort; sortState.dir = 1; }
      updateSortIndicators(tableEl, sortState.col, sortState.dir);
      onSort();
    });
  });
  updateSortIndicators(tableEl, sortState.col, sortState.dir);
}

// ── Color helpers ─────────────────────────────────────────────────────────────
const COLOR_MAP = { W: '#fef9c3', U: '#3b82f6', B: '#9333ea', R: '#ef4444', G: '#22c55e' };
const TYPE_COLORS = {
  Creatures: '#7c6af7', Instants: '#60a5fa', Sorceries: '#a78bfa',
  Artifacts: '#94a3b8', Enchantments: '#4ade80', Planeswalkers: '#fb923c', Lands: '#78716c',
};
const ROLE_COLORS = {
  ramp: '#4ade80', draw: '#60a5fa', removal: '#f87171', boardwipes: '#fb923c',
  tutors: '#a78bfa', threats: '#fbbf24', synergy: '#7c6af7', lands: '#78716c',
};

function colorPip(c) {
  const cls = { W: 'pip-W', U: 'pip-U', B: 'pip-B', R: 'pip-R', G: 'pip-G', C: 'pip-C' }[c] || 'pip-C';
  const label = { W: 'W', U: 'U', B: 'B', R: 'R', G: 'G', C: 'C' }[c] || c;
  return `<span class="color-pip ${cls}">${label}</span>`;
}

function formatPrice(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return '—';
  return `$${amount.toFixed(2)}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function normalizeRoleKey(role) {
  return String(role || '').trim().toLowerCase();
}

function rebuildCommanderRoleIndex() {
  _commanderRoleByName = new Map();
  [...(_commanderRoleCatalog.themes || []), ...(_commanderRoleCatalog.typals || [])].forEach(role => {
    _commanderRoleByName.set(normalizeRoleKey(role.name), role);
    (role.aliases || []).forEach(alias => _commanderRoleByName.set(normalizeRoleKey(alias), role));
  });
}

function getCommanderRoleMeta(roleName) {
  return _commanderRoleByName.get(normalizeRoleKey(roleName)) || null;
}

async function loadCommanderRoleCatalog() {
  try {
    const r = await fetch('/api/commander-roles');
    if (!r.ok) return;
    const data = await r.json();
    _commanderRoleCatalog = {
      themes: data.themes || [],
      typals: data.typals || [],
    };
    rebuildCommanderRoleIndex();
    if (currentAnalysis && !document.getElementById('results-panel').classList.contains('hidden')) {
      renderPlan(currentAnalysis);
    }
  } catch {
    // Role descriptions are progressive enhancement; analysis still works without them.
  }
}

function getCardUrl(name, fallbackUrl = '') {
  if (fallbackUrl) return fallbackUrl;

  const match = (currentAnalysis?.cards || []).find(card =>
    (card.name || card.raw_name || '').toLowerCase() === String(name || '').toLowerCase() &&
    card.scryfall_uri
  );

  if (match?.scryfall_uri) return match.scryfall_uri;
  return `https://scryfall.com/search?q=!%22${encodeURIComponent(name || '')}%22`;
}

function renderCardLink(name, { url = '', className = 'card-name-link', label = null } = {}) {
  const href = getCardUrl(name, url);
  const text = label ?? name;
  return `<a class="${className}" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>`;
}

function getBudgetConfig() {
  const analysisBudget = currentAnalysis?.budget;
  if (analysisBudget) return analysisBudget;

  const selected = document.getElementById('budget-tier-select')?.value || '';
  if (!selected) return null;
  const tier = BUDGET_TIERS[selected];
  return tier ? { tier: selected, ...tier } : null;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function linkKnownCardNames(text, extraNames = [], className = 'inline-card-link') {
  const rawText = String(text || '');
  const names = [
    ...(currentAnalysis?.cards || []).map(card => card.name || card.raw_name || '').filter(Boolean),
    ...extraNames,
  ];
  const uniqueNames = [...new Set(names)].sort((a, b) => b.length - a.length);

  if (!uniqueNames.length) return escapeHtml(rawText);

  const pattern = uniqueNames.map(escapeRegExp).join('|');
  if (!pattern) return escapeHtml(rawText);

  const regex = new RegExp(pattern, 'g');
  let result = '';
  let lastIndex = 0;

  for (const match of rawText.matchAll(regex)) {
    const index = match.index ?? 0;
    result += escapeHtml(rawText.slice(lastIndex, index));
    result += renderCardLink(match[0], { className });
    lastIndex = index + match[0].length;
  }

  result += escapeHtml(rawText.slice(lastIndex));
  return result;
}

function linkSuggestionText(text) {
  const rawText = String(text || '');
  const candidates = [];
  const addCandidate = value => {
    const cleaned = String(value || '')
      .replace(/[*_`[\]]/g, '')
      .replace(/^\d+\.\s*/, '')
      .replace(/^[-•]\s*/, '')
      .replace(/^(?:format staples|staples|cards?)\s*:\s*/i, '')
      .trim();

    if (!cleaned || cleaned.length > 120) return;
    candidates.push(cleaned);

    if (/(,\s+(?:or|and)\s+)|(\s+(?:or|and)\s+)/i.test(cleaned) || (cleaned.match(/,/g) || []).length >= 2) {
      cleaned
        .split(/\s*,\s*(?:or\s+|and\s+)?|\s+(?:or|and)\s+/i)
        .map(part => part.trim())
        .filter(part => part.length > 1)
        .forEach(part => candidates.push(part));
    }
  };
  const labelPattern = /(?:^|[\s*_\-•(])(?:cut|add|replace|swap|remove|include|run|try|upgrade(?: to)?|consider(?: adding)?):?\s+([^→\n.;]+?)(?=\s*(?:→|->|with\b|for\b|because\b|[-—–]|\.|;|$))/gi;
  const arrowPattern = /(?:^|[\s*_\-•(])([^→\n.;:]{2,80}?)\s*(?:→|->)\s*(?:add:?\s*)?([^—–\-\n.;]{2,80})/gi;

  for (const match of rawText.matchAll(labelPattern)) {
    addCandidate(match[1]);
  }
  for (const match of rawText.matchAll(arrowPattern)) {
    addCandidate(match[1].replace(/^(?:cut|replace|swap|remove):?\s+/i, ''));
    addCandidate(match[2]);
  }

  const extraNames = candidates
    .filter(name => name.length > 1 && name.length <= 80);

  return linkKnownCardNames(rawText, extraNames);
}

function normalizeAdvisorSuggestions(suggestions) {
  const normalized = [];
  let current = '';
  const isStart = value => /^(?:[-•]\s*)?(?:\d+[\.)]\s+|cut\b|add\b|replace\b|swap\b|remove\b|include\b|try\b|consider\b|→|->)/i.test(String(value || '').trim());

  (suggestions || []).forEach(item => {
    const parts = String(item || '')
      .split(/(?=\s+(?:\d+[\.)]\s+))/g)
      .map(part => part.trim())
      .filter(Boolean);

    parts.forEach(text => {
      if (isStart(text) || !current) {
        if (current) normalized.push(current);
        current = text;
      } else {
        current = `${current} ${text}`;
      }
    });
  });

  if (current) normalized.push(current);
  return normalized;
}

function renderSuggestionList(suggestions) {
  return normalizeAdvisorSuggestions(suggestions)
    .map(s => `<div class="suggestion-item">${linkSuggestionText(s)}</div>`)
    .join('');
}

const ADVISOR_SECTION_TITLES = {
  summary: 'Deck Summary',
  suggestions: 'Card Suggestions',
  coverage: 'Coverage Gaps',
  power: 'Power-Level Assessment',
};

function normalizeAdvisorSectionHeading(line) {
  const cleaned = String(line || '')
    .replace(/^#{1,6}\s*/, '')
    .replace(/[*_`]/g, '')
    .replace(/^[^\w]+/, '')
    .replace(/:$/, '')
    .trim()
    .toLowerCase();

  if (!cleaned) return null;
  if (/deck\s+summary|summary/.test(cleaned)) return 'summary';
  if (/card\s+suggestions?|suggestions?|recommendations?/.test(cleaned)) return 'suggestions';
  if (/coverage\s+gaps?|category\s+gaps?|plan\s+framework/.test(cleaned)) return 'coverage';
  if (/power[-\s]?level|power\s+assessment|playgroup|closing/.test(cleaned)) return 'power';
  return null;
}

function parseAdvisorSections(data) {
  const raw = String(data.ai_full_response || '').trim();
  if (!raw) {
    const sections = [];
    if (data.ai_summary) sections.push({ key: 'summary', title: ADVISOR_SECTION_TITLES.summary, lines: [data.ai_summary] });
    if ((data.ai_suggestions || []).length) sections.push({ key: 'suggestions', title: ADVISOR_SECTION_TITLES.suggestions, lines: data.ai_suggestions });
    return sections;
  }

  const normalizedRaw = raw.replace(
    /\s*(\*{0,2}(?:deck\s+summary|card\s+suggestions?|coverage\s+gaps?|power[-\s]?level\s+assessment|power\s+assessment|closing\s+assessment)\*{0,2}:?)/gi,
    '\n$1\n'
  );
  const sections = [];
  let current = null;

  normalizedRaw.split(/\r?\n/).forEach(line => {
    const text = line.trim();
    if (!text) return;

    const heading = normalizeAdvisorSectionHeading(text);
    const isHeadingOnly = heading && text.replace(/[*_`:#\s-]/g, '').length <= 32;
    if (isHeadingOnly) {
      if (current && current.lines.length) sections.push(current);
      current = { key: heading, title: ADVISOR_SECTION_TITLES[heading], lines: [] };
      return;
    }

    if (!current) current = { key: 'summary', title: ADVISOR_SECTION_TITLES.summary, lines: [] };
    current.lines.push(text);
  });

  if (current && current.lines.length) sections.push(current);

  if (!sections.some(section => section.key === 'suggestions') && (data.ai_suggestions || []).length) {
    sections.push({ key: 'suggestions', title: ADVISOR_SECTION_TITLES.suggestions, lines: data.ai_suggestions });
  }

  return sections;
}

function renderAdvisorTextSection(section, extraCardNames) {
  const body = section.lines
    .join('\n')
    .split(/\n{2,}/)
    .map(paragraph => paragraph.trim())
    .filter(Boolean)
    .map(paragraph => `<p>${linkKnownCardNames(paragraph.replace(/^[-•]\s*/, ''), extraCardNames)}</p>`)
    .join('');

  return `
    <div class="advisor-section">
      <h3>${escapeHtml(section.title)}</h3>
      <div class="advisor-text-card">${body}</div>
    </div>
  `;
}

function renderAdvisorSections(data, extraCardNames = []) {
  const sections = parseAdvisorSections(data);
  if (!sections.length) return '';

  return sections.map(section => {
    if (section.key === 'suggestions') {
      const suggestionLines = (data.ai_suggestions || []).length ? data.ai_suggestions : section.lines;
      return `
        <div class="advisor-section">
          <h3>${escapeHtml(section.title)}</h3>
          <div class="suggestion-list">
            ${renderSuggestionList(suggestionLines)}
          </div>
        </div>
      `;
    }
    return renderAdvisorTextSection(section, extraCardNames);
  }).join('');
}

function getActiveBracketValue() {
  const resultsVisible = !document.getElementById('results-panel').classList.contains('hidden');
  const targetSelect = document.getElementById('target-bracket-select');
  if (resultsVisible && targetSelect) return targetSelect.value;
  return document.getElementById('bracket-select').value;
}

function getTargetCommanderRoles() {
  const seen = new Set();
  return _targetCommanderRoles
    .map(role => canonicalizeCommanderRole(role))
    .filter(role => {
      if (!role) return false;
      const key = normalizeRoleKey(role);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function canonicalizeCommanderRole(role) {
  const meta = getCommanderRoleMeta(role);
  return meta ? meta.name : role.trim();
}

function renderCommanderRoleOptions() {
  const themes = _commanderRoleCatalog.themes || [];
  const typals = _commanderRoleCatalog.typals || [];
  if (!themes.length && !typals.length) {
    return `
      <option value="Tokens">Tokens</option>
      <option value="+1/+1 Counters">+1/+1 Counters</option>
      <option value="Artifacts">Artifacts</option>
      <option value="Spellslinger">Spellslinger</option>
      <option value="Aristocrats">Aristocrats</option>
      <option value="Dragons">Dragons</option>
    `;
  }
  const themeOptions = themes.map(role =>
    `<option value="${escapeHtml(role.name)}">${escapeHtml(role.name)} · ${Number(role.deck_count || 0).toLocaleString()} decks</option>`
  ).join('');
  const typalOptions = typals.map(role =>
    `<option value="${escapeHtml(role.name)}">${escapeHtml(role.name)} · ${Number(role.deck_count || 0).toLocaleString()} decks</option>`
  ).join('');
  return `
    <optgroup label="EDHREC Themes">${themeOptions}</optgroup>
    <optgroup label="Typal Decks">${typalOptions}</optgroup>
  `;
}

function renderCommanderRoleDatalistOptions() {
  const roles = [...(_commanderRoleCatalog.themes || []), ...(_commanderRoleCatalog.typals || [])];
  return roles.map(role => `<option value="${escapeHtml(role.name)}"></option>`).join('');
}

function renderTargetRoleTags() {
  const el = document.getElementById('target-role-tags');
  if (!el) return;

  const roles = getTargetCommanderRoles();
  el.innerHTML = roles.length
    ? roles.map((role, index) => {
        const meta = getCommanderRoleMeta(role);
        const kind = meta?.kind === 'typal' ? 'Typal' : (meta?.kind === 'theme' ? 'Theme' : 'Custom');
        const description = meta?.description || `Builds around ${role} synergies as the deck's main plan.`;
        return `
        <div class="editable-role-tag">
          <div class="role-tag-main">
            <span>${escapeHtml(role)}</span>
            <span class="role-kind">${kind}</span>
            <button type="button" class="role-remove-btn" data-role-index="${index}" aria-label="Remove ${escapeHtml(role)}">&times;</button>
          </div>
          <div class="role-tag-description">${escapeHtml(description)}</div>
        </div>
      `;
      }).join('')
    : '<span style="color:var(--text3);font-size:.85rem">No target roles set.</span>';

  el.querySelectorAll('.role-remove-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _targetCommanderRoles.splice(Number(btn.dataset.roleIndex), 1);
      renderTargetRoleTags();
    });
  });
}

function addTargetCommanderRole() {
  const input = document.getElementById('target-role-input');
  const select = document.getElementById('target-role-select');
  if (!input && !select) return;
  const role = canonicalizeCommanderRole((input?.value || '').trim() || (select?.value || '').trim());
  if (!role) return;

  const exists = _targetCommanderRoles.some(existing => existing.toLowerCase() === role.toLowerCase());
  if (!exists) _targetCommanderRoles.push(role);
  if (input) input.value = '';
  renderTargetRoleTags();
}

function bindTargetControls() {
  const addBtn = document.getElementById('target-role-add-btn');
  const input = document.getElementById('target-role-input');
  const select = document.getElementById('target-role-select');
  const rerunBtn = document.getElementById('target-analysis-btn');
  const targetBracket = document.getElementById('target-bracket-select');

  if (addBtn) addBtn.addEventListener('click', addTargetCommanderRole);
  if (select) {
    select.addEventListener('change', () => {
      if (input && select.value) input.value = select.value;
    });
  }
  if (input) {
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        addTargetCommanderRole();
      }
    });
  }
  if (targetBracket) {
    targetBracket.addEventListener('change', () => {
      document.getElementById('bracket-select').value = targetBracket.value;
    });
  }
  if (rerunBtn) {
    rerunBtn.addEventListener('click', () => {
      document.getElementById('skip-ai-check').checked = false;
      submitDeck();
    });
  }
}

// ── Status checks ─────────────────────────────────────────────────────────────
async function checkIndexStatus() {
  const indexBadge = document.getElementById('index-status');
  const bulkBadge  = document.getElementById('bulk-status');
  const updateBtn  = document.getElementById('update-data-btn');

  try {
    const r    = await fetch('/health');
    const data = await r.json();

    // ── Card index ───────────────────────────────────────────────────
    if (data.index_ready) {
      indexBadge.textContent = 'Index: ready';
      indexBadge.className   = 'badge badge-ready';
      enableSubmit();
    } else {
      indexBadge.textContent = 'Index: building…';
      indexBadge.className   = 'badge badge-building';
      await buildIndex();
    }

    // ── Bulk data freshness ───────────────────────────────────────────
    const bulk = data.bulk_data || {};
    renderBulkBadge(bulk, bulkBadge, updateBtn);

  } catch {
    indexBadge.textContent = 'Server offline';
    indexBadge.className   = 'badge badge-error';
    bulkBadge.textContent  = 'Data: offline';
    bulkBadge.className    = 'badge badge-error';
  }
}

function renderBulkBadge(bulk, badge, btn) {
  if (!bulk.found) {
    badge.textContent = 'Data: missing';
    badge.className   = 'badge badge-error';
    btn.classList.remove('hidden');
    btn.classList.add('stale');
    return;
  }

  const age   = bulk.age_human || '?';
  const stale = bulk.is_stale;
  const aging = (bulk.age_hours || 0) > 12;   // warn after 12 h, stale after 24 h

  if (stale) {
    badge.textContent = `Data: ${age} — STALE`;
    badge.className   = 'badge badge-stale';
    btn.classList.remove('hidden');
    btn.classList.add('stale');
    btn.title = 'Scryfall data is over 24 hours old — click to download the latest';
  } else if (aging) {
    badge.textContent = `Data: ${age}`;
    badge.className   = 'badge badge-aging';
    btn.classList.remove('hidden');
    btn.classList.remove('stale');
    btn.title = `Data is ${age} old — update recommended before 24h`;
  } else {
    badge.textContent = `Data: ${age}`;
    badge.className   = 'badge badge-ready';
    btn.classList.remove('hidden', 'stale');   // still show it, just neutral
    btn.title = `Bulk data is ${age} old (fresh)`;
  }
}

async function buildIndex() {
  const badge = document.getElementById('index-status');
  badge.textContent = 'Index: building (~30s)…';
  badge.className   = 'badge badge-building';
  try {
    const r    = await fetch('/api/index/build', { method: 'POST' });
    const data = await r.json();
    if (data.success) {
      badge.textContent = 'Index: ready';
      badge.className   = 'badge badge-ready';
      enableSubmit();
    }
  } catch {
    badge.textContent = 'Index: build failed';
    badge.className   = 'badge badge-error';
  }
}

function enableSubmit() {
  document.getElementById('submit-btn').disabled = false;
}

// ── Data update flow ──────────────────────────────────────────────────────────
let _pollInterval = null;

document.getElementById('update-data-btn').addEventListener('click', async () => {
  const confirmed = confirm(
    'This will download the latest Scryfall card database (~500 MB) and rebuild the card index.\n\n' +
    'The server will remain usable during the download. Continue?'
  );
  if (!confirmed) return;

  try {
    const r = await fetch('/api/bulk-data/update', { method: 'POST' });
    if (!r.ok) {
      const err = await r.json();
      alert(`Could not start update: ${err.detail || r.statusText}`);
      return;
    }
    showDownloadOverlay();
    startPollingProgress();
  } catch (e) {
    alert(`Network error: ${e.message}`);
  }
});

function showDownloadOverlay() {
  document.getElementById('download-overlay').classList.remove('hidden');
  setDownloadProgress('fetching_metadata', 0, 'Querying Scryfall API…');
}

function hideDownloadOverlay() {
  document.getElementById('download-overlay').classList.add('hidden');
}

function setDownloadProgress(status, pct, message) {
  document.getElementById('download-message').textContent = message || status;
  document.getElementById('download-bar').style.width     = `${pct}%`;
  document.getElementById('download-pct').textContent     = `${pct}%`;
}

function startPollingProgress() {
  if (_pollInterval) clearInterval(_pollInterval);
  _pollInterval = setInterval(async () => {
    try {
      const r    = await fetch('/api/bulk-data/progress');
      const data = await r.json();
      const { status, pct = 0, message = '', downloaded_mb, total_mb, filename } = data;

      let label = message || status;
      if (status === 'downloading' && downloaded_mb != null) {
        label = `Downloading ${filename || ''}… ${downloaded_mb} / ${total_mb} MB`;
      } else if (status === 'rebuilding_index') {
        label = 'Rebuilding card index — almost done…';
      } else if (status === 'done') {
        label = 'Update complete!';
      } else if (status === 'error') {
        label = `Error: ${message}`;
      }

      setDownloadProgress(status, pct, label);

      if (status === 'done' || status === 'error') {
        clearInterval(_pollInterval);
        _pollInterval = null;
        setTimeout(async () => {
          hideDownloadOverlay();
          await checkIndexStatus();   // refresh all badges
        }, status === 'done' ? 1500 : 3000);
      }
    } catch {
      // transient network hiccup — keep polling
    }
  }, 1500);
}

// ── Moxfield import ───────────────────────────────────────────────────────────
document.getElementById('moxfield-import-btn').addEventListener('click', async () => {
  const url = document.getElementById('moxfield-url').value.trim();
  if (!url) { alert('Paste a Moxfield deck URL first.'); return; }

  const btn = document.getElementById('moxfield-import-btn');
  const statusEl = document.getElementById('moxfield-status');
  btn.disabled = true;
  btn.textContent = 'Importing…';
  statusEl.className = 'moxfield-status';
  statusEl.textContent = '';

  try {
    const r = await fetch(`/api/moxfield?url=${encodeURIComponent(url)}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);

    document.getElementById('paste-input').value = data.text || '';
    if (data.commander) {
      document.getElementById('commander-input').value = data.commander;
    }
    statusEl.className = 'moxfield-status moxfield-ok';
    statusEl.textContent = `Imported: ${data.deck_name || 'deck'}`;
    statusEl.classList.remove('hidden');
  } catch (err) {
    statusEl.className = 'moxfield-status moxfield-err';
    statusEl.textContent = `Import failed: ${err.message}`;
    statusEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import';
  }
});

// ── File drag & drop ──────────────────────────────────────────────────────────
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
let selectedFile = null;

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});
dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

function handleFile(f) {
  selectedFile = f;
  dropZone.innerHTML = `<div class="drop-icon">✅</div><p><strong>${f.name}</strong> selected (${(f.size/1024).toFixed(1)} KB)</p>`;
  // Also read text into paste area for preview
  const reader = new FileReader();
  reader.onload = e => { document.getElementById('paste-input').value = e.target.result; };
  reader.readAsText(f);
}

// ── Submit ────────────────────────────────────────────────────────────────────
document.getElementById('submit-btn').addEventListener('click', submitDeck);

async function submitDeck() {
  const text = document.getElementById('paste-input').value.trim();
  const commander = document.getElementById('commander-input').value.trim();
  const bracket = getActiveBracketValue();
  const budgetTier = document.getElementById('budget-tier-select').value;
  const aiProvider = document.getElementById('ai-provider-select').value;
  const aiModel = document.getElementById('ai-model-input').value.trim();
  const skipAi = document.getElementById('skip-ai-check').checked;
  const targetRoles = getTargetCommanderRoles();
  const hasTargetRoleEditor = Boolean(document.getElementById('target-role-tags'));

  if (!text && !selectedFile) {
    alert('Please provide a decklist (file or paste).');
    return;
  }

  showLoading('Parsing and enriching cards from Scryfall…');

  const fd = new FormData();
  if (selectedFile) {
    fd.append('file', selectedFile);
  } else {
    // Create a blob from pasted text
    const blob = new Blob([text], { type: 'text/plain' });
    fd.append('file', blob, 'pasted_deck.txt');
  }
  if (commander) fd.append('commander', commander);
  if (bracket) fd.append('intended_bracket', bracket);
  if (budgetTier) fd.append('budget_tier', budgetTier);
  if (hasTargetRoleEditor || targetRoles.length) fd.append('commander_roles', JSON.stringify(targetRoles));
  if (aiProvider) fd.append('ai_provider', aiProvider);
  if (aiModel) fd.append('ai_model', aiModel);
  fd.append('skip_ai', skipAi ? 'true' : 'false');

  try {
    const r = await fetch('/api/review', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json();
      throw new Error(err.detail || r.statusText);
    }
    const data = await r.json();
    currentAnalysis = data;
    allCards = data.cards || [];
    renderResults(data);
  } catch (err) {
    hideLoading();
    alert(`Error: ${err.message}`);
  }
}

function showLoading(msg) {
  document.getElementById('upload-panel').classList.add('hidden');
  document.getElementById('loading-panel').classList.remove('hidden');
  document.getElementById('results-panel').classList.add('hidden');
  document.getElementById('loading-msg').textContent = msg;
}

function hideLoading() {
  document.getElementById('loading-panel').classList.add('hidden');
  document.getElementById('upload-panel').classList.remove('hidden');
}

// ── Render Results ────────────────────────────────────────────────────────────
function renderResults(data) {
  document.getElementById('loading-panel').classList.add('hidden');
  document.getElementById('results-panel').classList.remove('hidden');

  renderCommanderHeader(data);
  renderOverview(data);
  renderPlan(data);
  renderValidation(data);
  renderSynergy(data);
  renderBracket(data);
  renderAI(data);
  renderCardList(data.cards || []);
}

// ── Commander Header ──────────────────────────────────────────────────────────
function getCommanderEntries(data) {
  return (data.cards || []).filter(card => card.is_commander);
}

function manaSymbolColors(token) {
  const normalized = String(token || '').toUpperCase();
  const colors = ['W', 'U', 'B', 'R', 'G'].filter(color => normalized.includes(color));
  return [...new Set(colors)];
}

function renderManaSymbol(token) {
  const colors = manaSymbolColors(token);
  const text = escapeHtml(token);
  if (!colors.length) {
    return `<span class="mana-symbol mana-symbol-generic">${text}</span>`;
  }
  if (colors.length === 1) {
    return `<span class="mana-symbol mana-symbol-${colors[0]}">${text}</span>`;
  }

  const palette = { W: '#fef3c7', U: '#60a5fa', B: '#7c3aed', R: '#ef4444', G: '#22c55e' };
  const step = 100 / colors.length;
  const stops = colors.map((color, index) => {
    const start = (index * step).toFixed(2);
    const end = ((index + 1) * step).toFixed(2);
    return `${palette[color]} ${start}% ${end}%`;
  }).join(', ');
  return `<span class="mana-symbol mana-symbol-hybrid" style="background:linear-gradient(135deg, ${stops})">${text}</span>`;
}

function formatManaCost(manaCost) {
  if (!manaCost) return '—';
  return escapeHtml(manaCost).replace(/\{([^}]+)\}/g, (_, token) => renderManaSymbol(token));
}

function formatStats(card) {
  if (card.power && card.toughness) return `${escapeHtml(card.power)}/${escapeHtml(card.toughness)}`;
  if (card.defense) return `[${escapeHtml(card.defense)}]`;
  return '—';
}

function renderCommanderCardDetails(card) {
  if (!card) return '';
  const keywords = (card.keywords || []).slice(0, 6);
  return `
    <div class="commander-detail-card">
      <div class="commander-detail-top">
        <div>
          <div class="commander-detail-name">${renderCardLink(card.name || card.raw_name, { url: card.scryfall_uri, className: 'commander-detail-link' })}</div>
          <div class="commander-type">${escapeHtml(card.type_line || 'Unknown type')}</div>
        </div>
        <div class="commander-mana">${formatManaCost(card.mana_cost)}</div>
      </div>
      <div class="commander-facts">
        <span>MV ${card.cmc ?? '—'}</span>
        <span>${formatStats(card)}</span>
        <span>${escapeHtml(card.rarity || 'unknown')}</span>
      </div>
      ${keywords.length ? `<div class="commander-keywords">${keywords.map(k => `<span>${escapeHtml(k)}</span>`).join('')}</div>` : ''}
      ${card.oracle_text ? `<div class="commander-oracle">${escapeHtml(card.oracle_text).replace(/\n/g, '<br>')}</div>` : ''}
    </div>
  `;
}

function renderCommanderHeader(data) {
  const el = document.getElementById('commander-header');
  const commanderEntries = getCommanderEntries(data);
  const ci = (data.color_identity || []).map(colorPip).join('');
  const commander = data.commander
    ? renderCardLink(data.commander, { className: 'commander-name-link' })
    : 'Unknown Commander';
  const partner = data.partner
    ? ` <span style="color:var(--text2)">+</span> ${renderCardLink(data.partner, { className: 'commander-name-link' })}`
    : '';
  const bracketNum = data.bracket?.bracket;
  const bracketLabel = data.bracket?.label;
  const bracketStr = bracketNum != null
    ? `Bracket ${bracketNum}${bracketLabel ? ` — ${escapeHtml(bracketLabel)}` : ''}`
    : 'Unknown Bracket';
  const cardDetails = commanderEntries.map(renderCommanderCardDetails).join('');
  el.innerHTML = `
    <h2>${commander}${partner}</h2>
    <div class="subtitle">${ci} &nbsp; ${bracketStr}</div>
    ${cardDetails ? `<div class="commander-details">${cardDetails}</div>` : ''}
  `;
}

// ── Overview Tab ──────────────────────────────────────────────────────────────
function renderOverview(data) {
  document.getElementById('stat-count').textContent = data.card_count || 0;
  document.getElementById('stat-cmc').textContent = data.avg_cmc || '—';

  const ci = (data.color_identity || []).map(colorPip).join('');
  document.getElementById('stat-colors').innerHTML = ci || '<span style="color:var(--text3)">Colorless</span>';

  renderManaCurve(data.mana_curve || {});
  renderTypeDonut(data.type_breakdown || {});
  renderRoleBars(data.role_breakdown || {});

  const allWarnings = [
    ...(data.synergy_warnings || []),
  ];
  const wp = document.getElementById('warnings-panel');
  const wl = document.getElementById('warnings-list');
  if (allWarnings.length) {
    wl.innerHTML = allWarnings.map(w => `<li>${linkKnownCardNames(w)}</li>`).join('');
    wp.style.display = '';
  } else {
    wp.style.display = 'none';
  }
}

function renderManaCurve(curve) {
  const el = document.getElementById('mana-curve-chart');
  const max = Math.max(...Object.values(curve), 1);
  const labels = ['0','1','2','3','4','5','6','7+'];
  el.innerHTML = labels.map(l => {
    const count = curve[l] || 0;
    const pct = Math.round((count / max) * 100);
    return `<div class="bar-wrap">
      <div class="bar-count">${count}</div>
      <div class="bar" style="height:${Math.max(pct, count ? 3 : 0)}%"></div>
      <div class="bar-label">${l}</div>
    </div>`;
  }).join('');
}

function renderTypeDonut(breakdown) {
  const canvas = document.getElementById('type-canvas');
  const ctx = canvas.getContext('2d');
  const legend = document.getElementById('type-legend');

  const entries = Object.entries(breakdown).filter(([,v]) => v > 0);
  const total = entries.reduce((s,[,v]) => s+v, 0);
  if (!total) return;

  ctx.clearRect(0, 0, 220, 220);
  let start = -Math.PI/2;
  const cx = 110, cy = 110, r = 80, ir = 50;

  entries.forEach(([type, count]) => {
    const angle = (count / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + angle);
    ctx.closePath();
    ctx.fillStyle = TYPE_COLORS[type] || '#555';
    ctx.fill();
    // Inner hole
    ctx.beginPath();
    ctx.arc(cx, cy, ir, 0, 2*Math.PI);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg3').trim() || '#1e2030';
    ctx.fill();
    start += angle;
  });

  legend.innerHTML = entries.map(([type, count]) => `
    <div class="legend-item">
      <div class="legend-dot" style="background:${TYPE_COLORS[type] || '#555'}"></div>
      <span>${type}: <strong>${count}</strong></span>
    </div>
  `).join('');
}

function renderRoleBars(roles) {
  const el = document.getElementById('role-bars');
  const entries = Object.entries(roles).sort(([,a],[,b]) => b-a);
  const max = Math.max(...entries.map(([,v]) => v), 1);
  el.innerHTML = entries.map(([role, count]) => {
    const pct = Math.round((count / max) * 100);
    const color = ROLE_COLORS[role] || '#7c6af7';
    return `<div class="role-row">
      <div class="role-label">${role}</div>
      <div class="role-bar-bg"><div class="role-bar-fill" style="width:${pct}%;background:${color}"></div></div>
      <div class="role-count">${count}</div>
    </div>`;
  }).join('');
}

// ── Plan Tab ──────────────────────────────────────────────────────────────────
const COVERAGE_COLORS = {
  'Lands':           '#78716c',
  'Card Advantage':  '#60a5fa',
  'Ramp':            '#4ade80',
  'Removal':         '#f87171',
  'Mass Disruption': '#fb923c',
  'Plan Cards':      '#a78bfa',
};

function renderPlan(data) {
  const plan = data.plan || {};

  // ── Commander Role ───────────────────────────────────────────────────
  const roles = plan.commander_roles || [];
  const detectedRoles = plan.detected_commander_roles || [];
  const detectedMatches = plan.detected_commander_role_matches || [];
  const roleSource = plan.commander_roles_source || 'detected';
  _targetCommanderRoles = [...roles.filter(Boolean)];
  const plannedBracket = data.intended_bracket || document.getElementById('bracket-select').value || '';
  document.getElementById('bracket-select').value = plannedBracket;
  const detectedHtml = detectedMatches.length
    ? `<div class="detected-role-list">${detectedMatches.map(match => {
        const evidence = (match.evidence || []).join('; ');
        const kind = match.kind === 'typal' ? 'Typal' : 'Theme';
        const confidence = match.confidence ? `${match.confidence} confidence` : 'detected';
        return `
          <div class="detected-role-item">
            <div class="detected-role-head">
              <span>${escapeHtml(match.name)}</span>
              <span>${escapeHtml(kind)} · ${escapeHtml(confidence)}</span>
            </div>
            <div class="detected-role-desc">${escapeHtml(match.description || '')}</div>
            ${evidence ? `<div class="detected-role-evidence">${escapeHtml(evidence)}</div>` : ''}
          </div>
        `;
      }).join('')}</div>`
    : '';
  document.getElementById('plan-cmd-roles').innerHTML = `
    <div class="target-editor">
      <div class="target-editor-note">
        Current target roles are used for focus advice, sequencing, and Advisor recommendations.
        ${roleSource === 'user' ? `Detected roles: ${escapeHtml(detectedRoles.join(', ') || 'Unknown')}` : 'These started from detected roles.'}
      </div>
      ${detectedHtml}
      <div id="target-role-tags" class="editable-role-list"></div>
      <div class="target-control-row">
        <select id="target-role-select" aria-label="Known commander role">
          <option value="">Browse EDHREC themes and typals</option>
          ${renderCommanderRoleOptions()}
        </select>
        <input type="text" id="target-role-input" list="commander-role-options" placeholder="Add target role, e.g. Tokens" />
        <button type="button" id="target-role-add-btn" class="btn-secondary">Add Role</button>
      </div>
      <datalist id="commander-role-options">
        ${renderCommanderRoleDatalistOptions()}
      </datalist>
      <div class="target-control-row">
        <label for="target-bracket-select">Planned Bracket</label>
        <select id="target-bracket-select">
          <option value="">Auto-detect</option>
          <option value="1" ${String(plannedBracket) === '1' ? 'selected' : ''}>1 — Exhibition</option>
          <option value="2" ${String(plannedBracket) === '2' ? 'selected' : ''}>2 — Core</option>
          <option value="3" ${String(plannedBracket) === '3' ? 'selected' : ''}>3 — Upgraded</option>
          <option value="4" ${String(plannedBracket) === '4' ? 'selected' : ''}>4 — Optimized</option>
          <option value="5" ${String(plannedBracket) === '5' ? 'selected' : ''}>5 — cEDH</option>
        </select>
        <button type="button" id="target-analysis-btn" class="btn-primary target-submit-btn">Re-run Analysis With Targets</button>
      </div>
    </div>
  `;
  renderTargetRoleTags();
  bindTargetControls();
  const _focusRaw = plan.commander_focus_advice || {};
  const _focusText  = typeof _focusRaw === 'string' ? _focusRaw : (_focusRaw.text || '');
  const _focusCards = typeof _focusRaw === 'object' && !Array.isArray(_focusRaw)
    ? (_focusRaw.suggested_cards || []) : [];
  document.getElementById('plan-focus-advice').textContent = _focusText;
  document.getElementById('plan-focus-cards').innerHTML = _focusCards.length
    ? _focusCards.map(c =>
        `<a class="tag focus-card-link" href="${c.url}" target="_blank" rel="noopener">${c.name} ↗</a>`
      ).join('')
    : '';

  // ── Path to Victory ──────────────────────────────────────────────────
  const ptv = plan.path_to_victory || {};
  const conf = (ptv.confidence || 'Low').toLowerCase();
  const ptvEl = document.getElementById('plan-ptv');
  const ptvSummary = linkKnownCardNames(ptv.summary || '');
  ptvEl.innerHTML = `
    <div class="ptv-box ptv-${conf}">
      <div class="ptv-label">${ptv.confidence || '—'} Confidence</div>
      <div class="ptv-summary">${ptvSummary}</div>
      <div class="ptv-detail">
        Commander on curve: Turn ${ptv.commander_earliest_turn || '?'} &nbsp;|&nbsp;
        Payoffs: ${ptv.payoff_count || 0} &nbsp;|&nbsp;
        Low-CMC payoffs: ${(ptv.low_cmc_payoffs || []).slice(0, 4).map(name =>
          renderCardLink(name, { className: 'inline-card-link' })
        ).join(', ') || 'none'}
      </div>
    </div>
  `;

  // ── Coverage Grid ────────────────────────────────────────────────────
  const cats = (plan.coverage || {}).categories || {};
  const covEl = document.getElementById('plan-coverage');
  covEl.innerHTML = Object.entries(cats).map(([cat, d]) => {
    const pct = Math.min(d.pct, 100);
    const color = COVERAGE_COLORS[cat] || '#7c6af7';
    const deltaClass = d.status === 'ok' ? 'delta-ok' : (d.status === 'close' ? 'delta-close' : 'delta-low');
    const deltaSign = d.delta >= 0 ? '+' : '';
    return `
      <div class="coverage-card ${d.status}">
        <div class="coverage-header">
          <span class="coverage-name">${cat}</span>
          <span class="coverage-nums">${d.actual} / ${d.target}</span>
        </div>
        <div class="coverage-bar-bg">
          <div class="coverage-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="coverage-delta ${deltaClass}">${deltaSign}${d.delta} vs target</div>
      </div>
    `;
  }).join('');

  // ── Dual Bar Chart (CMC actual vs target) ────────────────────────────
  const curveEval = plan.curve_evaluation || {};
  const comparison = curveEval.comparison || {};
  const chartEl = document.getElementById('plan-curve-chart');
  const allBuckets = Object.keys(comparison);
  const maxVal = Math.max(...Object.values(comparison).flatMap(d => [d.actual, d.target]), 1);

  chartEl.innerHTML = allBuckets.map(label => {
    const d = comparison[label];
    const actH = Math.round((d.actual / maxVal) * 100);
    const tarH = Math.round((d.target / maxVal) * 100);
    return `
      <div class="dual-bar-wrap">
        <div class="bar-count" style="font-size:.65rem;color:var(--text3)">${d.actual}</div>
        <div class="dual-bars" style="height:${Math.max(actH,tarH)}%">
          <div class="bar-actual" style="height:${actH > 0 ? (actH/(Math.max(actH,tarH)||1))*100 : 2}%"></div>
          <div class="bar-target" style="height:${tarH > 0 ? (tarH/(Math.max(actH,tarH)||1))*100 : 2}%"></div>
        </div>
        <div class="bar-label">${label}</div>
      </div>
    `;
  }).join('');

  chartEl.insertAdjacentHTML('afterend', `
    <div class="dual-legend">
      <span><div class="legend-sq" style="background:var(--accent)"></div>Actual</span>
      <span><div class="legend-sq" style="background:var(--border)"></div>Target</span>
    </div>
  `);

  const curveNotes = document.getElementById('plan-curve-notes');
  curveNotes.innerHTML = (curveEval.notes || []).map(n =>
    `<div class="plan-note warn">${n}</div>`
  ).join('') || '<div class="plan-note">Curve looks balanced against the target.</div>';

  // ── Playtest Simulation ──────────────────────────────────────────────
  const pt = plan.playtest_simulation || {};
  const ptTableWrap = document.getElementById('plan-playtest-table');
  const ptCats = ['Lands', 'Ramp', 'Card Advantage', 'Removal', 'Plan Cards'];
  const oh = pt.opening_hand || {};
  const t5 = pt.by_turn_5 || {};
  const t7 = pt.by_turn_7 || {};

  ptTableWrap.innerHTML = `
    <table class="playtest-table">
      <thead>
        <tr>
          <th class="cat-col">Category</th>
          <th>In Deck</th>
          <th>Opening Hand (7)</th>
          <th>By Turn 5 (12)</th>
          <th>By Turn 7 (14)</th>
        </tr>
      </thead>
      <tbody>
        ${ptCats.map(cat => `
          <tr>
            <td class="cat-col">${cat}</td>
            <td>${(pt.category_counts || {})[cat] || 0}</td>
            <td>${oh[cat] || '0.0'}</td>
            <td>${t5[cat] || '0.0'}</td>
            <td>${t7[cat] || '0.0'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  const ptNotes = document.getElementById('plan-playtest-notes');
  ptNotes.innerHTML = (pt.assessments || []).map(a =>
    `<div class="plan-note">${linkKnownCardNames(a)}</div>`
  ).join('');

  // ── Mulligan Guide ───────────────────────────────────────────────────
  const mull = plan.mulligan_guide || {};
  const mullEl = document.getElementById('plan-mulligan');
  const idealHand = mull.ideal_hand_profile || [];
  const keepRules = idealHand.map(r => `<div class="keep-rule">✓ ${linkKnownCardNames(r)}</div>`).join('');
  const mullRules = (mull.mulligan_triggers || []).map(r => `<div class="mull-rule">✗ ${linkKnownCardNames(r)}</div>`).join('');

  mullEl.innerHTML = `
    <div class="mulligan-section">
      <div class="mulligan-label">Keep if you have</div>
      ${keepRules}
    </div>
    <div class="mulligan-section">
      <div class="mulligan-label">Mulligan when</div>
      ${mullRules}
    </div>
    <div class="mulligan-section">
      <div class="mulligan-label">Priority engine pieces</div>
      <div class="mulligan-hand">
        ${(mull.engine_pieces || []).map(n => renderCardLink(n, { className: 'hand-card' })).join('') || '<span style="color:var(--text3)">None detected</span>'}
      </div>
    </div>
  `;

  // ── Sequencing Guide ─────────────────────────────────────────────────
  const seq = plan.sequencing_guide || [];
  document.getElementById('plan-sequencing').innerHTML = seq.map(s => `
    <div class="seq-row">
      <div class="seq-turn">T${s.turn}</div>
      <div class="seq-content">
        <div class="seq-priority">${linkKnownCardNames(s.priority)}</div>
        <div class="seq-notes">${linkKnownCardNames(s.notes)}</div>
      </div>
    </div>
  `).join('');

  // ── Card Role Table ──────────────────────────────────────────────────
  renderCardRoleTable(plan.card_roles || [], data.cards || []);
}

let _allCardRoles = [];
let _allCardsForRoles = [];
let _cmcMapCache = {};
let _cardRoleCurrentView = [];
let _cardRoleCardMap = new Map();

function renderCardRoleTable(cardRoles, cards) {
  _allCardRoles = cardRoles;
  _allCardsForRoles = cards || [];
  _cardRoleCardMap = new Map();

  // Build a CMC lookup from the main cards array
  _cmcMapCache = {};
  _allCardsForRoles.forEach(c => {
    const name = c.name || c.raw_name;
    if (!name) return;
    _cmcMapCache[name] = c.cmc;
    _cardRoleCardMap.set(name.toLowerCase(), c);
  });

  filterCardRoleTable(_cmcMapCache);
}

function getFilteredCardRoleRows(cmcMap = {}) {
  const query = (document.getElementById('role-card-filter').value || '').toLowerCase();
  const catFilter = document.getElementById('role-cat-filter').value;

  // Attach cmc to each row for sorting, then sort
  const withCmc = _allCardRoles.map(cr => ({
    ...cr,
    cmc: cmcMap[cr.name] !== undefined ? cmcMap[cr.name] : (_cmcMapCache[cr.name] ?? ''),
  }));

  const filtered = sortArr(
    withCmc.filter(cr => {
      if (query && !cr.name.toLowerCase().includes(query)) return false;
      if (catFilter && !cr.roles.includes(catFilter)) return false;
      return true;
    }),
    _roleSort.col, _roleSort.dir
  );

  return filtered;
}

function filterCardRoleTable(cmcMap) {
  const filtered = getFilteredCardRoleRows(cmcMap);
  _cardRoleCurrentView = filtered;

  const tbody = document.getElementById('card-role-tbody');
  tbody.innerHTML = filtered.map(cr => {
    const roleTags = (cr.roles || []).map(r => {
      const cls = 'role-' + r.replace(/ /g, '-');
      return `<span class="role-tag ${cls}">${r}</span>`;
    }).join('');
    const subCat = cr.plan_subcategory
      ? `<span class="sub-${cr.plan_subcategory}">${cr.plan_subcategory}</span>`
      : '—';
    const overlapChip = cr.is_overlap
      ? `<span class="overlap-chip">overlap</span>`
      : '';
    const cmc = cr.cmc !== undefined && cr.cmc !== null ? cr.cmc : '—';
    return `<tr class="${cr.is_overlap ? 'overlap-row' : ''}">
      <td>${renderCardLink(cr.name)}</td>
      <td>${cmc}</td>
      <td>${roleTags}</td>
      <td>${subCat}</td>
      <td>${overlapChip}</td>
    </tr>`;
  }).join('');
}

document.getElementById('role-card-filter').addEventListener('input', () => filterCardRoleTable({}));
document.getElementById('role-cat-filter').addEventListener('change', () => filterCardRoleTable({}));

function decklistLineForRoleRow(row) {
  const card = _cardRoleCardMap.get(String(row.name || '').toLowerCase()) || {};
  const name = card.name || row.name;
  const quantity = Number.isFinite(Number(card.quantity)) ? Number(card.quantity) : 1;
  return {
    isCommander: Boolean(card.is_commander),
    line: `${quantity} ${name}`,
    commanderLine: `Commander: ${name}`,
  };
}

async function copyCardRoleView() {
  const rows = _cardRoleCurrentView.length ? _cardRoleCurrentView : getFilteredCardRoleRows(_cmcMapCache);
  if (!rows.length) {
    alert('No cards match the current Card Role Map filters.');
    return;
  }

  const lines = [];
  rows.map(decklistLineForRoleRow).forEach(item => {
    if (item.isCommander) lines.push(item.commanderLine);
    lines.push(item.line);
  });

  const text = `${lines.join('\n')}\n`;
  const btn = document.getElementById('role-export-btn');
  const originalText = btn.textContent;

  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = originalText; }, 1400);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand('copy');
    textarea.remove();

    if (!copied) {
      alert('Could not copy the current Card Role Map view to clipboard.');
      return;
    }

    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = originalText; }, 1400);
  }
}

document.getElementById('role-export-btn').addEventListener('click', copyCardRoleView);

// ── Validation Tab ────────────────────────────────────────────────────────────
function renderValidation(data) {
  const v = data.validation || {};
  const errors = v.errors || [];
  const warnings = v.warnings || [];

  const status = document.getElementById('validation-status');
  if (v.valid) {
    status.className = 'validation-status valid-ok';
    status.innerHTML = '✅ Deck is valid and Commander-legal.';
  } else {
    status.className = 'validation-status valid-fail';
    status.innerHTML = `❌ ${errors.length} error${errors.length !== 1 ? 's' : ''} found — deck may not be legal.`;
  }

  const el = document.getElementById('error-list');
  el.innerHTML = errors.length
    ? errors.map(e => `<li>${linkKnownCardNames(e)}</li>`).join('')
    : '<p class="empty-note">No errors. ✓</p>';

  const wl = document.getElementById('warning-list');
  wl.innerHTML = warnings.length
    ? warnings.map(w => `<li>${linkKnownCardNames(w)}</li>`).join('')
    : '<p class="empty-note">No warnings. ✓</p>';
}

// ── Synergy Tab ───────────────────────────────────────────────────────────────
function renderSynergy(data) {
  const clusters = data.synergy_clusters || [];
  const el = document.getElementById('synergy-clusters');
  el.innerHTML = clusters.length
    ? clusters.map(c => `
      <div class="cluster-card ${c.strength}">
        <div class="cluster-name">
          ${c.name} - ${c.cards.length} cards
          <span class="strength-badge strength-${c.strength}">${c.strength}</span>
        </div>
        <div class="cluster-desc">${c.description}</div>
        <div class="cluster-tags">${(c.cards || []).map(n => renderCardLink(n, { className: 'cluster-tag' })).join('')}</div>
      </div>
    `).join('')
    : '<p style="color:var(--text3);padding:20px">No strong synergy clusters detected.</p>';

  const staples = data.missing_staples || [];
  document.getElementById('missing-staples').innerHTML = staples.length
    ? staples.map(s => renderCardLink(s, { className: 'tag' })).join('')
    : '<span style="color:var(--text3);font-size:.85rem">None flagged — great staple coverage!</span>';
}

// ── Bracket Tab ───────────────────────────────────────────────────────────────
function renderBracket(data) {
  const b = data.bracket || {};
  const computed = b.bracket || 1;
  const el = document.getElementById('bracket-display');

  const labels = {
    1: 'Exhibition', 2: 'Core', 3: 'Upgraded', 4: 'Optimized', 5: 'cEDH'
  };

  el.innerHTML = [1,2,3,4,5].map(n => `
    <div class="bracket-box ${n === computed ? 'active' : ''}">
      <div class="bracket-num">${n}</div>
      <div class="bracket-label">${labels[n]}</div>
    </div>
  `).join('');

  if (b.reasoning && b.reasoning.length) {
    el.insertAdjacentHTML('afterend', `
      <div class="bracket-reasoning panel-inner">
        <h3>Analysis Reasoning</h3>
        ${b.reasoning.map(r => `<div class="reasoning-item">${linkKnownCardNames(r)}</div>`).join('')}
      </div>
    `);
  }

  const gcCards = b.game_changer_cards || [];
  document.getElementById('gc-list').innerHTML = gcCards.length
    ? gcCards.map(n => renderCardLink(n, { className: 'tag gc-tag', label: `★ ${n}` })).join('')
    : '<span style="color:var(--text3);font-size:.85rem">No game-changer cards found.</span>';
}

// ── AI Tab ────────────────────────────────────────────────────────────────────
function renderAI(data) {
  const el = document.getElementById('ai-content');
  const deckNames = new Set((data.cards || []).map(c => (c.name || '').toLowerCase()));
  const edhrec = data.edhrec || {};

  const edhrecHtml = buildEdhrecSection(edhrec, deckNames);

  const creativityHtml = renderCreativityScore(data);

  if (!data.ai_available && !data.ai_summary) {
    // AI skipped or API key not set — EDHREC is the primary recommendation
    const sug = data.ai_suggestions || [];
    el.innerHTML = `
      ${creativityHtml}
      ${edhrecHtml}
      ${!edhrec.available ? `
        <div class="panel-inner" style="margin-top:14px">
          <h3>EDHREC Recommendations</h3>
          <p style="color:var(--text2);font-size:.82rem">
            EDHREC data is unavailable for this commander right now${edhrec.error ? `: ${escapeHtml(edhrec.error)}` : '.'}
          </p>
        </div>
      ` : ''}
      ${sug.length ? `
        <div class="panel-inner" style="margin-top:14px">
          <h3>Rule-Based Suggestions</h3>
          <div class="suggestion-list">
            ${renderSuggestionList(sug)}
          </div>
        </div>
      ` : ''}
      ${!edhrec.available ? `
        <div class="ai-unavailable" style="margin-top:14px">
          <p>&#129302; AI advisor is offline.</p>
          <p style="margin-top:8px;font-size:.82rem">Set <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, or choose <code>Ollama</code> with a local model.</p>
        </div>
      ` : ''}
    `;
    initEdhrecSort();
    initCreativitySort();
    return;
  }

  const advisorCardNames = [...(edhrec.high_synergy_cards || []), ...(edhrec.top_cards || [])].map(c => c.name);
  el.innerHTML = `
    ${creativityHtml}
    <div class="advisor-sections">
      ${renderAdvisorSections(data, advisorCardNames)}
    </div>
    ${data.ai_full_response ? `
      <details style="margin-top:12px">
        <summary style="color:var(--text2);cursor:pointer;font-size:.82rem">Full AI response</summary>
        <pre style="background:var(--bg3);padding:14px;border-radius:6px;font-size:.78rem;white-space:pre-wrap;margin-top:8px">${escapeHtml(data.ai_full_response)}</pre>
      </details>
    ` : ''}
    ${edhrecHtml}
  `;
  initEdhrecSort();
  initCreativitySort();
}

const EDHREC_ROLE_ABBR = {
  'Lands': 'Land', 'Card Advantage': 'Card Adv', 'Ramp': 'Ramp',
  'Removal': 'Removal', 'Mass Disruption': 'Mass Dis', 'Plan Cards': 'Plan',
};

function renderEdhrecRows(cards, inDeck) {
  return cards.map(c => {
    const roleHtml = (c.plan_roles || []).map(r => {
      const cls = 'role-' + r.replace(/ /g, '-');
      return `<span class="role-tag ${cls}">${EDHREC_ROLE_ABBR[r] || r}</span>`;
    }).join('') || '<span style="color:var(--text3)">—</span>';
    return `
      <tr class="${inDeck ? 'edhrec-row-in-deck' : ''}">
        <td>${renderCardLink(c.name, { url: c.scryfall_uri || '' })}${inDeck ? ' <span class="edhrec-in-deck-badge">✓</span>' : ''}</td>
        <td class="edhrec-num">${c.synergy > 0 ? '+' : ''}${c.synergy}%</td>
        <td class="edhrec-num">${c.inclusion_pct}%</td>
        <td class="edhrec-num">${c.num_decks.toLocaleString()}</td>
        <td class="edhrec-num">${formatPrice(c.tcgplayer_price)}</td>
        <td>${roleHtml}</td>
        <td><span class="edhrec-source-${c.source === 'High Synergy' ? 'hs' : 'top'}">${c.source}</span></td>
      </tr>`;
  }).join('');
}

function _creativityCardRows(cards) {
  return cards.map(card => {
    const rawType = card.type_line || '';
    const shortType = rawType.split(' // ')[0].split(' — ')[0].trim() || '—';

    const roleHtml = (card.plan_roles || []).map(r => {
      const cls = 'role-' + r.replace(/ /g, '-');
      return `<span class="role-tag ${cls}">${EDHREC_ROLE_ABBR[r] || r}</span>`;
    }).join('') || '<span style="color:var(--text3)">—</span>';

    const subHtml = card.plan_subcategory
      ? `<span class="creativity-subcategory">${escapeHtml(card.plan_subcategory)}</span>`
      : '<span style="color:var(--text3)">—</span>';

    const cmc = card.cmc != null ? Number(card.cmc) : null;
    const cmcHtml = cmc != null ? String(Number.isInteger(cmc) ? cmc : cmc) : '—';
    const ciHtml  = (card.color_identity || []).map(colorPip).join('') || '<span style="color:var(--text3)">—</span>';

    return `
      <tr>
        <td>${renderCardLink(card.name, { url: card.scryfall_uri || '' })}</td>
        <td class="creativity-type">${escapeHtml(shortType)}</td>
        <td>${roleHtml}</td>
        <td>${subHtml}</td>
        <td class="creativity-num">${formatPrice(card.usd_price)}</td>
        <td class="creativity-num">${cmcHtml}</td>
        <td class="creativity-num">${ciHtml}</td>
      </tr>`;
  }).join('');
}

function renderCreativityScore(data) {
  const c = data.creativity;
  if (!c || c.score == null) return '';

  const score = c.score;
  const label = c.label || '';
  const colorVar = {
    'Brewer':     'var(--green)',
    'Innovative': 'var(--green)',
    'Refined':    'var(--yellow)',
    'Tuned':      'var(--yellow)',
    'Stock Build':'var(--red)',
  }[label] || 'var(--accent2)';

  const explanation = {
    'Brewer':     'Highly original — very few cards overlap with the average build.',
    'Innovative': 'Above average originality — many personal card choices.',
    'Refined':    'Balanced — a mix of conventional and original choices.',
    'Tuned':      'Conventional — most choices follow the EDHREC average build.',
    'Stock Build':'Very close to the average deck — almost no original card choices.',
  }[label] || '';

  _creativityUnique  = c.unique_to_user || [];
  _creativitySkipped = c.average_only   || [];

  const tableHeader = `
    <thead><tr>
      <th data-sort="name">Card</th>
      <th data-sort="type_line">Type</th>
      <th data-sort="plan_roles">Categories</th>
      <th data-sort="plan_subcategory">Plan Role</th>
      <th data-sort="usd_price">Price</th>
      <th data-sort="cmc">CMC</th>
      <th data-sort="color_identity">CI</th>
    </tr></thead>`;

  const sortedUnique  = sortArr(_creativityUnique,  _creativitySort.col, _creativitySort.dir);
  const sortedSkipped = sortArr(_creativitySkipped, _creativitySort.col, _creativitySort.dir);

  const uniqueContent = _creativityUnique.length
    ? `<div class="creativity-table-wrap"><table class="creativity-table" id="creativity-unique-table">${tableHeader}<tbody id="creativity-unique-tbody">${_creativityCardRows(sortedUnique)}</tbody></table></div>`
    : '<p style="color:var(--text3);font-size:.82rem;padding:10px 12px">None — deck closely follows the average build.</p>';

  const skippedContent = _creativitySkipped.length
    ? `<div class="creativity-table-wrap"><table class="creativity-table" id="creativity-skipped-table">${tableHeader}<tbody id="creativity-skipped-tbody">${_creativityCardRows(sortedSkipped)}</tbody></table></div>`
    : '<p style="color:var(--text3);font-size:.82rem;padding:10px 12px">You run all common average-deck staples.</p>';

  return `
    <div class="panel-inner creativity-panel">
      <h3>Creativity Score vs EDHREC Average Build${c.average_deck_url ? ` <a href="${escapeHtml(c.average_deck_url)}" target="_blank" rel="noopener" class="creativity-avg-link">View Average Deck ↗</a>` : ''}</h3>
      <div class="creativity-score-row">
        <div class="creativity-score-display" style="color:${colorVar}">${score}</div>
        <div class="creativity-score-meta">
          <div class="creativity-label" style="color:${colorVar}">${escapeHtml(label)}</div>
          <div class="creativity-explanation">${escapeHtml(explanation)}</div>
          <div class="creativity-overlap-note">
            ${c.overlap_count} card${c.overlap_count !== 1 ? 's' : ''} in common with the average build
            &nbsp;&middot;&nbsp; ${c.user_card_count} deck cards vs ${c.avg_card_count} average deck cards
          </div>
        </div>
      </div>
      <details class="creativity-details" style="margin-top:12px">
        <summary class="creativity-summary">Your Original Picks (${_creativityUnique.length})</summary>
        ${uniqueContent}
      </details>
      <details class="creativity-details" style="margin-top:8px">
        <summary class="creativity-summary">Average Staples You Skipped (${_creativitySkipped.length})</summary>
        ${skippedContent}
      </details>
    </div>
  `;
}

function buildEdhrecSection(edhrec, deckNames) {
  if (!edhrec.available) return '';

  const budget = getBudgetConfig();
  const maxCardPrice = budget?.max_card_price;

  const all = [...(edhrec.high_synergy_cards || []), ...(edhrec.top_cards || [])];
  const seen = new Set();
  const deduped = all.filter(c => { if (seen.has(c.name)) return false; seen.add(c.name); return true; });
  const withinBudget = card => maxCardPrice == null || card.tcgplayer_price == null || card.tcgplayer_price <= maxCardPrice;
  const hiddenForBudget = deduped.filter(card => !withinBudget(card)).length;
  const budgeted = deduped.filter(withinBudget);

  _edhrecMissing  = budgeted.filter(c => !deckNames.has(c.name.toLowerCase()));
  _edhrecIncluded = budgeted.filter(c =>  deckNames.has(c.name.toLowerCase()));

  const thRow = `<tr>
    <th data-sort="name">Card</th>
    <th data-sort="synergy">Synergy</th>
    <th data-sort="inclusion_pct">Inclusion</th>
    <th data-sort="num_decks">Decks</th>
    <th data-sort="tcgplayer_price">Price</th>
    <th data-sort="plan_roles">Roles</th>
    <th data-sort="source">Source</th>
  </tr>`;

  return `
    <div class="panel-inner edhrec-panel" style="margin-top:14px">
      <h3>
        &#9733; EDHREC Recommendations
        <a href="${edhrec.url}" target="_blank" class="edhrec-link">View on EDHREC ↗</a>
      </h3>
      ${budget ? `
        <div class="edhrec-budget-note">
          Budget target: ${escapeHtml(budget.label)}${budget.max_card_price != null ? ` (up to ${formatPrice(budget.max_card_price)} per card)` : ''}.
          ${hiddenForBudget ? `${hiddenForBudget} higher-priced EDHREC card${hiddenForBudget !== 1 ? 's were' : ' was'} hidden.` : 'No EDHREC cards were hidden by budget.'}
        </div>
      ` : ''}
      ${_edhrecMissing.length === 0 && _edhrecIncluded.length === 0
        ? `<p style="color:var(--text3);font-size:.83rem">${
            hiddenForBudget
              ? 'No EDHREC recommendations remain inside the selected budget.'
              : 'No EDHREC data available for this commander.'
          }</p>`
        : ''}
      ${_edhrecMissing.length ? `
        <div class="edhrec-subtitle">Cards not in your deck — consider adding</div>
        <div class="edhrec-table-wrap">
          <table class="edhrec-table" id="edhrec-missing-table">
            <thead>${thRow}</thead>
            <tbody id="edhrec-missing-tbody">${renderEdhrecRows(_edhrecMissing, false)}</tbody>
          </table>
        </div>
      ` : ''}
      ${_edhrecIncluded.length ? `
        <details style="margin-top:10px">
          <summary class="edhrec-already-have">You already run ${_edhrecIncluded.length} EDHREC-recommended card${_edhrecIncluded.length !== 1 ? 's' : ''} ▸</summary>
          <div class="edhrec-table-wrap" style="margin-top:8px">
            <table class="edhrec-table" id="edhrec-included-table">
              <thead>${thRow}</thead>
              <tbody id="edhrec-included-tbody">${renderEdhrecRows(_edhrecIncluded, true)}</tbody>
            </table>
          </div>
        </details>
      ` : ''}
    </div>`;
}

function initEdhrecSort() {
  const specs = [
    { tableId: 'edhrec-missing-table',  tbodyId: 'edhrec-missing-tbody',  inDeck: false },
    { tableId: 'edhrec-included-table', tbodyId: 'edhrec-included-tbody', inDeck: true  },
  ];
  const rerender = () => {
    specs.forEach(({ tableId, tbodyId, inDeck }) => {
      const tbody = document.getElementById(tbodyId);
      if (!tbody) return;
      const arr = inDeck ? _edhrecIncluded : _edhrecMissing;
      tbody.innerHTML = renderEdhrecRows(sortArr(arr, _edhrecSort.col, _edhrecSort.dir), inDeck);
      const tbl = document.getElementById(tableId);
      if (tbl) updateSortIndicators(tbl, _edhrecSort.col, _edhrecSort.dir);
    });
  };
  specs.forEach(({ tableId }) => {
    const tbl = document.getElementById(tableId);
    if (tbl) initTableSort(tbl, _edhrecSort, rerender);
  });
}

function initCreativitySort() {
  const specs = [
    { tableId: 'creativity-unique-table',  tbodyId: 'creativity-unique-tbody',  arr: () => _creativityUnique  },
    { tableId: 'creativity-skipped-table', tbodyId: 'creativity-skipped-tbody', arr: () => _creativitySkipped },
  ];
  const rerender = () => {
    specs.forEach(({ tableId, tbodyId, arr }) => {
      const tbody = document.getElementById(tbodyId);
      if (!tbody) return;
      tbody.innerHTML = _creativityCardRows(sortArr(arr(), _creativitySort.col, _creativitySort.dir));
      const tbl = document.getElementById(tableId);
      if (tbl) updateSortIndicators(tbl, _creativitySort.col, _creativitySort.dir);
    });
  };
  specs.forEach(({ tableId }) => {
    const tbl = document.getElementById(tableId);
    if (tbl) initTableSort(tbl, _creativitySort, rerender);
  });
}

// ── Card List Tab ─────────────────────────────────────────────────────────────
function renderCardList(cards) {
  allCards = cards;
  filterCards();
}

function filterCards() {
  const query = (document.getElementById('card-filter').value || '').toLowerCase();
  const typeFilter = document.getElementById('type-filter').value;
  const tbody = document.getElementById('card-tbody');

  const filtered = sortArr(
    allCards.filter(c => {
      const name = (c.name || c.raw_name || '').toLowerCase();
      const type = c.type_line || '';
      if (query && !name.includes(query)) return false;
      if (typeFilter && !type.includes(typeFilter)) return false;
      return true;
    }),
    _cardSort.col, _cardSort.dir
  );

  tbody.innerHTML = filtered.map(c => {
    if (!c.found) {
      return `<tr class="not-found-row">
        <td>${c.quantity}</td>
        <td colspan="7">⚠ ${c.raw_name} — not found in database</td>
      </tr>`;
    }
    const ci = (c.color_identity || []).map(colorPip).join('');
    const pt = (c.power && c.toughness) ? `${c.power}/${c.toughness}` : (c.defense ? `[${c.defense}]` : '—');
    const rarityClass = { common:'rarity-c', uncommon:'rarity-u', rare:'rarity-r', mythic:'rarity-m' }[c.rarity] || '';
    const link = c.scryfall_uri
      ? `<a class="card-name-link" href="${c.scryfall_uri}" target="_blank">${c.name}</a>`
      : c.name;
    return `<tr>
      <td>${c.quantity}</td>
      <td>${link} ${c.is_commander ? '👑' : ''}</td>
      <td>${c.type_line || '—'}</td>
      <td>${c.cmc !== null && c.cmc !== undefined ? c.cmc : '—'}</td>
      <td>${ci || '—'}</td>
      <td>${pt}</td>
      <td class="${rarityClass}">${(c.rarity || '').charAt(0).toUpperCase()}</td>
      <td>${c.game_changer ? '<span class="gc-dot">★</span>' : ''}</td>
    </tr>`;
  }).join('');
}

document.getElementById('card-filter').addEventListener('input', filterCards);
document.getElementById('type-filter').addEventListener('change', filterCards);

// ── Tab switching ─────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.add('hidden'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    document.getElementById(`tab-${tab}`).classList.remove('hidden');
  });
});

// ── Init ──────────────────────────────────────────────────────────────────────
checkIndexStatus();
loadCommanderRoleCatalog();

// Sortable static tables
const _cardTableEl = document.getElementById('card-table');
if (_cardTableEl) initTableSort(_cardTableEl, _cardSort, filterCards);
const _roleTableEl = document.getElementById('card-role-table');
if (_roleTableEl) initTableSort(_roleTableEl, _roleSort, () => filterCardRoleTable(_cmcMapCache));
