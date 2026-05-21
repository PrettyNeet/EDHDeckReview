# Vercel + Supabase Deployment

## Vercel app shape

Vercel uses the root [index.py](../index.py) entrypoint, which imports the FastAPI app from
`app.main`. [vercel.json](../vercel.json) rewrites all traffic to `/index.py`.

[.vercelignore](../.vercelignore) excludes local-only artifacts such as raw Scryfall bulk data,
uncompressed cache JSON, test files, results, and virtualenvs. Production uses the compressed
cache files described below.

## Supabase setup

Create the invite whitelist table:

```sql
create table public.allowed_users (
  email text primary key,
  role text not null default 'user',
  active boolean not null default true,
  invited_at timestamptz not null default now(),
  notes text
);

alter table public.allowed_users enable row level security;
```

Manage invites by inserting or deactivating rows in Supabase:

```sql
insert into public.allowed_users (email) values ('you@example.com');
update public.allowed_users set active = false where email = 'old@example.com';
```

The backend reads this table with `SUPABASE_SERVICE_ROLE_KEY`; do not expose that key in client code.

Invited users still need a Supabase Auth account. In the web app they should choose
`Create Account`, enter their whitelisted email, and set their password. If Supabase
email confirmation is enabled, they must confirm the email before signing in. The
`Forgot password?` flow sends a recovery link and lets them set a replacement password.

Public routes are `/`, frontend assets, `/health`, and `/api/config`. All deck-review,
card lookup, Moxfield, commander-role, and maintenance API routes require both a valid
Supabase session and an active whitelist row.

## Action logging

Run [supabase-action-logging.sql](supabase-action-logging.sql) in the Supabase SQL editor
to create durable action logs.

The backend writes to `public.user_action_logs` with `SUPABASE_SERVICE_ROLE_KEY`.
Action logging defaults on when Supabase URL + service-role key are configured; set
`ACTION_LOGGING_ENABLED=false` to disable it. Set `ACTION_LOG_IP_HASH_SALT` to a stable
secret so client IP hashes remain useful without storing raw IP addresses.

Logged events include `moxfield_import_requested`, `moxfield_import_completed`,
`moxfield_import_failed`, `deck_review_submitted`, `deck_review_completed`, and
`deck_review_failed`.

Logs intentionally store the full submitted decklist text and are retained indefinitely.
Do not expose this table to browser clients; keep it service-role only unless an admin UI
is added later.

## Vercel environment variables

Set these in the Vercel project:

```env
INVITE_AUTH_ENABLED=true
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
ACTION_LOGGING_ENABLED=true
ACTION_LOG_IP_HASH_SALT=...
AI_PROVIDER=auto
FEATURE_AI_REVIEW_ENABLED=false
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
CLOUDFLARE_TURNSTILE_SITE_KEY=...
```

`SUPABASE_URL`, `SUPABASE_ANON_KEY`, and the optional Turnstile site key are returned to the browser by `/api/config`. Service-role, provider, and CAPTCHA secret keys are never returned.

## Supabase Auth CAPTCHA

To require Cloudflare Turnstile on sign in, sign up, and password reset:

1. Enable CAPTCHA in the Supabase dashboard under Auth settings.
2. Select Cloudflare Turnstile and enter the Turnstile secret key there.
3. Set `CLOUDFLARE_TURNSTILE_SITE_KEY` in the app environment. `TURNSTILE_SITE_KEY` also works as a fallback.

## Feature flags

Feature flags are returned through `/api/config` and enforced by the backend.

| Variable | Default | Effect |
|---|---|---|
| `FEATURE_AI_REVIEW_ENABLED` | `false` on Vercel, `true` locally | Shows AI provider/model controls and allows model-backed AI review calls |

When `FEATURE_AI_REVIEW_ENABLED=false`, the web UI hides only the AI provider/model controls, keeps the results Analysis tab visible for EDHREC and creativity analysis, and the review API will not call Anthropic/OpenAI/Ollama even if a request includes `skip_ai=false`.

## Scryfall cache freshness

Production uses compressed deploy cache files:

- `cache/card_index.json.gz`
- `cache/otag_index.json.gz`
- `cache/index_metadata.json`

Vercel runtime rebuilds and bulk downloads are disabled. Refresh these files through the scheduled GitHub Actions workflow or manually:

```bash
python3 scripts/refresh_deploy_cache.py
```

The workflow opens a pull request with the refreshed compressed cache files. Merge that PR and redeploy to update production data.

`/health` and `/api/index/status` treat `cache/card_index.json.gz` as index-ready, so the
web app should show `Index: ready` in production when the compressed cache is deployed.

## Upload validation

The web app and backend both validate deck uploads. Files must be:

- `.txt`
- plain text
- non-empty
- under 512 KB
- text-like, with no binary NUL bytes near the start

Invalid uploads return `400` from `/api/review`.
