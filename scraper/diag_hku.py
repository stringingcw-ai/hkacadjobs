"""One-off: how HKU's job listing is marked up now (the 20 Nov 2026 run found no
"/en/job/<id>" links in a full page). One plain request only, so AWS WAF doesn't step
in. Read-only; removed after use."""

import re
from collections import Counter

import requests

from core import HEADERS

URL = "https://jobs.hku.hk/en/listing/?page=1&page-items=1000"

resp = requests.get(URL, headers=HEADERS, timeout=60)
html = resp.text
print(f"HTTP {resp.status_code}, {len(html)} chars, WAF {resp.headers.get('x-amzn-waf-action', '-')}")
if resp.status_code != 200:
    raise SystemExit("not a listing page; nothing to inspect")

print("counts:", {tag: len(re.findall(rf"<{tag}\b", html, re.I)) for tag in ("tr", "li", "article", "a", "table")})
hrefs = re.findall(r"""href\s*=\s*["']([^"']*)["']""", html, re.I)
jobish = [h for h in hrefs if re.search(r"job|vacanc|position|opening", h, re.I)]
shapes = Counter(re.sub(r"\d{3,}", "<n>", re.sub(r"/[a-z0-9-]{25,}", "/<slug>", h)) for h in jobish)
print(f"{len(hrefs)} links, {len(jobish)} job-like; most common shapes:")
for shape, n in shapes.most_common(12):
    print(f"  {n:4d}  {shape[:140]}")
print("sample job-like links:", [h[:140] for h in jobish[:8]])

for needle in ("/en/job/", "jobId", "job_id", "data-job", "__NEXT_DATA__", "application/json", "Closing", "Provost"):
    i = html.find(needle)
    print(f"\n--- first {needle!r} at {i}" + ("" if i < 0 else ":"))
    if i >= 0:
        print(re.sub(r"\s+", " ", html[max(0, i - 500):i + 900]))
