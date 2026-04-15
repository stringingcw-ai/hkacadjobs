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
import json
import os
import re
import secrets
import ssl
import time
import urllib.request
import urllib.parse
from datetime import date
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


def get_subscriptions():
    return _supabase_request("GET", "subscriptions?select=*", use_service_key=True)


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


# ── Job loading ───────────────────────────────────────────────────────────────

def load_new_jobs():
    jobs = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("is_new", "").upper() == "TRUE":
                jobs.append(row)
    return jobs


# ── Filter matching ───────────────────────────────────────────────────────────

def job_matches_filter(job, state):
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

    # Area filter (maps to position_type)
    area = state.get("area", "")
    if area and job.get("position_type", "") != area:
        return False

    # Keyword search (title + department + description)
    search = state.get("search", "").lower().strip()
    if search:
        haystack = f"{job['title']} {job.get('department', '')} {job.get('description', '')}".lower()
        if not all(word in haystack for word in search.split()):
            return False

    return True


def match_jobs_to_subscriptions(new_jobs, subscriptions):
    """Return list of (subscription, matched_jobs) for subscriptions with ≥1 match."""
    results = []
    for sub in subscriptions:
        state = sub.get("filter_state") or {}
        if isinstance(state, str):
            state = json.loads(state)
        matched = [j for j in new_jobs if job_matches_filter(j, state)]
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


def render_email(sub, jobs):
    label     = sub.get("filter_label", "Your filter")
    token     = sub.get("token", "")
    unsub_url = f"{SITE_URL}/?unsubscribe={token}"
    today     = date.today().strftime("%d %b %Y")
    count     = len(jobs)

    rows_html = ""
    for j in jobs:
        uni    = UNI_DISPLAY.get(j["university"], j["university"])
        dl     = j.get("deadline", "")
        dl_str = f" · Deadline: {dl}" if dl else ""
        url    = j.get("apply_url", SITE_URL)
        rows_html += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #e8e4da;">
            <div style="font-weight:600;color:#1a1a1a;margin-bottom:4px;">
              <a href="{SITE_URL}" style="color:#1a1a1a;text-decoration:none;">{j['title']}</a>
            </div>
            <div style="font-size:13px;color:#6b6560;">{uni} · {j.get('rank','')}{dl_str}</div>
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
        <tr><td style="background:#1a1a1a;padding:24px 32px;">
          <span style="font-size:18px;font-weight:700;color:#fff;letter-spacing:-0.3px;">HKAcadJobs</span>
          <span style="font-size:13px;color:#888;margin-left:12px;">Job Alert</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 8px;font-size:14px;color:#6b6560;">{today}</p>
          <h1 style="margin:0 0 6px;font-size:20px;font-weight:700;color:#1a1a1a;">
            {count} new job{'s' if count != 1 else ''} matching <em style="font-style:italic;">"{label}"</em>
          </h1>
          <p style="margin:0 0 24px;font-size:13px;color:#6b6560;">
            New postings added today that match your saved filter.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0">
            {rows_html}
          </table>

          <div style="margin-top:28px;">
            <a href="{SITE_URL}"
               style="display:inline-block;background:#1a1a1a;color:#fff;padding:11px 22px;border-radius:7px;font-size:14px;font-weight:600;text-decoration:none;">
              View all jobs →
            </a>
          </div>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f5f2eb;padding:20px 32px;border-top:1px solid #e8e4da;">
          <p style="margin:0;font-size:12px;color:#9c9690;line-height:1.6;">
            You're receiving this because you set up a job alert on HKAcadJobs.<br>
            <a href="{unsub_url}" style="color:#9c9690;">Unsubscribe</a> ·
            <a href="{SITE_URL}" style="color:#9c9690;">hkacadjobs.org</a>
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
        dl  = j.get("deadline", "")
        dl_str = f" | Deadline: {dl}" if dl else ""
        text += f"• {j['title']}\n  {uni} · {j.get('rank','')}{dl_str}\n\n"

    text += f"\nView all jobs: {SITE_URL}\nUnsubscribe: {unsub_url}\n"
    return html, text


# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(to_email, subject, html, text):
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not set")
    payload = json.dumps({
        "from": f"HKAcadJobs <{FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": text,
    }).encode()
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
        if args.dry_run:
            print(f"\nDRY RUN — would send test email to {args.test_email}")
            print(f"Subject: {subject}")
        else:
            print(f"\nSending test email to {args.test_email}...")
            result = send_email(args.test_email, subject, html, text)
            print(f"✅ Sent — id: {result.get('id')}")
        return

    # Fetch subscriptions
    if not SUPABASE_SERVICE_KEY or SUPABASE_SERVICE_KEY == "PASTE_SERVICE_ROLE_KEY_HERE":
        print("⚠️  SUPABASE_SERVICE_KEY not set — cannot fetch subscriptions")
        return
    subs = get_subscriptions()
    print(f"Subscriptions: {len(subs)}")
    if not subs:
        print("No subscribers yet.")
        return

    # Match
    matches = match_jobs_to_subscriptions(new_jobs, subs)
    print(f"Subscribers with matches: {len(matches)}")

    # Group by email so each subscriber gets one digest (not one per filter)
    by_email = {}
    for sub, jobs in matches:
        email = sub["email"]
        if email not in by_email:
            by_email[email] = {"sub": sub, "jobs": [], "labels": []}
        seen_ids = {j["id"] for j in by_email[email]["jobs"]}
        for j in jobs:
            if j["id"] not in seen_ids:
                by_email[email]["jobs"].append(j)
                seen_ids.add(j["id"])
        by_email[email]["labels"].append(sub.get("filter_label", "Your filter"))
    print(f"Unique recipients: {len(by_email)}")

    sent = 0
    for email, info in by_email.items():
        combined_label = " + ".join(dict.fromkeys(info["labels"]))
        merged_sub = {**info["sub"], "filter_label": combined_label}
        jobs = info["jobs"]
        subject = f"HKAcadJobs: {len(jobs)} new job{'s' if len(jobs) != 1 else ''} matching \"{combined_label}\""
        html, text = render_email(merged_sub, jobs)

        if args.dry_run:
            print(f"\n  → {email} | {combined_label} | {len(jobs)} match(es):")
            for j in jobs:
                print(f"      • {j['title']} ({j['university']})")
        else:
            try:
                send_email(email, subject, html, text)
                print(f"  ✅ Sent to {email} ({len(jobs)} jobs)")
                sent += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  ❌ Failed for {email}: {e}")

    if not args.dry_run:
        print(f"\n── Done: {sent}/{len(by_email)} emails sent")


if __name__ == "__main__":
    main()
