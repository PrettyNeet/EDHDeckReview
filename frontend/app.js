/* MTG Commander Deck Review — frontend app */

// ── State ─────────────────────────────────────────────────────────────────────
let currentAnalysis = null;
let allCards = [];
let _targetCommanderRoles = [];
let _detectedCommanderRoleNames = new Set();
let _commanderRoleCatalog = { themes: [], typals: [] };
let _commanderRoleByName = new Map();
let _appConfig = { auth_enabled: false, data_updates_enabled: true };
let _supabaseClient = null;
let _session = null;
let _authMode = 'sign-in';
let _statusTimer = null;
let _confirmResolve = null;

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
const MAX_DECKLIST_FILE_BYTES = 512 * 1024;
const ALLOWED_DECKLIST_MIME_TYPES = new Set(['', 'text/plain', 'text/markdown', 'application/octet-stream']);

function showAppStatus(message, kind = '', { persist = false } = {}) {
  const el = document.getElementById('app-status');
  if (!el) return;
  if (_statusTimer) {
    clearTimeout(_statusTimer);
    _statusTimer = null;
  }
  el.textContent = message || '';
  el.className = `app-status ${kind}`.trim();
  el.classList.toggle('hidden', !message);
  if (message && !persist) {
    _statusTimer = setTimeout(() => el.classList.add('hidden'), 4200);
  }
}

function showMoxfieldStatus(message, kind = '') {
  const el = document.getElementById('moxfield-status');
  if (!el) return;
  el.className = `moxfield-status ${kind ? `moxfield-${kind}` : ''}`.trim();
  el.textContent = message || '';
  el.classList.toggle('hidden', !message);
}

function requestConfirm({ title = 'Confirm Action', message = '', confirmText = 'Continue' } = {}) {
  const overlay = document.getElementById('confirm-overlay');
  const titleEl = document.getElementById('confirm-title');
  const messageEl = document.getElementById('confirm-message');
  const okBtn = document.getElementById('confirm-ok-btn');
  const cancelBtn = document.getElementById('confirm-cancel-btn');
  if (!overlay || !okBtn || !cancelBtn) return Promise.resolve(false);

  titleEl.textContent = title;
  messageEl.textContent = message;
  okBtn.textContent = confirmText;
  overlay.classList.remove('hidden');
  okBtn.focus();

  return new Promise(resolve => {
    _confirmResolve = value => {
      overlay.classList.add('hidden');
      _confirmResolve = null;
      resolve(value);
    };
  });
}

function updateInputReadiness() {
  const status = document.getElementById('input-status');
  if (!status) return;

  const hasDeck = Boolean(document.getElementById('paste-input')?.value.trim() || selectedFile);
  const indexReady = !document.getElementById('submit-btn')?.disabled;
  const bracket = document.getElementById('bracket-select')?.value || 'Auto';
  const budget = document.getElementById('budget-tier-select')?.selectedOptions?.[0]?.textContent || 'No limit';
  const aiEnabled = featureEnabled('ai_review');
  const skipAi = document.getElementById('skip-ai-check')?.checked;
  const aiState = aiEnabled ? (skipAi ? 'AI skipped' : 'AI enabled') : 'AI disabled';

  status.innerHTML = `
    <span class="readiness-chip ${hasDeck ? 'ok' : 'warn'}">${hasDeck ? 'Decklist ready' : 'Decklist needed'}</span>
    <span class="readiness-chip ${indexReady ? 'ok' : 'warn'}">${indexReady ? 'Index ready' : 'Index checking'}</span>
    <span class="readiness-chip">Bracket: ${escapeHtml(bracket)}</span>
    <span class="readiness-chip">Budget: ${escapeHtml(budget)}</span>
    <span class="readiness-chip">${escapeHtml(aiState)}</span>
  `;
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (_session?.access_token) {
    headers.set('Authorization', `Bearer ${_session.access_token}`);
  }
  return fetch(url, { ...options, headers });
}

function setAuthStatus(message, kind = '') {
  const el = document.getElementById('auth-status');
  if (!el) return;
  el.textContent = message || '';
  el.className = `auth-status ${kind}`.trim();
}

