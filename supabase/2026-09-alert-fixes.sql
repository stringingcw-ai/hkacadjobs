-- ─────────────────────────────────────────────────────────────────────────────
-- HKAcadJobs — job alert fixes (Sep 2026)
-- Run in the Supabase dashboard → SQL Editor, one step at a time.
--
-- Background: saving a filter with alerts switched on created the
-- `subscriptions` row but left `saved_filters.alert_enabled` false.
-- Since 13 May 2026, notify.py only emails filters whose alert_enabled is
-- true, so those subscribers stopped receiving alerts while the site still
-- showed their bell as ON. The UI bug is fixed in index.html; this script
-- repairs existing rows and adds a safe unsubscribe endpoint for email links.
-- ─────────────────────────────────────────────────────────────────────────────


-- STEP 1 — Review the subscriptions notify.py is currently skipping.
-- Each row is a saved filter whose bell shows ON in the UI (the site derives it
-- from the subscription row) but which notify.py treats as switched off.
select s.email,
       s.filter_label,
       f.alert_enabled,
       f.filter_state
from subscriptions s
join saved_filters f
  on f.user_id = s.user_id and f.label = s.filter_label
where coalesce(f.alert_enabled, false) = false
order by s.email;

-- Subscriptions with no matching saved filter (filter deleted or renamed).
-- These are correctly skipped; delete them if you want a tidy table.
select s.email, s.filter_label
from subscriptions s
where s.user_id is not null
  and not exists (
    select 1 from saved_filters f
    where f.user_id = s.user_id and f.label = s.filter_label
  );


-- STEP 2 — Backfill: turn alert_enabled on wherever a subscription exists, so
-- notify.py agrees with what each user sees on the site. If step 1 shows anyone
-- you know switched alerts off, exclude their email here first.
update saved_filters f
set alert_enabled = true
from subscriptions s
where s.user_id = f.user_id
  and s.filter_label = f.label
  and coalesce(f.alert_enabled, false) = false;


-- STEP 3 — Unsubscribe endpoint used by the link in every alert email
-- (https://www.hkacadjobs.org/?unsubscribe=<token>). SECURITY DEFINER lets the
-- anonymous page delete exactly the row matching the secret token without
-- granting anon any broader DELETE rights on `subscriptions`.
create or replace function public.unsubscribe_alert(p_token text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_sub   record;
  v_count integer := 0;
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

  return v_count;
end;
$$;

revoke all on function public.unsubscribe_alert(text) from public;
grant execute on function public.unsubscribe_alert(text) to anon, authenticated;


-- STEP 4 (optional) — Verify: this should now return no rows.
select s.email, s.filter_label
from subscriptions s
join saved_filters f on f.user_id = s.user_id and f.label = s.filter_label
where coalesce(f.alert_enabled, false) = false;
