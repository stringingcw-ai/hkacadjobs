"""Temporary live check of THEi reference numbers (run on GitHub Actions). Writes nothing."""
import re, sys, collections
sys.path.insert(0, "scraper")
import scraper as sc

jobs = sc.scrape_thei()
by_id = collections.defaultdict(list)
for j in jobs:
    by_id[j["id"]].append(j)
print("\nid | ref | title | url slug")
for j in jobs:
    flag = "  <== DUPLICATE" if len(by_id[j["id"]]) > 1 else ""
    print(f"{j['id']} | {j['reference']!r} | {j['title'][:45]} | {j['apply_url'].rstrip('/').rsplit('/', 1)[-1][:60]}{flag}")
print("\nRef-number context in each description:")
for j in jobs:
    m = re.search(r".{0,40}Ref(?:erence)?\.?\s*No.{0,70}", j["description"], re.I | re.S)
    print(f"  {j['id']}: {m.group(0).replace(chr(10), ' ⏎ ') if m else '(no Ref No. text)'}")