function setAuthMode(mode) {
  _authMode = mode;
  const title = document.getElementById('auth-title');
  const note = document.getElementById('auth-note');
  const email = document.getElementById('auth-email');
  const password = document.getElementById('auth-password');
  const confirmWrap = document.getElementById('auth-confirm-wrap');
  const confirm = document.getElementById('auth-password-confirm');
  const submit = document.getElementById('auth-submit-btn');
  const secondary = document.getElementById('auth-secondary-btn');
  const reset = document.getElementById('auth-reset-btn');
  const back = document.getElementById('auth-back-btn');

  const recovery = mode === 'recovery';
  const signUp = mode === 'sign-up';
  const resetRequest = mode === 'reset-request';

  title.textContent = recovery ? 'Set New Password' : (signUp ? 'Create Account' : (resetRequest ? 'Reset Password' : 'Sign In'));
  note.textContent = recovery
    ? 'Enter a new password for your invited account.'
    : signUp
      ? 'Create a Supabase login using your whitelisted email.'
      : resetRequest
        ? 'Enter your email and we will send a password reset link.'
        : 'Use the email and password for your invited account.';

  email.classList.toggle('hidden', recovery);
  email.previousElementSibling.classList.toggle('hidden', recovery);
  password.classList.toggle('hidden', resetRequest);
  password.previousElementSibling.classList.toggle('hidden', resetRequest);
  confirmWrap.classList.toggle('hidden', !(signUp || recovery));
  confirm.required = signUp || recovery;
  password.required = !resetRequest;
  password.autocomplete = signUp || recovery ? 'new-password' : 'current-password';

  submit.textContent = recovery ? 'Update Password' : (signUp ? 'Create Account' : (resetRequest ? 'Send Reset Link' : 'Sign In'));
  secondary.textContent = signUp ? 'I Have an Account' : 'Create Account';
  secondary.classList.toggle('hidden', recovery || resetRequest);
  reset.classList.toggle('hidden', signUp || recovery || resetRequest);
  back.classList.toggle('hidden', mode === 'sign-in');
  setAuthStatus('');
}

function getAuthFormValues() {
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const confirm = document.getElementById('auth-password-confirm').value;
  return { email, password, confirm };
}

function validateNewPassword(password, confirm) {
  if (password.length < 6) {
    setAuthStatus('Password must be at least 6 characters.', 'error');
    return false;
  }
  if (password !== confirm) {
    setAuthStatus('Passwords do not match.', 'error');
    return false;
  }
  return true;
}

function updateAuthShell() {
  const authPanel = document.getElementById('auth-panel');
  const appShell = document.getElementById('app-shell');
  const userBadge = document.getElementById('auth-user-badge');
  const signOutBtn = document.getElementById('sign-out-btn');
  const hasAccess = !_appConfig.auth_enabled || Boolean(_session?.access_token);

  authPanel.classList.toggle('hidden', hasAccess);
  appShell.classList.toggle('hidden', !hasAccess);
  userBadge.classList.toggle('hidden', !hasAccess || !_session?.user?.email);
  signOutBtn.classList.toggle('hidden', !hasAccess || !_appConfig.auth_enabled);

  if (_session?.user?.email) {
    userBadge.textContent = _session.user.email;
    userBadge.className = 'badge badge-ready';
  }
}

function featureEnabled(name) {
  return Boolean(_appConfig.features?.[name]);
}

function applyFeatureFlags() {
  const aiEnabled = featureEnabled('ai_review');
  document.querySelectorAll('.ai-feature').forEach(el => {
    el.classList.toggle('hidden', !aiEnabled);
  });
  updateInputReadiness();
}

async function loadAppConfig() {
  const r = await fetch('/api/config');
  _appConfig = await r.json();
  applyFeatureFlags();
}

async function initAuth() {
  await loadAppConfig();

  if (!_appConfig.data_updates_enabled) {
    document.getElementById('update-data-btn')?.classList.add('hidden');
  }

  if (!_appConfig.auth_enabled) {
    updateAuthShell();
    await startAuthenticatedApp();
    return;
  }

  if (!window.supabase?.createClient || !_appConfig.supabase_url || !_appConfig.supabase_anon_key) {
    setAuthStatus('Authentication is configured incorrectly. Missing Supabase public config.', 'error');
    document.getElementById('auth-panel').classList.remove('hidden');
    return;
  }

  _supabaseClient = window.supabase.createClient(_appConfig.supabase_url, _appConfig.supabase_anon_key);
  const { data } = await _supabaseClient.auth.getSession();
  _session = data.session;
  if (window.location.hash.includes('type=recovery')) {
    setAuthMode('recovery');
  } else {
    setAuthMode('sign-in');
  }
  updateAuthShell();

  _supabaseClient.auth.onAuthStateChange((_event, session) => {
    _session = session;
    updateAuthShell();
    if (_event === 'PASSWORD_RECOVERY') {
      setAuthMode('recovery');
      document.getElementById('auth-panel').classList.remove('hidden');
      document.getElementById('app-shell').classList.add('hidden');
      return;
    }
    if (session) startAuthenticatedApp();
  });

  if (_session) await startAuthenticatedApp();
}

