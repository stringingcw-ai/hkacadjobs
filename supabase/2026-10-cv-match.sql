-- ─────────────────────────────────────────────────────────────────────────────
-- HKAcadJobs — CV matching (Oct 2026)
-- Run once in the Supabase dashboard → SQL Editor, before the match-jobs Edge
-- Function (supabase/functions/match-jobs) goes live. Safe to run again.
--
-- Nothing here stores a CV. match_usage holds token counts and costs per
-- request; match_profiles holds the structured profile only for signed-in users
-- who choose to save it for "jobs that fit you" alerts.
-- ─────────────────────────────────────────────────────────────────────────────


-- STEP 1 — Usage log: one row per request that used Claude, for each account's
-- daily limits and the site-wide daily budget.
create table if not exists public.match_usage (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),
  user_id       uuid references auth.users (id) on delete cascade,  -- null for the daily alert run
  action        text not null check (action in ('profile', 'match', 'alert')),
  model         text not null,
  input_tokens  integer not null default 0,
  output_tokens integer not null default 0,
  cost_usd      numeric(10, 5) not null default 0,
  outcome       text not null check (outcome in ('ok', 'refused', 'unreadable', 'error'))
);
create index if not exists match_usage_user_created_idx on public.match_usage (user_id, created_at);
create index if not exists match_usage_created_idx on public.match_usage (created_at);

-- Row level security on, with no policies: only the service role (the Edge
-- Function) can read or write this table.
alter table public.match_usage enable row level security;


-- STEP 2 — Today's use (Hong Kong day), read by the function before each
-- request. A failed call ('error') doesn't count against a person's limit;
-- every call counts towards the budget.
create or replace function public.match_quota_status(p_user_id uuid)
returns json
language sql
stable
set search_path = public
as $$
  select json_build_object(
    'user_profiles',  count(*) filter (where user_id = p_user_id and action = 'profile' and outcome <> 'error'),
    'user_matches',   count(*) filter (where user_id = p_user_id and action = 'match' and outcome <> 'error'),
    'site_cost_usd',  coalesce(sum(cost_usd) filter (where action in ('profile', 'match')), 0),
    'alert_cost_usd', coalesce(sum(cost_usd) filter (where action = 'alert'), 0)
  )
  from match_usage
  where created_at >= (date_trunc('day', now() at time zone 'Asia/Hong_Kong') at time zone 'Asia/Hong_Kong');
$$;

revoke all on function public.match_quota_status(uuid) from public, anon, authenticated;
grant execute on function public.match_quota_status(uuid) to service_role;


-- STEP 3 — Saved profiles for "jobs that fit you" alerts (opt-in, signed-in
-- users only). Used from phase 3 of CV_MATCH_PLAN.md; created now so this file
-- runs once. Each user can read and change only their own row, and only with
-- their own sign-in email.
create table if not exists public.match_profiles (
  user_id        uuid primary key references auth.users (id) on delete cascade,
  email          text not null,
  profile        jsonb not null,
  prefs          jsonb not null default '{}'::jsonb,  -- {"unis": [...]}: institutions the user chose
  alerts_enabled boolean not null default true,
  token          text not null unique check (length(token) >= 16),  -- for the unsubscribe link
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
-- prefs was added after the first run of this file
alter table public.match_profiles add column if not exists prefs jsonb not null default '{}'::jsonb;
alter table public.match_profiles enable row level security;

-- (select auth.…()) is evaluated once per query rather than once per row
drop policy if exists "match_profiles_own_row" on public.match_profiles;
create policy "match_profiles_own_row" on public.match_profiles
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id and email = ((select auth.jwt()) ->> 'email'));


-- STEP 4 — The unsubscribe link in alert emails (?unsubscribe=<token>) also
-- switches off match alerts. Same as in 2026-09-alert-fixes.sql, plus the
-- match_profiles update at the end.
create or replace function public.unsubscribe_alert(p_token text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_sub   record;
  v_count integer := 0;
  v_rows  integer;
begin
  if p_token is null or length(p_token) < 16 then
    return 0;
  end if;

  for v_sub in
    delete from subscriptions where token = p_token
    returning user_id, filter_label
  loop
    v_count := v_count + 1;
    if v_sub.user_id is not null then
      -- Keep the saved filter itself, but switch its bell off.
      update saved_filters
         set alert_enabled = false
       where user_id = v_sub.user_id and label = v_sub.filter_label;
      begin
        update saved_filters
           set filter_state = filter_state::jsonb - '_alertEnabled'
         where user_id = v_sub.user_id and label = v_sub.filter_label;
      exception when others then
        null;  -- filter_state isn't jsonb-compatible; alert_enabled above is what matters
      end;
    end if;
  end loop;

  -- "Jobs that fit you" alerts: keep the saved profile, stop the emails
  update match_profiles
     set alerts_enabled = false, updated_at = now()
   where token = p_token and alerts_enabled;
  get diagnostics v_rows = row_count;
  v_count := v_count + v_rows;

  return v_count;
end;
$$;

revoke all on function public.unsubscribe_alert(text) from public;
grant execute on function public.unsubscribe_alert(text) to anon, authenticated;


-- OPTIONAL — Use and spend per day (Hong Kong time):
-- select date_trunc('day', created_at at time zone 'Asia/Hong_Kong') as day, action,
--        count(*) as requests, count(distinct user_id) as people, sum(cost_usd) as usd
--   from match_usage
--  group by 1, 2
--  order by 1 desc, 2;

-- Usage rows are kept for 90 days, as the site's privacy notice says: the daily
-- alert run (scraper/match_alerts.py, purge_usage_log) deletes older ones.
