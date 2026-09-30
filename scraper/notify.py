"""
notify.py
─────────
Sends job alert emails to subscribers whose saved filters match new jobs.

Reads new jobs from jobs.csv (is_new == TRUE), fetches subscriptions from
Supabase, matches each subscription's filter_state against the new jobs,
and sends a digest email via Resend.

Usage (local):
  cd scraper
  python notify.py                  # use .env.local
  python notify.py --dry-run        # print matches without sending emails
  python notify.py --test-email you@example.com  # send a test email
"""

import argparse
import csv
import hashlib
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

# Use certifi certs on macOS where Python may not find system certs
try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
CSV_PATH   = SCRIPT_DIR.parent / "jobs.csv"

def load_env():
    env_file = SCRIPT_DIR / ".env.local"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_ANON_KEY    = os.environ.get("SUPABASE_ANON_KEY", "")
RESEND_API_KEY       = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL           = os.environ.get("ALERT_FROM_EMAIL", "alerts@hkacadjobs.org")
SITE_URL             = "https://www.hkacadjobs.org"
UTM                  = "utm_source=job_alert&utm_medium=email&utm_campaign=daily_alert"
HKT                  = timezone(timedelta(hours=8))
ALERT_LOG            = SCRIPT_DIR / "alert_log.json"   # jobs already emailed, per subscription
ALERT_LOG_KEEP_DAYS  = 120

ACADEMIC_RANKS = {
    "Professor", "Associate Professor", "Assistant Professor", "Tenure-Track",
    "Postdoctoral", "Senior Lecturer/Lecturer", "Lecturer", "Senior Management",
    "Teaching Assistant", "Research Assistant/Associate", "Other"
}

# ── Supabase helpers ──────────────────────────────────────────────────────────

def _supabase_request(method, path, body=None, use_service_key=True):
    key = SUPABASE_SERVICE_KEY if use_service_key else SUPABASE_ANON_KEY
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Supabase {method} {path} → {e.code}: {body}")


def _get_all(path, page=1000):
    """GET every row of a table query (PostgREST caps each response at 1,000)."""
    rows, offset = [], 0
    while True:
        sep = "&" if "?" in path else "?"
        batch = _supabase_request("GET", f"{path}{sep}limit={page}&offset={offset}", use_service_key=True)
        rows += batch
        if len(batch) < page:
            return rows
        offset += page


def get_subscriptions():
    return _get_all("subscriptions?select=*&order=token")


def get_enabled_filter_keys():
    """Return a set of (user_id, filter_label) for saved_filters with alert_enabled=true.

    Used as the source of truth for whether a logged-in user wants alerts on a
    given filter. The `subscriptions` table can drift out of sync with this flag
    (filter renames, silent delete failures), so we re-check before emailing.
    """
    rows = _get_all("saved_filters?select=user_id,label,alert_enabled&alert_enabled=eq.true&order=user_id")
    return {(r["user_id"], r["label"]) for r in rows if r.get("user_id") and r.get("label")}


def filter_active_subscriptions(subs, enabled_keys):
    """Drop subscriptions whose saved filter is toggled off (or missing).

    Legacy subscriptions without a user_id (pre-auth email-only signups) are
    always kept — they have no saved_filters row, so the unsubscribe token is
    their only off-switch.
    """
    kept, dropped = [], 0
    for s in subs:
        uid = s.get("user_id")
        if not uid:
            kept.append(s)
            continue
        if (uid, s.get("filter_label")) in enabled_keys:
            kept.append(s)
        else:
            dropped += 1
    return kept, dropped


def insert_subscription(email, filter_label, filter_state):
    token = secrets.token_hex(24)
    return _supabase_request("POST", "subscriptions", {
        "email": email,
        "filter_label": filter_label,
        "filter_state": filter_state,
        "token": token,
    }, use_service_key=False)


def delete_subscription_by_token(token):
    return _supabase_request("DELETE", f"subscriptions?token=eq.{token}", use_service_key=False)


# ── Sent log: never email a subscription the same job twice ──────────────────
#    Keyed by a hash of each subscription's secret token (no emails stored), so
#    it can live in the public repo; committed by the daily workflow.

def _sub_key(sub):
    return hashlib.sha256((sub.get("token") or sub.get("email") or "").encode()).hexdigest()[:16]