async function startAuthenticatedApp() {
  if (startAuthenticatedApp.started) return;
  startAuthenticatedApp.started = true;
  await checkIndexStatus();
  const allowed = await loadCommanderRoleCatalog();
  if (allowed === false) {
    startAuthenticatedApp.started = false;
    document.getElementById('app-shell').classList.add('hidden');
    document.getElementById('auth-panel').classList.remove('hidden');
    setAuthStatus('This account is not invited to use this app.', 'error');
  }
}

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
  Creatures: '#c8a44a', Instants: '#60a5fa', Sorceries: '#e4c068',
  Artifacts: '#94a3b8', Enchantments: '#4ade80', Planeswalkers: '#fb923c', Lands: '#78716c',
};
const ROLE_COLORS = {
  ramp: '#4ade80', draw: '#60a5fa', removal: '#f87171', boardwipes: '#fb923c',
  tutors: '#e4c068', threats: '#fbbf24', synergy: '#c8a44a', lands: '#78716c',
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
    const r = await apiFetch('/api/commander-roles');
    if (r.status === 401 || r.status === 403) return false;
    if (!r.ok) return true;
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
  return true;
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

  const allRoles = getTargetCommanderRoles();
  const roles = allRoles.filter(r => !_detectedCommanderRoleNames.has(r.toLowerCase()));
  el.innerHTML = roles.length // eslint-disable-line -- content is escapeHtml-sanitized below
    ? roles.map((role, index) => {
        const meta = getCommanderRoleMeta(role);
        const kind = meta?.kind === 'typal' ? 'Typal' : (meta?.kind === 'theme' ? 'Theme' : 'Custom');
        const description = meta?.description || `Builds around ${role} synergies as the deck's main plan.`;
        return `
        <div class="editable-role-tag">
          <div class="role-tag-main">
            <span>${escapeHtml(role)}</span>
            <span class="role-kind">${kind}</span>
            <button type="button" class="role-remove-btn" data-role-name="${escapeHtml(role)}" aria-label="Remove ${escapeHtml(role)}">&times;</button>
          </div>
          <div class="role-tag-description">${escapeHtml(description)}</div>
        </div>
      `;
      }).join('')
    : '<span class="soft-empty">No custom roles added.</span>';

  el.querySelectorAll('.role-remove-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.roleName.toLowerCase();
      const idx = _targetCommanderRoles.findIndex(r => r.toLowerCase() === name);
      if (idx !== -1) _targetCommanderRoles.splice(idx, 1);
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
      document.getElementById('skip-ai-check').checked = !featureEnabled('ai_review');
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
    } else if (!_appConfig.data_updates_enabled) {
      indexBadge.textContent = 'Index: missing';
      indexBadge.className   = 'badge badge-error';
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
    if (_appConfig.data_updates_enabled) btn.classList.remove('hidden');
    btn.classList.add('stale');
    return;
  }

  const age   = bulk.age_human || '?';
  const stale = bulk.is_stale;
  const aging = (bulk.age_hours || 0) > 12;   // warn after 12 h, stale after 24 h

  if (stale) {
    badge.textContent = `Data: ${age} — STALE`;
    badge.className   = 'badge badge-stale';
    if (_appConfig.data_updates_enabled) btn.classList.remove('hidden');
    btn.classList.add('stale');
    btn.title = 'Scryfall data is over 24 hours old — click to download the latest';
  } else if (aging) {
    badge.textContent = `Data: ${age}`;
    badge.className   = 'badge badge-aging';
    if (_appConfig.data_updates_enabled) btn.classList.remove('hidden');
    btn.classList.remove('stale');
    btn.title = `Data is ${age} old — update recommended before 24h`;
  } else {
    badge.textContent = `Data: ${age}`;
    badge.className   = 'badge badge-ready';
    if (_appConfig.data_updates_enabled) btn.classList.remove('hidden', 'stale');   // still show it, just neutral
    btn.title = `Bulk data is ${age} old (fresh)`;
  }
}

