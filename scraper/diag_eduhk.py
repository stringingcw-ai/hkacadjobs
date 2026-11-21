"""One-off: the 21 Nov 2026 run got 0 jobs in EdUHK's Academic category (usually
~22). Does the page fill in later than the scraper's fixed 3 s wait, or is it empty?
What does an empty category show, and what data requests does the page make?
Read-only; removed after use."""

import re
import time

from playwright.sync_api import sync_playwright

BASE = "https://www.eduhk.hk/en/current-openings?category={}&department=&q="
CATEGORIES = ["senior-management", "deanship-headship-appointments",
              "academic-teaching-posts", "research-support-posts"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for cat in CATEGORIES:
        page = browser.new_page()
        requests = []
        page.on("response", lambda r: requests.append((r.request.resource_type, r.status, r.url[:140]))
                if r.request.resource_type in ("xhr", "fetch") else None)
        start = time.time()
        resp = page.goto(BASE.format(cat), timeout=60000, wait_until="domcontentloaded")
        print(f"\n=== {cat}: HTTP {resp.status if resp else '?'}")
        for t in (1, 3, 6, 10, 20):
            page.wait_for_timeout(max(0, (start + t - time.time()) * 1000))
            body = page.inner_text("body")
            pdfs = page.evaluate("document.querySelectorAll('a[href*=\"/cms/f/career\"]').length")
            print(f"  after {t:>2}s: {body.count('Ad Date:')} 'Ad Date:', {pdfs} PDF links")
        body = page.inner_text("body")
        i = body.find("Ad Date:")
        around = body[max(0, i - 300):i + 200] if i >= 0 else body[:100]
        print("  text around the first job (or page start):", re.sub(r"\s+", " ", around)[:500])
        if i < 0:
            for needle in ("No ", "no result", "not found", "currently", "There is", "There are"):
                j = body.find(needle)
                if j >= 0:
                    print(f"  empty-state text near {needle!r}:", re.sub(r"\s+", " ", body[max(0, j - 80):j + 160]))
        print("  data requests:", requests[:12])
        page.close()
    browser.close()
