"""Temporary: run the HKUST scraper live with the published data as its cache."""
import csv, time
import core
from sites.hkust import scrape_hkust
rows = {r["id"]: r for r in csv.DictReader(open("../jobs.csv", encoding="utf-8"))}
core._existing_descriptions.update({i: r["description"] for i, r in rows.items()})
core._previous_rows.update(rows)
t = time.time()
jobs = scrape_hkust()
print(f"took {time.time() - t:.0f}s; {len(jobs)} jobs")
thin = [j for j in jobs if "Please visit the application link" in j["description"]]
raw = [j for j in jobs if not j["description"].startswith("**") and j not in thin]
print(f"summaries {sum(j['description'].startswith('**') for j in jobs)}, new raw text {len(raw)}, still thin {len(thin)}")
for j in raw[:3]:
    print("-", j["id"], len(j["description"]), j["description"][:300].replace("\n", " | "))
for j in thin[:5]:
    print("thin:", j["id"], j["apply_url"][:110])
