"""Temporary: compare the fresh scrape with the published data."""
import csv, json, re, collections
from pathlib import Path
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
def load(p):
    return {r["id"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}
before, after = load("/tmp/before.csv"), load("jobs.csv")
unis = sorted({r["university"] for r in list(before.values()) + list(after.values())})
print(f"TOTAL before {len(before)} after {len(after)}; NEW {sum(r['is_new'] == 'TRUE' for r in after.values())}")
print(f"{'uni':9s} {'before':>6s} {'after':>6s} {'same':>5s} {'added':>5s} {'gone':>5s} {'NEW':>4s} {'dl':>4s} {'note':>4s} {'none':>4s} {'summ':>4s} {'url~':>4s} {'date~':>5s}")
for u in unis:
    b = {i for i, r in before.items() if r["university"] == u}
    a = {i for i, r in after.items() if r["university"] == u}
    ar = [after[i] for i in a]
    url_changed = sum(before[i]["apply_url"] != after[i]["apply_url"] for i in a & b)
    date_changed = sum(before[i]["date_added"] != after[i]["date_added"] for i in a & b)
    print(f"{u:9s} {len(b):6d} {len(a):6d} {len(a & b):5d} {len(a - b):5d} {len(b - a):5d} "
          f"{sum(r['is_new'] == 'TRUE' for r in ar):4d} {sum(bool(ISO.match(r['deadline'])) for r in ar):4d} "
          f"{sum(bool(r.get('deadline_note')) for r in ar):4d} {sum(not r['deadline'] and not r.get('deadline_note') for r in ar):4d} "
          f"{sum(r['description'].startswith('**') for r in ar):4d} {url_changed:4d} {date_changed:5d}")
for u in unis:
    b = {i for i, r in before.items() if r["university"] == u}
    a = {i for i, r in after.items() if r["university"] == u}
    if a - b or b - a:
        print(f"\n== {u}: added {len(a - b)}, gone {len(b - a)}")
        for i in sorted(a - b)[:8]:
            r = after[i]; print(f"  + {i} | {r['title'][:60]} | dl={r['deadline']} note={r.get('deadline_note','')[:40]} | new={r['is_new']} added={r['date_added']}")
        for i in sorted(b - a)[:8]:
            r = before[i]; print(f"  - {i} | {r['title'][:60]} | dl={r['deadline']}")
print("\n== deadline notes (sample per uni)")
notes = collections.defaultdict(collections.Counter)
for r in after.values():
    if r.get("deadline_note"): notes[r["university"]][r["deadline_note"][:60]] += 1
for u, c in sorted(notes.items()): print(" ", u, dict(c.most_common(4)))
print("\n== apply_url samples (SFU, HKCHC, HKUST, CPCE, HKBU, LU)")
for u in ["SFU", "HKCHC", "HKUST", "CPCE", "HKBU", "LU"]:
    for r in [r for r in after.values() if r["university"] == u][:2]:
        print(f"  {u}: {r['apply_url'][:150]}")
print("\n== position_type / rank (CPCE, HKCHC)")
for u in ["CPCE", "HKCHC"]:
    rs = [r for r in after.values() if r["university"] == u]
    print(" ", u, collections.Counter(r["position_type"] for r in rs), collections.Counter(r["rank"] for r in rs))
print("\n== empty fields:", {k: sum(not r[k] for r in after.values()) for k in ["title", "department", "apply_url", "description", "date_added"]})
print("== salary", sum(bool(r["salary"]) for r in after.values()), "start_date", sum(bool(r["start_date"]) for r in after.values()))
bad_dates = [r["id"] for r in after.values() if r["deadline"] and not ISO.match(r["deadline"])]
print("== non-ISO deadlines:", len(bad_dates), bad_dates[:5])
h = json.loads(Path("scraper/scrape_health.json").read_text())["runs"][-1]
print("\n== health", {k: (v["status"], v["scraped"], v["expected"]) for k, v in h["results"].items()})
m = json.loads(Path("scraper/pages_manifest.json").read_text())
print("\n== pages", collections.Counter(v["status"] for v in m.values()), "dirs", sum(1 for p in Path("jobs").iterdir() if p.is_dir()))
lite = list(csv.DictReader(open("jobs-lite.csv", encoding="utf-8")))
print("== lite rows", len(lite), "cols", len(lite[0]))
bad = 0
for d in list(m)[:2000]:
    t = (Path("jobs") / d / "index.html").read_text(encoding="utf-8")
    for blob in re.findall(r'<script type="application/ld\+json">\n(.*?)\n  </script>', t, re.S):
        try: json.loads(blob)
        except Exception: bad += 1
print("== JSON-LD parse failures:", bad)
idx = Path("index.html").read_text(encoding="utf-8")
print("== index latest links:", len(re.findall(r'<li><a href="/jobs/', idx)))