async function buildIndex() {
  if (!_appConfig.data_updates_enabled) return;
  const badge = document.getElementById('index-status');
  badge.textContent = 'Index: building (~30s)…';
  badge.className   = 'badge badge-building';
  try {
    const r    = await apiFetch('/api/index/build', { method: 'POST' });
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
  updateInputReadiness();
}

// ── Data update flow ──────────────────────────────────────────────────────────
let _pollInterval = null;

document.getElementById('update-data-btn').addEventListener('click', async () => {
  if (!_appConfig.data_updates_enabled) return;
  const confirmed = await requestConfirm({
    title: 'Update Scryfall Data',
    message: 'This downloads the latest Scryfall card database, about 500 MB, and rebuilds the card index. The server remains usable during the download.',
    confirmText: 'Update Data',
  });
  if (!confirmed) return;

  try {
    const r = await apiFetch('/api/bulk-data/update', { method: 'POST' });
    if (!r.ok) {
      const err = await r.json();
      showAppStatus(`Could not start update: ${err.detail || r.statusText}`, 'error', { persist: true });
      return;
    }
    showDownloadOverlay();
    startPollingProgress();
  } catch (e) {
    showAppStatus(`Network error: ${e.message}`, 'error', { persist: true });
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
      const r    = await apiFetch('/api/bulk-data/progress');
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
  if (!url) {
    showMoxfieldStatus('Paste a Moxfield deck URL first.', 'err');
    return;
  }

  const btn = document.getElementById('moxfield-import-btn');
  btn.disabled = true;
  btn.textContent = 'Importing…';
  showMoxfieldStatus('');

  try {
    const r = await apiFetch(`/api/moxfield?url=${encodeURIComponent(url)}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);

    document.getElementById('paste-input').value = data.text || '';
    if (data.commander) {
      document.getElementById('commander-input').value = data.commander;
    }
    updateInputReadiness();
    showMoxfieldStatus(`Imported: ${data.deck_name || 'deck'}`, 'ok');
  } catch (err) {
    showMoxfieldStatus(`Import failed: ${err.message}`, 'err');
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

function resetDropZone() {
  dropZone.innerHTML = `
    <div class="drop-icon">&#128196;</div>
    <p>Drag &amp; drop your <code>.txt</code> decklist here</p>
    <p>or <label for="file-input" class="link-label">click to browse</label></p>
  `;
}

function validateDeckFile(file) {
  const name = file.name || '';
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : '';
  const type = String(file.type || '').split(';', 1)[0].toLowerCase();

  if (ext !== '.txt') return 'Please upload a .txt decklist file.';
  if (!ALLOWED_DECKLIST_MIME_TYPES.has(type)) return 'Please upload a plain text decklist file.';
  if (file.size <= 0) return 'The selected file is empty.';
  if (file.size > MAX_DECKLIST_FILE_BYTES) return 'Decklist files must be under 512 KB.';
  return '';
}

function handleFile(f) {
  const validationError = validateDeckFile(f);
  if (validationError) {
    selectedFile = null;
    fileInput.value = '';
    resetDropZone();
    showAppStatus(validationError, 'error', { persist: true });
    updateInputReadiness();
    return;
  }

  selectedFile = f;
  dropZone.innerHTML = `<div class="drop-icon">OK</div><p><strong>${escapeHtml(f.name)}</strong> selected (${(f.size/1024).toFixed(1)} KB)</p>`;
  showAppStatus(`${f.name} selected. Decklist preview loaded below.`, 'ok');
  updateInputReadiness();
  // Also read text into paste area for preview
  const reader = new FileReader();
  reader.onload = e => {
    const value = String(e.target.result || '');
    if (value.includes('\u0000')) {
      selectedFile = null;
      fileInput.value = '';
      resetDropZone();
      showAppStatus('The selected file does not look like plain text.', 'error', { persist: true });
      updateInputReadiness();
      return;
    }
    document.getElementById('paste-input').value = value;
    updateInputReadiness();
  };
  reader.onerror = () => {
    selectedFile = null;
    fileInput.value = '';
    resetDropZone();
    showAppStatus('Could not read the selected file.', 'error', { persist: true });
    updateInputReadiness();
  };
  reader.readAsText(f);
}

function showUploadPanel({ clearResults = false } = {}) {
  document.getElementById('loading-panel').classList.add('hidden');
  document.getElementById('results-panel').classList.add('hidden');
  document.getElementById('upload-panel').classList.remove('hidden');
  showAppStatus('');
  if (clearResults) {
    currentAnalysis = null;
    allCards = [];
    updateTabBadges({});
    document.getElementById('result-summary').innerHTML = '';
    document.getElementById('commander-header').innerHTML = '';
  }
  updateInputReadiness();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.getElementById('new-review-btn')?.addEventListener('click', () => showUploadPanel({ clearResults: true }));

// ── Submit ────────────────────────────────────────────────────────────────────
document.getElementById('submit-btn').addEventListener('click', submitDeck);

async function submitDeck() {
  const text = document.getElementById('paste-input').value.trim();
  const commander = document.getElementById('commander-input').value.trim();
  const bracket = getActiveBracketValue();
  const budgetTier = document.getElementById('budget-tier-select').value;
  const aiEnabled = featureEnabled('ai_review');
  const aiProvider = aiEnabled ? document.getElementById('ai-provider-select').value : '';
  const aiModel = aiEnabled ? document.getElementById('ai-model-input').value.trim() : '';
  const skipAi = aiEnabled ? document.getElementById('skip-ai-check').checked : true;
  const targetRoles = getTargetCommanderRoles();
  const hasTargetRoleEditor = Boolean(document.getElementById('target-role-tags'));

  if (!text && !selectedFile) {
    showAppStatus('Provide a decklist by pasting text, importing from Moxfield, or selecting a .txt file.', 'error', { persist: true });
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
    const r = await apiFetch('/api/review', { method: 'POST', body: fd });
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
    showAppStatus(`Review failed: ${err.message}`, 'error', { persist: true });
  }
}

function showLoading(msg) {
  document.getElementById('upload-panel').classList.add('hidden');
  document.getElementById('loading-panel').classList.remove('hidden');
  document.getElementById('results-panel').classList.add('hidden');
  document.getElementById('loading-msg').textContent = msg;
}

function hideLoading() {
  showUploadPanel();
}

// ── Render Results ────────────────────────────────────────────────────────────
function renderResults(data) {
  document.getElementById('loading-panel').classList.add('hidden');
  document.getElementById('results-panel').classList.remove('hidden');
  showAppStatus('');
  setActiveTab('overview', { focus: false });

  renderCommanderHeader(data);
  renderResultSummary(data);
  renderOverview(data);
  renderPlan(data);
  renderValidation(data);
  renderSynergy(data);
  renderBracket(data);
  renderAI(data);
  renderCardList(data.cards || []);
  updateTabBadges(data);
}

function countEdhrecRecommendations(data) {
  const deckNames = new Set((data.cards || []).map(c => (c.name || '').toLowerCase()));
  const edhrec = data.edhrec || {};
  const all = [...(edhrec.high_synergy_cards || []), ...(edhrec.top_cards || [])];
  const seen = new Set();
  return all.filter(card => {
    const key = String(card.name || '').toLowerCase();
    if (!key || seen.has(key) || deckNames.has(key)) return false;
    seen.add(key);
    return true;
  }).length;
}

function getTopCoverageGap(data) {
  const categories = data.plan?.coverage?.categories || {};
  const lows = Object.entries(categories)
    .filter(([, details]) => Number(details.delta || 0) < 0)
    .sort(([, a], [, b]) => Number(a.delta || 0) - Number(b.delta || 0));
  if (!lows.length) return { label: 'Coverage', value: 'Targets met', kind: 'ok' };
  const [name, details] = lows[0];
  return { label: 'Top Gap', value: `${name} ${details.delta}`, kind: details.status === 'close' ? 'warn' : 'error' };
}

function renderResultSummary(data) {
  const el = document.getElementById('result-summary');
  if (!el) return;
  const validation = data.validation || {};
  const errors = validation.errors || [];
  const warnings = [...(validation.warnings || []), ...(data.synergy_warnings || [])];
  const bracket = data.bracket?.bracket ? `Bracket ${data.bracket.bracket}` : 'Unknown';
  const recCount = countEdhrecRecommendations(data);
  const gap = getTopCoverageGap(data);
  const aiEnabled = Boolean(data.features?.ai_review ?? featureEnabled('ai_review'));
  const advisor = data.ai_available ? 'AI ready' : (aiEnabled ? 'Rule/EDHREC only' : 'AI disabled');
  const items = [
    { label: 'Legality', value: validation.valid ? 'Commander legal' : `${errors.length} error${errors.length !== 1 ? 's' : ''}`, kind: validation.valid ? 'ok' : 'error' },
    { label: 'Deck Size', value: `${data.card_count || 0} cards`, kind: (data.card_count === 100 ? 'ok' : 'warn') },
    { label: 'Power', value: bracket, kind: 'accent' },
    gap,
    { label: 'Warnings', value: `${warnings.length} flagged`, kind: warnings.length ? 'warn' : 'ok' },
    { label: 'Analysis', value: `${recCount} EDHREC adds · ${advisor}`, kind: recCount ? 'accent' : 'ok' },
  ];

  el.innerHTML = items.map(item => `
    <div class="summary-item ${item.kind || ''}">
      <div class="summary-label">${escapeHtml(item.label)}</div>
      <div class="summary-value">${escapeHtml(item.value)}</div>
    </div>
  `).join('');
}

function updateTabBadge(tab, value) {
  const btn = document.querySelector(`.tab-btn[data-tab="${tab}"]`);
  const badge = btn?.querySelector('.tab-badge');
  if (!badge) return;
  const show = value != null && value !== '' && Number(value) !== 0;
  badge.textContent = show ? String(value) : '';
  badge.classList.toggle('hidden', !show);
}

function updateTabBadges(data) {
  const validation = data.validation || {};
  const issueCount = (validation.errors || []).length + (validation.warnings || []).length;
  updateTabBadge('validation', issueCount);
  updateTabBadge('synergy', (data.synergy_clusters || []).length);
  updateTabBadge('bracket', (data.bracket?.game_changer_cards || []).length);
  updateTabBadge('ai', countEdhrecRecommendations(data) + ((data.ai_suggestions || []).length));
  updateTabBadge('cards', (data.cards || []).length);
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
    ? ` <span class="muted-inline">+</span> ${renderCardLink(data.partner, { className: 'commander-name-link' })}`
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
  document.getElementById('stat-colors').innerHTML = ci || '<span class="soft-empty">Colorless</span>';

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
    wp.classList.remove('hidden');
  } else {
    wp.classList.add('hidden');
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
    const color = ROLE_COLORS[role] || '#c8a44a';
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
  'Plan Cards':      '#c8a44a',
};

function renderPlan(data) {
  const plan = data.plan || {};

  // ── Commander Role ───────────────────────────────────────────────────
  const roles = plan.commander_roles || [];
  const detectedRoles = plan.detected_commander_roles || [];
  const detectedMatches = plan.detected_commander_role_matches || [];
  const roleSource = plan.commander_roles_source || 'detected';
  _targetCommanderRoles = [...roles.filter(Boolean)];
  _detectedCommanderRoleNames = new Set(detectedMatches.map(m => m.name.toLowerCase()));
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
              <div class="detected-role-head-right">
                <span>${escapeHtml(kind)} · ${escapeHtml(confidence)}</span>
                <button type="button" class="detected-role-remove-btn" data-role-name="${escapeHtml(match.name)}" aria-label="Remove ${escapeHtml(match.name)}">&times;</button>
              </div>
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
  document.getElementById('plan-cmd-roles')
    .querySelectorAll('.detected-role-remove-btn')
    .forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const roleName = btn.dataset.roleName;
        const idx = _targetCommanderRoles.findIndex(r => r.toLowerCase() === roleName.toLowerCase());
        if (idx !== -1) {
          _targetCommanderRoles.splice(idx, 1);
          renderTargetRoleTags();
        }
        btn.closest('.detected-role-item').classList.add('detected-role-removed');
        btn.disabled = true;
      });
    });
  const _focusRaw = plan.commander_focus_advice || {};
  const _focusText  = typeof _focusRaw === 'string' ? _focusRaw : (_focusRaw.text || '');
  const _focusCards = typeof _focusRaw === 'object' && !Array.isArray(_focusRaw)
    ? (_focusRaw.suggested_cards || []) : [];
  document.getElementById('plan-focus-advice').textContent = _focusText;
  document.getElementById('plan-focus-cards').innerHTML = _focusCards.length
    ? _focusCards.map(c =>
        `<a class="tag focus-card-link" href="${escapeHtml(c.url || getCardUrl(c.name))}" target="_blank" rel="noopener">${escapeHtml(c.name)} ↗</a>`
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
    const color = COVERAGE_COLORS[cat] || '#c8a44a';
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
        <div class="bar-count muted-count">${d.actual}</div>
        <div class="dual-bars" style="height:${Math.max(actH,tarH)}%">
          <div class="bar-actual" style="height:${actH > 0 ? (actH/(Math.max(actH,tarH)||1))*100 : 2}%"></div>
          <div class="bar-target" style="height:${tarH > 0 ? (tarH/(Math.max(actH,tarH)||1))*100 : 2}%"></div>
        </div>
        <div class="bar-label">${label}</div>
      </div>
    `;
  }).join('');

  chartEl.parentElement.querySelector('.dual-legend')?.remove();
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
        ${(mull.engine_pieces || []).map(n => renderCardLink(n, { className: 'hand-card' })).join('') || '<span class="soft-empty">None detected</span>'}
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
    showAppStatus('No cards match the current Card Role Map filters.', 'warn');
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
    showAppStatus('Current Card Role Map view copied to clipboard.', 'ok');
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
      showAppStatus('Could not copy the current Card Role Map view to clipboard.', 'error', { persist: true });
      return;
    }

    btn.textContent = 'Copied';
    showAppStatus('Current Card Role Map view copied to clipboard.', 'ok');
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
    status.textContent = 'Deck is valid and Commander-legal.';
  } else {
    status.className = 'validation-status valid-fail';
    status.textContent = `${errors.length} error${errors.length !== 1 ? 's' : ''} found. Deck may not be legal.`;
  }

  const el = document.getElementById('error-list');
  el.innerHTML = errors.length
    ? errors.map(e => `<li>${linkKnownCardNames(e)}</li>`).join('')
    : '<p class="empty-note">No errors.</p>';

  const wl = document.getElementById('warning-list');
  wl.innerHTML = warnings.length
    ? warnings.map(w => `<li>${linkKnownCardNames(w)}</li>`).join('')
    : '<p class="empty-note">No warnings.</p>';
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
    : '<p class="soft-empty-block">No strong synergy clusters detected.</p>';

  const staples = data.missing_staples || [];
  document.getElementById('missing-staples').innerHTML = staples.length
    ? staples.map(s => renderCardLink(s, { className: 'tag' })).join('')
    : '<span class="soft-empty">None flagged. Staple coverage looks good.</span>';
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

  const reasoningWrap = document.getElementById('bracket-reasoning');
  const reasoningList = document.getElementById('bracket-reasoning-list');
  if (b.reasoning && b.reasoning.length) {
    reasoningList.innerHTML = b.reasoning.map(r => `<div class="reasoning-item">${linkKnownCardNames(r)}</div>`).join('');
    reasoningWrap.classList.remove('hidden');
  } else {
    reasoningList.innerHTML = '';
    reasoningWrap.classList.add('hidden');
  }

  const gcCards = b.game_changer_cards || [];
  document.getElementById('gc-list').innerHTML = gcCards.length
    ? gcCards.map(n => renderCardLink(n, { className: 'tag gc-tag', label: `★ ${n}` })).join('')
    : '<span class="soft-empty">No game-changer cards found.</span>';
}

// ── AI Tab ────────────────────────────────────────────────────────────────────
function renderAI(data) {
  const el = document.getElementById('ai-content');
  const deckNames = new Set((data.cards || []).map(c => (c.name || '').toLowerCase()));
  const edhrec = data.edhrec || {};
  const aiEnabled = Boolean(data.features?.ai_review ?? featureEnabled('ai_review'));

  const edhrecHtml = buildEdhrecSection(edhrec, deckNames);

  const creativityHtml = renderCreativityScore(data);

  if (!data.ai_available && !data.ai_summary) {
    // AI skipped or API key not set — EDHREC is the primary recommendation
    const sug = data.ai_suggestions || [];
    el.innerHTML = `
      ${creativityHtml}
      ${edhrecHtml}
      ${!edhrec.available ? `
        <div class="panel-inner panel-block">
          <h3>EDHREC Recommendations</h3>
          <p class="muted-copy">
            EDHREC data is unavailable for this commander right now${edhrec.error ? `: ${escapeHtml(edhrec.error)}` : '.'}
          </p>
        </div>
      ` : ''}
      ${sug.length ? `
        <div class="panel-inner panel-block">
          <h3>Rule-Based Suggestions</h3>
          <div class="suggestion-list">
            ${renderSuggestionList(sug)}
          </div>
        </div>
      ` : ''}
      ${!aiEnabled && edhrec.available ? `
        <div class="panel-inner panel-block">
          <h3>AI Review Disabled</h3>
          <p class="muted-copy">
            Model-backed recommendations are disabled for this deployment. EDHREC and creativity analysis are still shown here.
          </p>
        </div>
      ` : ''}
      ${aiEnabled && !edhrec.available ? `
        <div class="ai-unavailable panel-block">
          <p>AI advisor is offline.</p>
          <p class="mt-small">Set <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>, or choose <code>Ollama</code> with a local model.</p>
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
      <details class="advisor-raw-response">
        <summary>Full AI response</summary>
        <pre>${escapeHtml(data.ai_full_response)}</pre>
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
    }).join('') || '<span class="soft-empty">—</span>';
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
    }).join('') || '<span class="soft-empty">—</span>';

    const subHtml = card.plan_subcategory
      ? `<span class="creativity-subcategory">${escapeHtml(card.plan_subcategory)}</span>`
      : '<span class="soft-empty">—</span>';

    const cmc = card.cmc != null ? Number(card.cmc) : null;
    const cmcHtml = cmc != null ? String(Number.isInteger(cmc) ? cmc : cmc) : '—';
    const ciHtml  = (card.color_identity || []).map(colorPip).join('') || '<span class="soft-empty">—</span>';

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
    : '<p class="soft-empty padded-empty">None. Deck closely follows the average build.</p>';

  const skippedContent = _creativitySkipped.length
    ? `<div class="creativity-table-wrap"><table class="creativity-table" id="creativity-skipped-table">${tableHeader}<tbody id="creativity-skipped-tbody">${_creativityCardRows(sortedSkipped)}</tbody></table></div>`
    : '<p class="soft-empty padded-empty">You run all common average-deck staples.</p>';

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
      <details class="creativity-details creativity-details-primary">
        <summary class="creativity-summary">Your Original Picks (${_creativityUnique.length})</summary>
        ${uniqueContent}
      </details>
      <details class="creativity-details details-content">
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
    <div class="panel-inner edhrec-panel panel-block">
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
        ? `<p class="soft-empty">${
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
        <details class="details-offset">
          <summary class="edhrec-already-have">You already run ${_edhrecIncluded.length} EDHREC-recommended card${_edhrecIncluded.length !== 1 ? 's' : ''} ▸</summary>
          <div class="edhrec-table-wrap details-content">
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
        <td>${escapeHtml(c.quantity)}</td>
        <td colspan="7">${escapeHtml(c.raw_name)} - not found in database</td>
      </tr>`;
    }
    const ci = (c.color_identity || []).map(colorPip).join('');
    const pt = (c.power && c.toughness) ? `${c.power}/${c.toughness}` : (c.defense ? `[${c.defense}]` : '—');
    const rarityClass = { common:'rarity-c', uncommon:'rarity-u', rare:'rarity-r', mythic:'rarity-m' }[c.rarity] || '';
    const link = c.scryfall_uri
      ? `<a class="card-name-link" href="${escapeHtml(c.scryfall_uri)}" target="_blank" rel="noopener">${escapeHtml(c.name)}</a>`
      : escapeHtml(c.name);
    return `<tr>
      <td>${escapeHtml(c.quantity)}</td>
      <td>${link} ${c.is_commander ? '<span class="commander-mark">Commander</span>' : ''}</td>
      <td>${escapeHtml(c.type_line || '—')}</td>
      <td>${escapeHtml(c.cmc !== null && c.cmc !== undefined ? c.cmc : '—')}</td>
      <td>${ci || '—'}</td>
      <td>${escapeHtml(pt)}</td>
      <td class="${rarityClass}">${escapeHtml((c.rarity || '').charAt(0).toUpperCase())}</td>
      <td>${c.game_changer ? '<span class="gc-dot">★</span>' : ''}</td>
    </tr>`;
  }).join('');
}