def load_alert_log():
    try:
        return json.loads(ALERT_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_alert_log(log):
    cutoff = (datetime.now(HKT).date() - timedelta(days=ALERT_LOG_KEEP_DAYS)).isoformat()
    pruned = {k: {jid: d for jid, d in v.items() if d >= cutoff} for k, v in log.items()}
    ALERT_LOG.write_text(json.dumps({k: v for k, v in pruned.items() if v}, indent=1, sort_keys=True) + "\n",
                         encoding="utf-8")


# ── Job loading ───────────────────────────────────────────────────────────────

def load_new_jobs():
    jobs = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("is_new", "").upper() == "TRUE":
                jobs.append(row)
    return jobs


# ── Filter matching ───────────────────────────────────────────────────────────

INDEX_HTML = SCRIPT_DIR.parent / "index.html"


def _parse_js_groups(source, const_name):
    """Extract `const NAME = [ { group?: '..', area: '..', kw: ['..'] }, ... ];` entries."""
    m = re.search(rf"const {const_name}\s*=\s*\[(.*?)\n\];", source, re.S)
    if not m:
        return []
    entries = []
    for body in re.findall(r"\{([^{}]*)\}", m.group(1)):
        area = re.search(r"area:\s*'([^']*)'", body)
        kw = re.search(r"kw:\s*\[([^\]]*)\]", body)
        if not (area and kw):
            continue
        group = re.search(r"group:\s*'([^']*)'", body)
        entries.append({
            "group": group.group(1) if group else None,
            "area": area.group(1),
            "kw": re.findall(r"'([^']*)'", kw.group(1)),
        })
    return entries


def load_site_taxonomy(path=INDEX_HTML):
    """Read AREA_GROUPS / DEPT_GROUPS from index.html so alerts classify
    departments exactly like the site's Category and group filters do.

    Fails loudly if the arrays can't be found: silently ignoring a saved
    filter's category would email jobs the subscriber never asked for.
    """
    source = Path(path).read_text(encoding="utf-8")
    areas = _parse_js_groups(source, "AREA_GROUPS")
    groups = _parse_js_groups(source, "DEPT_GROUPS")
    if len(areas) < 5 or len(groups) < 10:
        raise RuntimeError(
            f"Could not parse AREA_GROUPS/DEPT_GROUPS from {path} "
            f"({len(areas)} areas, {len(groups)} groups) — update _parse_js_groups()"
        )
    return {"areas": areas, "groups": groups}


def _classify(dept, entries, key):
    """Port of classifyArea() / classifyDeptGroup() in index.html."""
    d = (dept or "").lower()
    if not d:
        return "Other"
    for e in entries:
        if any(k in d for k in e["kw"]):
            return e[key]
    return "Other"


def job_matches_filter(job, state, taxonomy):
    """Mirror the filterJobs() logic from index.html."""
    # Role filter
    role = state.get("role", "")
    if role == "academic" and job["rank"] not in ACADEMIC_RANKS:
        return False
    if role == "non-academic" and job["rank"] in ACADEMIC_RANKS:
        return False

    # Institution filter
    unis = state.get("unis", [])
    if unis and job["university"] not in unis:
        return False

    # Rank filter
    ranks = state.get("ranks", [])
    if ranks and job["rank"] not in ranks:
        return False

    # Category filter: the academic area derived from the department
    # (classifyArea), e.g. "Medicine & Health" — not position_type
    area = state.get("area") or ""
    if area and _classify(job.get("department"), taxonomy["areas"], "area") != area:
        return False

    # Department group chips within the category (classifyDeptGroup)
    dept_groups = state.get("deptGroups") or []
    if dept_groups and _classify(job.get("department"), taxonomy["groups"], "group") not in dept_groups:
        return False

    # Keyword search: the whole phrase, as typed, in any of the fields the site searches
    search = (state.get("search") or "").lower().strip()
    if search:
        fields = ("title", "department", "university", "university_full", "description")
        if not any(search in (job.get(k) or "").lower() for k in fields):
            return False

    return True


def match_jobs_to_subscriptions(new_jobs, subscriptions, taxonomy):
    """Return list of (subscription, matched_jobs) for subscriptions with ≥1 match."""
    results = []
    for sub in subscriptions:
        state = sub.get("filter_state") or {}
        if isinstance(state, str):
            state = json.loads(state)
        matched = [j for j in new_jobs if job_matches_filter(j, state, taxonomy)]
        if matched:
            results.append((sub, matched))
    return results


# ── Email rendering ───────────────────────────────────────────────────────────

UNI_DISPLAY = {
    "HKU": "HKU", "HKUST": "HKUST", "CUHK": "CUHK", "CityU": "CityU",
    "PolyU": "PolyU", "HKBU": "HKBU", "LU": "Lingnan", "EdUHK": "EdUHK",
    "HKMU": "HKMU", "HKSYU": "HKSYU", "HKUSPACE": "HKU SPACE",
    "CPCE": "CPCE", "THEI": "THEi", "VTC": "VTC", "HSU": "HSU",
    "SFU": "SFU", "HKCHC": "Chu Hai",
}


def unsubscribe_url(token):
    """Page that confirms and removes the subscription(s) behind `token`.

    A digest can merge several saved filters, so `token` may be a comma-separated
    list; index.html unsubscribes each one.
    """
    return f"{SITE_URL}/?unsubscribe={urllib.parse.quote(token, safe=',')}"


def job_page_url(job, campaign="daily_alert"):
    """The job's own page on the site (generated by generate_job_pages.py)."""
    from generate_job_pages import job_dir_name
    return f"{SITE_URL}/jobs/{job_dir_name(job)}/?{UTM.replace('daily_alert', campaign)}"


def deadline_text(job):
    dl = job.get("deadline", "")
    if dl:
        try:
            return datetime.strptime(dl, "%Y-%m-%d").strftime("%-d %b %Y")
        except ValueError:
            return dl
    return job.get("deadline_note", "")


def render_email(sub, jobs):
    label     = sub.get("filter_label", "Your filter")
    token     = sub.get("token", "")
    unsub_url = unsubscribe_url(token)
    today     = datetime.now(HKT).strftime("%d %b %Y")
    count     = len(jobs)
    home_url  = f"{SITE_URL}/?{UTM}"

    rows_html = ""
    for j in jobs:
        uni    = UNI_DISPLAY.get(j["university"], j["university"])
        dl     = deadline_text(j)
        dl_str = f" · Deadline: {escape(dl)}" if j.get("deadline") else (f" · {escape(dl)}" if dl else "")
        rows_html += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #e8e4da;">
            <div style="font-weight:600;color:#1a1a1a;margin-bottom:4px;">
              <a href="{escape(job_page_url(j))}" style="color:#1a1a1a;text-decoration:none;">{escape(j['title'])}</a>
            </div>
            <div style="font-size:13px;color:#6b6560;">{escape(uni)} · {escape(j.get('rank',''))}{dl_str}</div>
          </td>
        </tr>"""

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
          <span style="font-size:13px;color:#9aa3b2;margin-left:12px;">Job Alert</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:14px;color:#6b6560;">{today}</p>
          <h1 style="margin:0 0 6px;font-size:20px;font-weight:700;color:#1a1a1a;">
            {count} new job{'s' if count != 1 else ''} matching <em style="font-style:italic;">"{escape(label)}"</em>
          </h1>
          <p style="margin:0 0 24px;font-size:13px;color:#6b6560;">
            New postings added today that match your saved filter.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0">
            {rows_html}
          </table>

          <div style="margin-top:28px;">
            <a href="{escape(home_url)}"
               style="display:inline-block;background:#2b3240;color:#fff;padding:11px 22px;border-radius:7px;font-size:14px;font-weight:600;text-decoration:none;">
              View all jobs →
            </a>
          </div>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f5f2eb;padding:20px 32px;border-top:1px solid #e8e4da;">
          <p style="margin:0;font-size:12px;color:#9c9690;line-height:1.6;">
            You're receiving this because you set up a job alert on HKAcadJobs.<br>
            <a href="{escape(unsub_url)}" style="color:#9c9690;">Unsubscribe</a> ·
            <a href="{escape(home_url)}" style="color:#9c9690;">hkacadjobs.org</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""HKAcadJobs Job Alert — {today}

{count} new job{'s' if count != 1 else ''} matching "{label}":

"""
    for j in jobs:
        uni = UNI_DISPLAY.get(j["university"], j["university"])
        dl  = deadline_text(j)
        dl_str = f" | Deadline: {dl}" if j.get("deadline") else (f" | {dl}" if dl else "")
        text += f"• {j['title']}\n  {uni} · {j.get('rank','')}{dl_str}\n  {job_page_url(j)}\n\n"

    text += f"\nView all jobs: {home_url}\nUnsubscribe: {unsub_url}\n"
    return html, text


# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(to_email, subject, html, text, unsub_url=None):
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not set")
    body = {
        "from": f"HKAcadJobs <{FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if unsub_url:
        # Lets mail clients show their own "Unsubscribe" button
        body["headers"] = {"List-Unsubscribe": f"<{unsub_url}>"}
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; HKAcadJobs-Notifier/1.0)",
        }
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Resend error {e.code}: {e.read().decode()}")


