# Vercel + Supabase Deployment

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

## Vercel environment variables

Set these in the Vercel project:

```env
INVITE_AUTH_ENABLED=true
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
AI_PROVIDER=auto
FEATURE_AI_REVIEW_ENABLED=false
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

Only `SUPABASE_URL` and `SUPABASE_ANON_KEY` are returned to the browser by `/api/config`.

## Feature flags

Feature flags are returned through `/api/config` and enforced by the backend.

| Variable | Default | Effect |
|---|---|---|
| `FEATURE_AI_REVIEW_ENABLED` | `false` on Vercel, `true` locally | Shows Advisor controls and allows model-backed AI review calls |

When `FEATURE_AI_REVIEW_ENABLED=false`, the web UI hides Advisor provider/model controls and the Advisor tab, and the review API will not call Anthropic/OpenAI/Ollama even if a request includes `skip_ai=false`.

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
