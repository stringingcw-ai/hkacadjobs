"""
bootstrap_registry.py
─────────────────────
Rebuilds scraper/job_registry.json (first/last day each job id was scraped)
from the git history of jobs.csv. Run from the repo root with full history:

  git fetch --unshallow   # if the clone is shallow
  python scraper/bootstrap_registry.py

Only needed once, or if the registry file is ever lost; the daily scraper
keeps it up to date afterwards.
"""

import csv
import io
import re
import subprocess
from datetime import datetime, timedelta, timezone

import scraper

HKT = timezone(timedelta(hours=8))
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main():
    log = subprocess.run(["git", "log", "--format=%H %ct", "--", "jobs.csv"],
                         capture_output=True, text=True, check=True).stdout.split()
    commits = list(zip(log[::2], log[1::2]))[::-1]   # oldest first
    registry = {}
    for sha, ts in commits:
        # A run's "today" is the HKT date it ran on
        run = datetime.fromtimestamp(int(ts), HKT).date().isoformat()
        data = subprocess.run(["git", "show", f"{sha}:jobs.csv"], capture_output=True, text=True).stdout
        for row in csv.DictReader(io.StringIO(data)):
            jid = row.get("id")
            if not jid:
                continue
            added = (row.get("date_added") or "").strip()
            first = added if ISO.match(added) and added <= run else run
            if jid in registry:
                f, l = registry[jid]
                registry[jid] = [min(f, first), max(l, run)]
            else:
                registry[jid] = [first, run]
    scraper.save_registry(registry)
    print(f"{len(commits)} snapshots → {len(registry)} job ids → {scraper.REGISTRY_FILE}")


if __name__ == "__main__":
    main()