# ── Entry point ───────────────────────────────────────────────────────────────

def send_filter_alerts(new_jobs, alert_log, dry_run=False):
    """Saved-filter alerts. Updates `alert_log` for what was sent. Returns
    (number of emails that failed, whether most logged-in alerts were skipped)."""
    subs = get_subscriptions()
    print(f"Subscriptions: {len(subs)}")
    if not subs:
        print("No subscribers yet.")
        return 0, False

    # Source of truth for "alerts on" is saved_filters.alert_enabled.
    # Drop subscription rows whose saved filter has been toggled off (or
    # whose saved filter has been deleted entirely). Anonymous/legacy subs
    # without a user_id are kept as-is.
    enabled_keys = get_enabled_filter_keys()
    logged_in = sum(1 for s in subs if s.get("user_id"))
    subs, dropped = filter_active_subscriptions(subs, enabled_keys)
    # Exit non-zero (after sending) when most logged-in alerts are being
    # skipped: that is how a UI bug silenced 28 of 29 alerts for months.
    # The workflow's health check turns this exit code into a failed run.
    too_many_skipped = dropped >= 3 and dropped > logged_in / 2
    if dropped:
        print(f"Skipped {dropped} subscription(s) with alerts toggled off")
    if too_many_skipped:
        print(f"::warning::{dropped} of {logged_in} logged-in subscriptions skipped because "
              "saved_filters.alert_enabled is not true — see supabase/2026-09-alert-fixes.sql")
    if not subs:
        print("No active subscriptions after applying alert_enabled filter.")
        return 0, too_many_skipped

    # Match, then drop jobs this subscription has already been sent
    taxonomy = load_site_taxonomy()
    matches, repeats = [], 0
    for sub, jobs in match_jobs_to_subscriptions(new_jobs, subs, taxonomy):
        already = alert_log.get(_sub_key(sub), {})
        fresh = [j for j in jobs if j["id"] not in already]
        repeats += len(jobs) - len(fresh)
        if fresh:
            matches.append((sub, fresh))
    if repeats:
        print(f"Skipped {repeats} job(s) already emailed to the same subscription")
    print(f"Subscribers with matches: {len(matches)}")

    # Group by email so each subscriber gets one digest (not one per filter)
    by_email = {}
    for sub, jobs in matches:
        email = sub["email"]
        if email not in by_email:
            by_email[email] = {"sub": sub, "jobs": [], "labels": [], "tokens": [], "sent": []}
        by_email[email]["sent"].append((_sub_key(sub), [j["id"] for j in jobs]))
        seen_ids = {j["id"] for j in by_email[email]["jobs"]}
        for j in jobs:
            if j["id"] not in seen_ids:
                by_email[email]["jobs"].append(j)
                seen_ids.add(j["id"])
        by_email[email]["labels"].append(sub.get("filter_label", "Your filter"))
        if sub.get("token"):
            by_email[email]["tokens"].append(sub["token"])
    print(f"Unique recipients: {len(by_email)}")

    sent = 0
    for email, info in by_email.items():
        combined_label = " + ".join(dict.fromkeys(info["labels"]))
        # One unsubscribe click should stop the whole digest, so include every
        # subscription token merged into it.
        combined_token = ",".join(dict.fromkeys(info["tokens"]))
        merged_sub = {**info["sub"], "filter_label": combined_label, "token": combined_token}
        jobs = info["jobs"]
        subject = f"HKAcadJobs: {len(jobs)} new job{'s' if len(jobs) != 1 else ''} matching \"{combined_label}\""
        html, text = render_email(merged_sub, jobs)

        if dry_run:
            print(f"\n  → {email} | {combined_label} | {len(jobs)} match(es):")
            for j in jobs:
                print(f"      • {j['title']} ({j['university']})")
        else:
            try:
                send_email(email, subject, html, text, unsub_url=unsubscribe_url(combined_token))
                print(f"  ✅ Sent to {email} ({len(jobs)} jobs)")
                sent += 1
                today = datetime.now(HKT).date().isoformat()
                for key, ids in info["sent"]:
                    alert_log.setdefault(key, {}).update({jid: today for jid in ids})
                time.sleep(0.3)
            except Exception as e:
                print(f"  ❌ Failed for {email}: {e}")

    if dry_run:
        return 0, too_many_skipped
    print(f"\n── Done: {sent}/{len(by_email)} emails sent")
    return len(by_email) - sent, too_many_skipped


