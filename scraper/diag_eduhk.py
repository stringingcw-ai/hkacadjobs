"""One-off: dry run of the EdUHK scraper with the new page wait (_open_category)
against the live site, compared with jobs.csv (nothing is written). Removed after use."""

import csv
import time
from pathlib import Path

import core
from sites.eduhk import scrape_eduhk

rows = {r["id"]: r for r in csv.DictReader(open(Path(__file__).parent.parent / "jobs.csv", encoding="utf-8"))}
core._existing_descriptions.update({k: v.get("description", "") for k, v in rows.items()})
old = {k for k, v in rows.items() if v["university"] == "EdUHK"}

start = time.time()
jobs = scrape_eduhk()
ids = {j["id"] for j in jobs}
print(f"\ntook {time.time() - start:.0f}s; scraped {len(jobs)}; stored EdUHK {len(old)}; "
      f"carried over {len(ids & old)}; new {len(ids - old)}; stored not found {len(old - ids)}")
for jid in sorted(old - ids):
    r = rows[jid]
    print("   not found:", jid, r["deadline"] or "-", r["title"][:70])
for j in jobs:
    if j["id"] not in old:
        print("   new:", j["id"], j["deadline"] or "-", j["title"][:70])
