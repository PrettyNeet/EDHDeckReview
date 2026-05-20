-- Durable action logging for hosted DeckReview analytics.
-- Run this in the Supabase SQL editor.

create table if not exists public.user_action_logs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  event_type text not null,
  user_id uuid,
  user_email text,
  request_id text,
  source text,
  decklist_text text,
  moxfield_url text,
  moxfield_deck_id text,
  moxfield_deck_name text,
  commander text,
  card_count int,
  input_metadata jsonb not null default '{}',
  result_summary jsonb not null default '{}',
  diagnostics jsonb not null default '{}',
  error jsonb,
  user_agent text,
  ip_hash text
);

create index if not exists user_action_logs_created_at_idx
  on public.user_action_logs (created_at desc);

create index if not exists user_action_logs_user_email_idx
  on public.user_action_logs (user_email);

create index if not exists user_action_logs_event_type_idx
  on public.user_action_logs (event_type);

alter table public.user_action_logs enable row level security;

-- Keep this table service-role only for now. The app writes with
-- SUPABASE_SERVICE_ROLE_KEY; browser clients should not read/write logs directly.
