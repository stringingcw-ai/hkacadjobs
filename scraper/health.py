"""
health.py
─────────
Fails the daily workflow when a university scraper under-delivers, so problems
surface as a red run (GitHub emails the repo owner) instead of hiding behind a
green tick.

Reads the latest run that scraper.py recorded in scraper/scrape_health.json and
flags any institution that crashed, returned nothing, or returned well below
its usual count (scraper.py has already kept the previous run's rows for those
institutions). Also flags a missing/stale record, a failed notify step, and
jobs.csv rows the site can't use (a deadline that isn't a date, a missing id or
title, a duplicate id).

Prints a per-institution table (and writes it to the GitHub job summary), and if
anything is wrong: emits error annotations, optionally emails HEALTH_ALERT_EMAIL
via Resend, and exits 1.

Usage (from repo root):
  python scraper/health.py
  python scraper/health.py --notify-outcome failure   # as passed by scrape.yml
"""

import argparse
import csv
import json
import re
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

HEALTH_FILE   = Path(__file__).parent / "scrape_health.json"
CSV_PATH      = Path(__file__).parent.parent / "jobs.csv"
MAX_AGE       = timedelta(hours=12)   # the record must come from this workflow run
STATUS_ICON   = {"ok": "✅", "partial": "🟠", "empty": "🔴", "crashed": "🔴"}
STATUS_MEANING = {
    "partial": "returned far fewer jobs than usual",
    "empty":   "returned no jobs",
    "crashed": "crashed",
}


def load_latest_run():
    try:
        runs = json.loads(HEALTH_FILE.read_text(encoding="utf-8")).get("runs", [])
    except (OSError, ValueError):
        return None
    return runs[-1] if runs else None


def find_problems(run, notify_outcome, now):
    problems = []
    if not run:
        return ["scraper.py recorded no run in scraper/scrape_health.json — the scrape step probably crashed"]
    run_at = datetime.fromisoformat(run["run_at"])
    if now - run_at > MAX_AGE:
        problems.append(f"latest scrape record is from {run['run_at']} — today's scrape didn't finish")
    for name, r in run["results"].items():
        if r["status"] != "ok":
            detail = f"{r['university']} {STATUS_MEANING.get(r['status'], r['status'])}: " \
                     f"{r['scraped']} scraped vs ~{r['expected']} usual; " \
                     f"kept {r['kept_from_previous']} jobs from the previous run"
            if r.get("error"):
                detail += f" ({r['error']})"
            problems.append(detail)
    if notify_outcome == "failure":
        problems.append("notify.py failed or skipped most alert subscriptions — see the 'Send job alert emails' step log")
    return problems


def check_csv(path=CSV_PATH):
    """Problems with jobs.csv rows that would break the site or its data."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        return [f"jobs.csv could not be read: {e}"]
    problems = []
    bad_deadline = [r["id"] for r in rows if r.get("deadline") and not re.match(r"^\d{4}-\d{2}-\d{2}$", r["deadline"])]
    if bad_deadline:
        problems.append(f"{len(bad_deadline)} jobs have a deadline that isn't a YYYY-MM-DD date "
                        f"(e.g. {', '.join(bad_deadline[:3])})")
    incomplete = [r.get("id") or "(no id)" for r in rows if not r.get("id") or not r.get("title")]
    if incomplete:
        problems.append(f"{len(incomplete)} jobs have no id or title (e.g. {', '.join(incomplete[:3])})")
    ids = [r.get("id") for r in rows if r.get("id")]
    dupes = sorted({i for i in ids if ids.count(i) > 1}) if len(ids) != len(set(ids)) else []
    if dupes:
        problems.append(f"{len(dupes)} job ids appear more than once (e.g. {', '.join(dupes[:3])})")
    return problems


def render_table(run):
    lines = [
        "| | Institution | Scraped | Usual | Kept from previous run |",
        "|---|---|--:|--:|--:|",
    ]
    for name, r in sorted(run["results"].items(), key=lambda kv: (kv[1]["status"] == "ok", kv[0])):
        lines.append(
            f"| {STATUS_ICON.get(r['status'], '❔')} | {r['university']} | {r['scraped']} | "
            f"{r['expected']} | {r['kept_from_previous'] or ''} |"
        )
    return "\n".join(lines)


def send_alert(problems, table):
    """Email the site owner, if HEALTH_ALERT_EMAIL and RESEND_API_KEY are set."""
    to_email = os.environ.get("HEALTH_ALERT_EMAIL", "").strip()
    if not to_email or not os.environ.get("RESEND_API_KEY"):
        return
    from notify import send_email   # same Resend sender as the job alerts

    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                   f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    text = "HKAcadJobs daily scrape needs attention:\n\n" + "\n".join(f"• {p}" for p in problems)
    text += f"\n\n{table}\n"
    if run_url:
        text += f"\nRun log: {run_url}\n"
    html = "<p>HKAcadJobs daily scrape needs attention:</p><ul>" + \
           "".join(f"<li>{escape(p)}</li>" for p in problems) + "</ul>" + \
           (f'<p><a href="{escape(run_url)}">Open the run log</a></p>' if run_url else "") + \
           f"<pre style=\"font-size:12px\">{escape(table)}</pre>"
    try:
        send_email(to_email, f"⚠️ HKAcadJobs scrape health: {len(problems)} problem(s)", html, text)
        print(f"Alert emailed to {to_email}")
    except Exception as e:
        print(f"::warning::Could not email health alert: {e}")


def main():
    parser = argparse.ArgumentParser(description="Check the latest HKAcadJobs scrape")
    parser.add_argument("--notify-outcome", default="",
                        help="outcome of the notify step (success/failure/skipped)")
    args = parser.parse_args()

    run = load_latest_run()
    problems = find_problems(run, args.notify_outcome, datetime.now(timezone.utc)) + check_csv()
    table = render_table(run) if run else "(no scrape record)"

    print("── HKAcadJobs scrape health ──────────────────────────")
    if run:
        print(f"Run {run['run_at']}: {run.get('total_jobs', '?')} jobs, {run.get('new_jobs', '?')} new")
    print(table)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Scrape health\n\n")
            f.write("\n".join(f"- ⚠️ {p}" for p in problems) + "\n\n" if problems else "All institutions OK.\n\n")
            f.write(table + "\n")

    if not problems:
        print("All institutions OK.")
        return
    for p in problems:
        print(f"::error title=Scrape health::{p}")
    send_alert(problems, table)
    sys.exit(1)


if __name__ == "__main__":
    main()
