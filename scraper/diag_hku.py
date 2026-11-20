"""One-off: HKU's new careers site (since 19/20 Nov 2026). How search results page, what
a result card holds, and whether a job page still shows the old job number. A few plain
requests, spaced out so AWS WAF doesn't step in. Read-only; removed after use."""

import re
import time

import requests
from bs4 import BeautifulSoup

from core import HEADERS


def get(url):
    time.sleep(6)
    resp = requests.get(url, headers=HEADERS, timeout=60)
    print(f"\n=== {url}\nHTTP {resp.status_code}, {len(resp.text)} chars, WAF {resp.headers.get('x-amzn-waf-action', '-')}")
    return resp.text if resp.status_code == 200 else ""


def squash(html, n):
    return re.sub(r"\s+", " ", html)[:n]


for url in ("https://jobs.hku.hk/jobs/search?page-items=1000&page=1",
            "https://jobs.hku.hk/jobs/search?page=2"):
    soup = BeautifulSoup(get(url), "html.parser")
    results = soup.select(".block-job-search-results .job-search-results-card")
    print(f"result cards: {len(results)}; featured cards: {len(soup.select('.featured-jobs .job-search-results-card'))}")
    print("result text:", squash(soup.select_one(".block-job-search-results").get_text(" ") if soup.select_one(".block-job-search-results") else "", 300))
    print("paging links:", sorted({a['href'] for a in soup.select("a[href*='page=']")})[:10])
    if results and url.endswith("page=1"):
        print("first card:", squash(str(results[0]), 3000))
        print("li classes:", sorted({c for li in soup.select(".job-search-results-card li") for c in li.get("class", [])}))
        first_job = results[0].select_one("a[href*='/jobs/']")["href"]

page = BeautifulSoup(get(first_job), "html.parser")
text = squash(page.get_text(" "), 100000)
for needle in ("Job Number", "Job number", "Job No", "Reference", "Ref", "Requisition", "Closing", "Faculty", "Department"):
    i = text.find(needle)
    if i >= 0:
        print(f"detail {needle!r}: …{text[max(0, i - 80):i + 160]}…")
print("detail /en/job/ links:", re.findall(r"/en/job/\d+[^\"' ]*", str(page))[:5])
print("detail meta:", [(m.get("property") or m.get("name"), (m.get("content") or "")[:120]) for m in page.find_all("meta") if m.get("content")][:12])
print("detail text start:", text[:1200])
