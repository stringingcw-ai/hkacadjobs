"""
match_alerts.py
───────────────
"Jobs that fit you" emails. Signed-in users can save the profile Claude built from
their CV (the match_profiles table, see supabase/2026-10-cv-match.sql). Each day,
for every saved profile with alerts on, this asks the match-jobs Edge Function
which of the day's new jobs fit, and emails the fits with a line on why.

Run by notify.py after the saved-filter alerts. It shares their sent log
(scraper/alert_log.json), so nobody is emailed the same job twice. It also deletes
usage records older than 90 days (purge_usage_log), as the site's privacy notice says.
"""

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape

import notify

FUNCTION_PATH = "/functions/v1/match-jobs"
MAX_PER_EMAIL = 5     # best fits per email
MIN_SCORE = 65        # Claude's 0-100 fit score; 70+ is a good fit
WORKERS = 4           # profiles matched at once
USAGE_KEEP_DAYS = 90  # match_usage rows (sizes and costs, never CV text) are kept this long


class BudgetReached(Exception):
    """The function's daily budget for match alerts (ALERT_DAILY_BUDGET_USD) is used up."""


def get_match_profiles():
    """Saved CV profiles whose owners want these emails."""
    return notify._get_all(
        "match_profiles?select=user_id,email,profile,prefs,token&alerts_enabled=eq.true&order=user_id")