document.getElementById('card-filter').addEventListener('input', filterCards);
document.getElementById('type-filter').addEventListener('change', filterCards);

['paste-input', 'bracket-select', 'budget-tier-select', 'ai-provider-select', 'ai-model-input', 'skip-ai-check'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener(el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input', updateInputReadiness);
});

// ── Tab switching ─────────────────────────────────────────────────────────────
function setActiveTab(tab, { focus = true } = {}) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    const active = btn.dataset.tab === tab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
    btn.tabIndex = active ? 0 : -1;
    if (active && focus) btn.focus();
  });
  document.querySelectorAll('.tab-content').forEach(panel => {
    const active = panel.id === `tab-${tab}`;
    panel.classList.toggle('hidden', !active);
  });
}

document.querySelectorAll('.tab-btn').forEach((btn, index, buttons) => {
  btn.addEventListener('click', () => setActiveTab(btn.dataset.tab));
  btn.addEventListener('keydown', event => {
    const key = event.key;
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(key)) return;
    event.preventDefault();
    let nextIndex = index;
    if (key === 'ArrowRight') nextIndex = (index + 1) % buttons.length;
    if (key === 'ArrowLeft') nextIndex = (index - 1 + buttons.length) % buttons.length;
    if (key === 'Home') nextIndex = 0;
    if (key === 'End') nextIndex = buttons.length - 1;
    setActiveTab(buttons[nextIndex].dataset.tab);
  });
});