def main():
    parser = argparse.ArgumentParser(description="Send HKAcadJobs alerts")
    parser.add_argument("--dry-run",    action="store_true", help="Print matches, don't send emails")
    parser.add_argument("--test-email", metavar="EMAIL",     help="Send a test alert to this address")
    args = parser.parse_args()

    print("── HKAcadJobs Notify ──────────────────────────────────")

    # Load new jobs
    new_jobs = load_new_jobs()
    print(f"New jobs today: {len(new_jobs)}")
    if not new_jobs and not args.test_email:
        print("No new jobs — nothing to send.")
        return

    # Test mode: inject a dummy job so email renders correctly
    if args.test_email:
        if not new_jobs:
            new_jobs = [{
                "id": "TEST-1", "title": "Test: Assistant Professor in Computer Science",
                "rank": "Assistant Professor", "university": "HKU",
                "department": "Department of Computer Science",
                "deadline": "31 Dec 2026", "is_new": "TRUE",
                "apply_url": SITE_URL, "position_type": "Academic",
            }]
        test_sub = {
            "email": args.test_email, "filter_label": "All Jobs",
            "filter_state": {}, "token": "test-token-000",
        }
        html, text = render_email(test_sub, new_jobs)
        subject = f"[TEST] HKAcadJobs Alert — {len(new_jobs)} new job(s)"
        # A "jobs that fit you" email too, with made-up reasons
        import match_alerts
        fits = [{"job_id": j["id"], "score": 88, "why": "Test: your experience matches this post.", "gaps": []}
                for j in new_jobs[:3]]
        test_row = {"email": args.test_email, "token": "test-token-000", "profile": {"headline": "Test profile"}}
        m_html, m_text = match_alerts.render_match_email(test_row, fits, {j["id"]: j for j in new_jobs})
        m_subject = f"[TEST] {match_alerts.subject_for(len(fits))}"
        if args.dry_run:
            print(f"\nDRY RUN — would send two test emails to {args.test_email}")
            print(f"Subjects: {subject} | {m_subject}")
        else:
            print(f"\nSending test emails to {args.test_email}...")
            result = send_email(args.test_email, subject, html, text)
            print(f"✅ Sent filter alert — id: {result.get('id')}")
            result = send_email(args.test_email, m_subject, m_html, m_text)
            print(f"✅ Sent CV match alert — id: {result.get('id')}")
        return

    if not SUPABASE_SERVICE_KEY or SUPABASE_SERVICE_KEY == "PASTE_SERVICE_ROLE_KEY_HERE":
        print("⚠️  SUPABASE_SERVICE_KEY not set — cannot fetch subscriptions")
        return

    alert_log = load_alert_log()
    failed, too_many_skipped = send_filter_alerts(new_jobs, alert_log, args.dry_run)

    # "Jobs that fit you" emails for saved CV profiles
    import match_alerts
    print("\n── CV match alerts ─────────────────────────────────────")
    failed += match_alerts.run(new_jobs, alert_log, dry_run=args.dry_run)
    match_alerts.purge_usage_log(dry_run=args.dry_run)

    if not args.dry_run:
        save_alert_log(alert_log)
    if failed:
        sys.exit(1)
    if too_many_skipped:
        sys.exit(2)


if __name__ == "__main__":
    main()
