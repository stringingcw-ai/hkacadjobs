"""
check_links.py
──────────────
Weekly check that every job's Apply link still opens. It runs from GitHub's
runners, because university sites refuse many other networks.

Writes a per-institution summary to the workflow run page. Exits 1 (so GitHub
emails the repo owner) when links look broken for an institution, and also
emails HEALTH_ALERT_EMAIL through Resend when that secret is set.

  python scraper/check_links.py
"""

import csv
import os
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

import requests

CSV_PATH = Path(__file__).parent.parent / "jobs.csv"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TIMEOUT = 25
WORKERS = 16
PER_HOST = 3                 # be gentle with each university's server
MAX_BROKEN_SHARE = 0.2       # alert when more than this share of an institution's links fail...
MIN_BROKEN = 3               # ...and at least this many do
BLOCKED = {401, 403, 429}    # bot protection: not proof the page is gone

_host_locks = defaultdict(lambda: threading.BoundedSemaphore(PER_HOST))


def check(url: str):
    """(verdict, detail) where verdict is ok / blocked / broken."""
    host = urlsplit(url).netloc
    detail = ""
    with _host_locks[host]:
        for attempt in range(2):
            try:
                resp = requests.head(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
                if resp.status_code >= 400:
                    # Many servers mishandle HEAD; ask again with a real GET
                    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT,
                                        allow_redirects=True, stream=True)
                    resp.close()
                if resp.status_code < 400:
                    return "ok", str(resp.status_code)
                if resp.status_code in BLOCKED:
                    return "blocked", str(resp.status_code)
                if resp.status_code < 500:
                    return "broken", f"HTTP {resp.status_code}"
                detail = f"HTTP {resp.status_code}"
            except requests.RequestException as e:
                detail = type(e).__name__
    return "broken", detail


def load_jobs():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    jobs = load_jobs()
    urls = {}
    no_link = Counter()
    for j in jobs:
        url = (j.get("apply_url") or "").split("#")[0].strip()
        if url.startswith(("http://", "https://")):
            urls.setdefault(url, []).append(j)
        else:
            no_link[j["university"]] += 1

    with ThreadPoolExecutor(WORKERS) as pool:
        results = dict(zip(urls, pool.map(check, urls)))

    per_uni = defaultdict(Counter)
    broken = []
    for url, (verdict, detail) in results.items():
        for j in urls[url]:
            per_uni[j["university"]][verdict] += 1
            if verdict == "broken":
                broken.append((j["university"], j["id"], j["title"], url, detail))
    for uni, n in no_link.items():
        per_uni[uni]["missing"] += n

    problems = []
    lines = ["| Institution | Links | OK | Blocked (403/429) | Broken | No link |", "|---|--:|--:|--:|--:|--:|"]
    for uni in sorted(per_uni):
        c = per_uni[uni]
        total = c["ok"] + c["blocked"] + c["broken"]
        lines.append(f"| {uni} | {total} | {c['ok']} | {c['blocked']} | {c['broken']} | {c['missing']} |")
        if c["broken"] >= MIN_BROKEN and c["broken"] > MAX_BROKEN_SHARE * total:
            problems.append(f"{uni}: {c['broken']} of {total} apply links fail")
    table = "\n".join(lines)
    listing = "\n".join(f"- {uni} {jid}: {title[:70]} — {detail} — {url}"
                        for uni, jid, title, url, detail in sorted(broken)[:150])

    report = f"## Apply-link check\n\n{len(urls)} distinct links for {len(jobs)} jobs.\n\n{table}\n"
    if broken:
        report += f"\n### Broken links ({len(broken)})\n\n{listing}\n"
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report)

    if not problems:
        print("No institution has an unusual number of broken links.")
        return 0
    for p in problems:
        print(f"::error::{p}")
    to_email = os.environ.get("HEALTH_ALERT_EMAIL", "").strip()
    if to_email and os.environ.get("RESEND_API_KEY"):
        from notify import send_email
        html = ("<p>HKAcadJobs weekly link check found broken Apply links:</p><ul>"
                + "".join(f"<li>{escape(p)}</li>" for p in problems) + "</ul>"
                + f"<pre style=\"font-size:12px\">{escape(table)}\n\n{escape(listing)}</pre>")
        try:
            send_email(to_email, f"⚠️ HKAcadJobs: broken apply links at {len(problems)} institution(s)",
                       html, report)
        except Exception as e:
            print(f"::warning::Could not email link report: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
