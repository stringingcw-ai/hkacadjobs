"""One-off: run the rewritten HKU scraper against the live site and compare with jobs.csv
(nothing is written): ids that carry over, still-open jobs it no longer finds, new
jobs, and what a job page's description looks like. Removed after use."""

import collections
import csv
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import core
from sites import hku

rows = {r["id"]: r for r in csv.DictReader(open(Path(__file__).parent.parent / "jobs.csv", encoding="utf-8"))}
core._existing_descriptions.update({k: v.get("description", "") for k, v in rows.items()})
old = {k: v for k, v in rows.items() if v["university"] == "HKU"}

jobs = hku.scrape_hku()
ids = {j["id"] for j in jobs}
print(f"\nscraped {len(jobs)}; stored HKU {len(old)}; carried over {len(ids & old.keys())}")
gone = [r for k, r in old.items() if k not in ids]
still_open = [r for r in gone if core.is_active(r["deadline"])]
print(f"stored but not found: {len(gone)}, of which still open: {len(still_open)}")
for r in still_open[:12]:
    print("   ", r["id"], r["deadline"], r["title"][:70])
new = [j for j in jobs if j["id"] not in old]
print(f"new: {len(new)}")
for j in new[:12]:
    print("   ", j["id"], j["deadline"], j["department"][:40], "|", j["title"][:60])
print("no deadline:", sum(not j["deadline"] for j in jobs), "| no ref:", sum(not j["reference"] for j in jobs))
moved = [(j["id"], old[j["id"]]["deadline"], j["deadline"]) for j in jobs
         if j["id"] in old and old[j["id"]]["deadline"] != j["deadline"]]
print(f"deadline differs from stored: {len(moved)}", moved[:8])
depts = collections.Counter((old[j["id"]]["department"], j["department"]) for j in jobs
                            if j["id"] in old and old[j["id"]]["department"] != j["department"])
print(f"department differs: {sum(depts.values())}", depts.most_common(5))
titles = sum(old[j["id"]]["title"] != j["title"] for j in jobs if j["id"] in old)
print(f"title differs: {titles}")
print("ranks:", collections.Counter(j["rank"] for j in jobs).most_common())
for j in new[:3]:
    print(f"\n--- {j['id']} {j['apply_url']}\n{j['description'][:1200]}")

# Where a job page keeps its text, to check description() picks the right part.
html = hku.fetch(jobs[0]["apply_url"], requests.Session())
soup = BeautifulSoup(html, "html.parser")
node = soup.find(string=re.compile(r"Ref\.?\s*:"))
chain, el = [], node.parent if node else None
while el is not None and el.name != "[document]":
    chain.append(el.name + "".join("." + c for c in el.get("class", [])) + (f"#{el['id']}" if el.get("id") else ""))
    el = el.parent
print("\n'Ref.:' text sits in:", " < ".join(chain))
print("main:", bool(soup.select_one("main")), "| header/nav/footer/form:",
      [len(soup.select(t)) for t in ("header", "nav", "footer", "form")])
print("card-like classes:", collections.Counter(" ".join(c.get("class")) for c in soup.select("[class*=card]")).most_common(8))
print(f"\ndescription() of {jobs[0]['apply_url']}:\n{hku.description(html)[:2500]}")