def fetch_matches(profile, job_ids, prefs=None, timeout=90):
    """Ask match-jobs, as the service role, which of `job_ids` fit `profile`
    (only at the institutions in prefs["unis"], if the user chose any)."""
    body = json.dumps({
        "action": "match", "profile": profile, "only_ids": job_ids,
        "prefs": {"unis": list((prefs or {}).get("unis") or [])},
        "limit": MAX_PER_EMAIL, "min_score": MIN_SCORE,
    }).encode()
    req = urllib.request.Request(
        f"{notify.SUPABASE_URL}{FUNCTION_PATH}", data=body, method="POST",
        headers={
            "Authorization": f"Bearer {notify.SUPABASE_SERVICE_KEY}",
            "apikey": notify.SUPABASE_SERVICE_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=notify._SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code == 503 and "budget_reached" in detail:
            raise BudgetReached(detail)
        raise RuntimeError(f"match-jobs HTTP {e.code}: {detail}")
    return data.get("matches") or []


def purge_usage_log(days=USAGE_KEEP_DAYS, dry_run=False):
    """Delete CV-matching usage records older than `days`. Returns True if done."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if dry_run:
        print(f"DRY RUN — would delete CV-matching usage records from before {cutoff[:10]}")
        return True
    key = notify.SUPABASE_SERVICE_KEY
    req = urllib.request.Request(
        f"{notify.SUPABASE_URL}/rest/v1/match_usage?created_at=lt.{cutoff}", method="DELETE",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=minimal"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=notify._SSL_CONTEXT):
            pass
    except (urllib.error.URLError, OSError) as e:
        # Not a failed run: tomorrow's run tries again, and the warning shows in the Actions summary
        print(f"::warning::Could not delete CV-matching usage records older than {days} days: {e}")
        return False
    print(f"Deleted CV-matching usage records from before {cutoff[:10]}")
    return True


def masked(email):
    """Enough of an address to tell recipients apart in a public Actions log."""
    name, _, domain = (email or "").partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def subject_for(count):
    return f"HKAcadJobs: {count} new job{'s' if count != 1 else ''} that fit your profile"


def render_match_email(row, fits, jobs_by_id):
    """(html, text) for one person's fits, in the same style as the filter alerts."""
    token     = row.get("token", "")
    unsub_url = notify.unsubscribe_url(token)
    home_url  = f"{notify.SITE_URL}/?utm_source=job_alert&utm_medium=email&utm_campaign=cv_match"
    today     = datetime.now(notify.HKT).strftime("%d %b %Y")
    headline  = ((row.get("profile") or {}).get("headline") or "").strip()
    count     = len(fits)

    rows_html, text_items = "", []
    for fit in fits:
        job    = jobs_by_id[fit["job_id"]]
        url    = notify.job_page_url(job, campaign="cv_match")
        uni    = notify.UNI_DISPLAY.get(job["university"], job["university"])
        dl     = notify.deadline_text(job)
        dl_str = f" · Deadline: {dl}" if job.get("deadline") else (f" · {dl}" if dl else "")
        gaps   = [g for g in fit.get("gaps") or [] if g]
        gaps_html = (f'<div style="font-size:12px;color:#9c9690;margin-top:4px;">Worth checking: '
                     f'{escape("; ".join(gaps))}</div>') if gaps else ""
        rows_html += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #e8e4da;">
            <div style="font-weight:600;color:#1a1a1a;margin-bottom:4px;">
              <a href="{escape(url)}" style="color:#1a1a1a;text-decoration:none;">{escape(job['title'])}</a>
            </div>
            <div style="font-size:13px;color:#6b6560;">{escape(uni)} · {escape(job.get('rank', ''))}{escape(dl_str)}</div>
            <div style="font-size:13px;color:#3d3a35;margin-top:6px;">{escape(fit.get('why', ''))}</div>{gaps_html}
          </td>
        </tr>"""
        text_items.append(
            f"• {job['title']}\n  {uni} · {job.get('rank', '')}{dl_str}\n  {fit.get('why', '')}\n"
            + (f"  Worth checking: {'; '.join(gaps)}\n" if gaps else "") + f"  {url}\n")

    intro = "New postings today that fit the CV profile you saved"
    intro += f": {headline}." if headline else "."
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f2eb;font-family:'DM Sans',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f2eb;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;overflow:hidden;max-width:600px;width:100%;">

        <!-- Header -->
        <tr><td style="background:#2b3240;padding:24px 32px;">
          <span style="font-size:18px;font-weight:700;color:#fff;letter-spacing:-0.3px;">HKAcadJobs</span>
          <span style="font-size:13px;color:#9aa3b2;margin-left:12px;">Jobs that fit you</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:14px;color:#6b6560;">{today}</p>
          <h1 style="margin:0 0 6px;font-size:20px;font-weight:700;color:#1a1a1a;">
            {count} new job{'s' if count != 1 else ''} that fit your profile
          </h1>
          <p style="margin:0 0 24px;font-size:13px;color:#6b6560;">{escape(intro)}</p>

          <table width="100%" cellpadding="0" cellspacing="0">
            {rows_html}
          </table>

          <div style="margin-top:28px;">
            <a href="{escape(home_url)}"
               style="display:inline-block;background:#2b3240;color:#fff;padding:11px 22px;border-radius:7px;font-size:14px;font-weight:600;text-decoration:none;">
              View all jobs →
            </a>
          </div>
          <p style="margin:20px 0 0;font-size:12px;color:#9c9690;">
            Suggestions are made by AI from your saved profile. Always check the full advertisement.
          </p>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f5f2eb;padding:20px 32px;border-top:1px solid #e8e4da;">
          <p style="margin:0;font-size:12px;color:#9c9690;line-height:1.6;">
            You're receiving this because you saved your CV profile on HKAcadJobs and asked for these emails.
            To change or delete your profile, sign in and open "My CV profile".<br>
            <a href="{escape(unsub_url)}" style="color:#9c9690;">Unsubscribe</a> ·
            <a href="{escape(home_url)}" style="color:#9c9690;">hkacadjobs.org</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = (f"HKAcadJobs — Jobs that fit you — {today}\n\n"
            f"{count} new job{'s' if count != 1 else ''} that fit your profile. {intro}\n\n"
            + "\n".join(text_items)
            + "\nSuggestions are made by AI from your saved profile. Always check the full advertisement.\n"
            + f"\nView all jobs: {home_url}\nUnsubscribe: {unsub_url}\n")
    return html, text


def run(new_jobs, alert_log, dry_run=False):
    """Email each saved profile the day's new jobs that fit it.
    Updates `alert_log` for what was sent; returns the number of failures."""
    if not new_jobs:
        return 0
    try:
        profiles = get_match_profiles()
    except RuntimeError as e:
        print(f"⚠️  Could not read saved CV profiles: {e}")
        return 1
    print(f"Saved CV profiles with alerts on: {len(profiles)}")
    if not profiles:
        return 0

    jobs_by_id = {j["id"]: j for j in new_jobs}

    def match(row):
        """(row, fits, error) — only jobs this profile hasn't been sent before are offered."""
        already = alert_log.get(notify._sub_key(row), {})
        fresh = [jid for jid in jobs_by_id if jid not in already]
        if not fresh:
            return row, [], None
        try:
            fits = [f for f in fetch_matches(row.get("profile") or {}, fresh, row.get("prefs"))
                    if f.get("job_id") in fresh]
            return row, fits[:MAX_PER_EMAIL], None
        except Exception as e:   # reported below, per profile
            return row, [], e

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(match, profiles))

    sent = failures = paused = 0
    today = datetime.now(notify.HKT).date().isoformat()
    for row, fits, error in results:
        who = masked(row.get("email"))
        if isinstance(error, BudgetReached):
            paused += 1
            continue
        if error:
            print(f"  ❌ Matching failed for {who}: {error}")
            failures += 1
            continue
        if not fits:
            continue
        html, text = render_match_email(row, fits, jobs_by_id)
        if dry_run:
            print(f"\n  → {who} | {len(fits)} fit(s):")
            for f in fits:
                print(f"      • {jobs_by_id[f['job_id']]['title']} ({f.get('score')})")
            continue
        try:
            notify.send_email(row["email"], subject_for(len(fits)), html, text,
                              unsub_url=notify.unsubscribe_url(row.get("token", "")))
            alert_log.setdefault(notify._sub_key(row), {}).update({f["job_id"]: today for f in fits})
            print(f"  ✅ Sent to {who} ({len(fits)} jobs)")
            sent += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Failed for {who}: {e}")
            failures += 1

    if paused:
        print(f"::warning::Match alerts paused for {paused} profile(s): today's ALERT_DAILY_BUDGET_USD is used up")
    print(f"── Match alerts: {sent} sent, {failures} failed")
    return failures
