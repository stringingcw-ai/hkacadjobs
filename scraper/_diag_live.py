"""Temporary live check of the rewritten THEi and HKU scrapers (run on GitHub Actions).
Runs the real scraper functions and compares them with the current jobs.csv. Writes nothing."""
import csv, sys, time, collections
sys.path.insert(0, "scraper")
import scraper as sc

existing = {r["id"]: r for r in csv.DictReader(open("jobs.csv", encoding="utf-8"))}
sc._existing_descriptions = {k: r.get("description", "") for k, r in existing.items()}

for name, code in (("thei", "THEI"), ("hku", "HKU")):
    print(f"\n{'=' * 20} {name} {'=' * 20}", flush=True)
    t0 = time.time()
    jobs = getattr(sc, f"scrape_{name}")()
    ids = {j["id"] for j in jobs}
    prev = {k for k, r in existing.items() if r["university"] == code}
    print(f"took {time.time() - t0:.0f}s; scraped {len(jobs)} jobs; duplicate ids: {len(jobs) - len(ids)}")
    print(f"vs current CSV ({len(prev)} rows): kept same id {len(ids & prev)}, new ids {len(ids - prev)}, gone {len(prev - ids)}")
    print("fields filled:", {k: sum(1 for j in jobs if j.get(k)) for k in ("title", "department", "deadline", "reference", "apply_url", "description")})
    print("ranks:", dict(collections.Counter(j["rank"] for j in jobs).most_common()))
    for j in jobs[:6]:
        print(f"  {j['id']:<22} | {j['title'][:60]:<60} | {j['department'][:35]:<35} | {j['deadline'] or '-':<10} | {j['apply_url'][:70]}")
    new_ids = sorted(ids - prev)[:8]
    if new_ids:
        print("  new ids sample:", [(i, next(j['title'][:40] for j in jobs if j['id'] == i)) for i in new_ids])
    gone = sorted(prev - ids)[:8]
    if gone:
        print("  gone sample:", [(i, existing[i]['title'][:40], existing[i]['date_added']) for i in gone])