// ── Auth events ───────────────────────────────────────────────────────────────
document.getElementById('auth-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  if (!_supabaseClient) return;

  const { email, password, confirm } = getAuthFormValues();

  if (_authMode === 'reset-request') {
    if (!email) {
      setAuthStatus('Enter your email first.', 'error');
      return;
    }
    setAuthStatus('Sending reset link...');
    const { error } = await _supabaseClient.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin,
    });
    if (error) {
      setAuthStatus(error.message, 'error');
      return;
    }
    setAuthStatus('Password reset link sent. Check your email.', 'ok');
    return;
  }

  if (_authMode === 'recovery') {
    if (!validateNewPassword(password, confirm)) return;
    setAuthStatus('Updating password...');
    const { data, error } = await _supabaseClient.auth.updateUser({ password });
    if (error) {
      setAuthStatus(error.message, 'error');
      return;
    }
    _session = data.user ? _session : null;
    setAuthStatus('Password updated. You can now use the app.', 'ok');
    setAuthMode('sign-in');
    updateAuthShell();
    if (_session) await startAuthenticatedApp();
    return;
  }

  if (!email || !password) {
    setAuthStatus('Enter an email and password first.', 'error');
    return;
  }

  if (_authMode === 'sign-up') {
    if (!validateNewPassword(password, confirm)) return;
    setAuthStatus('Creating account...');
    const { data, error } = await _supabaseClient.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: window.location.origin },
    });
    if (error) {
      setAuthStatus(error.message, 'error');
      return;
    }
    _session = data.session;
    if (_session) {
      setAuthStatus('Account created. Checking invite status...', 'ok');
      updateAuthShell();
      await startAuthenticatedApp();
    } else {
      setAuthStatus('Account created. Check your email to confirm it, then sign in.', 'ok');
      setAuthMode('sign-in');
    }
    return;
  }

  setAuthStatus('Signing in...');
  const { data, error } = await _supabaseClient.auth.signInWithPassword({ email, password });
  if (error) {
    setAuthStatus(`${error.message}. If you have not set a password yet, create an account with your whitelisted email or use password reset.`, 'error');
    return;
  }
  _session = data.session;
  setAuthStatus('');
  updateAuthShell();
  await startAuthenticatedApp();
});

