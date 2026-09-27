"""
wait_for_deploy.py
──────────────────
Waits (up to 8 minutes) until one of today's new job pages is live on the
site, so alert emails never link to a page GitHub Pages hasn't deployed yet.
Best effort: it never fails the workflow.

Run from the repo root after the data commit is pushed:
  python scraper/wait_for_deploy.py
"""

import csv
import time
import urllib.request
from pathlib import Path

from generate_job_pages import BASE_URL, job_dir_name, is_active

CSV_PATH = Path(__file__).parent.parent / "jobs.csv"
MAX_WAIT = 8 * 60


def main(max_wait=MAX_WAIT, poll=20):
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        new = [r for r in csv.DictReader(f) if r.get("is_new") == "TRUE" and is_active(r)]
    if not new:
        print("No new jobs today — nothing to wait for")
        return True
    # A unique query string skips any cached 404 from before the deploy
    url = f"{BASE_URL}/jobs/{job_dir_name(new[0])}/?deploy-check={int(time.time())}"
    give_up = time.time() + max_wait
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HKAcadJobs deploy check"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    print(f"New job pages are live ({url.split('?')[0]})")
                    return True
        except Exception:
            pass
        if time.time() >= give_up:
            print(f"::warning::New job pages not live after {max_wait // 60} min; sending alerts anyway")
            return False
        time.sleep(poll)


if __name__ == "__main__":
    main()