document.getElementById('auth-secondary-btn')?.addEventListener('click', () => {
  setAuthMode(_authMode === 'sign-up' ? 'sign-in' : 'sign-up');
});

document.getElementById('auth-reset-btn')?.addEventListener('click', () => {
  setAuthMode('reset-request');
});

document.getElementById('auth-back-btn')?.addEventListener('click', () => {
  setAuthMode('sign-in');
});

document.getElementById('sign-out-btn')?.addEventListener('click', async () => {
  if (_supabaseClient) await _supabaseClient.auth.signOut();
  _session = null;
  startAuthenticatedApp.started = false;
  updateAuthShell();
});

document.getElementById('confirm-ok-btn')?.addEventListener('click', () => {
  if (_confirmResolve) _confirmResolve(true);
});

document.getElementById('confirm-cancel-btn')?.addEventListener('click', () => {
  if (_confirmResolve) _confirmResolve(false);
});

document.getElementById('confirm-overlay')?.addEventListener('click', event => {
  if (event.target.id === 'confirm-overlay' && _confirmResolve) _confirmResolve(false);
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && _confirmResolve) _confirmResolve(false);
});

// ── Init ──────────────────────────────────────────────────────────────────────
initAuth();

// Sortable static tables
const _cardTableEl = document.getElementById('card-table');
if (_cardTableEl) initTableSort(_cardTableEl, _cardSort, filterCards);
const _roleTableEl = document.getElementById('card-role-table');
if (_roleTableEl) initTableSort(_roleTableEl, _roleSort, () => filterCardRoleTable(_cmcMapCache));
