"""One-off: AWS WAF challenged HKU's 7th quick plain request in the last check. Does a
headless browser (its own user agent, no override) get through the challenge and walk
past page 6? And does page 1 offer a cheaper way to list every job (a page-size
option, a feed, an API)? Read-only; removed after use."""

import re
import time

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SEARCH = "https://jobs.hku.hk/jobs/search?page={}"
CARDS = ".block-job-search-results .job-search-results-card"

first_html, cookies, agent = "", [], ""
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chromium", headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    agent = page.evaluate("navigator.userAgent")
    print("browser user agent:", agent, "| webdriver:", page.evaluate("navigator.webdriver"))
    for n in range(1, 10):
        start = time.time()
        resp = page.goto(SEARCH.format(n), timeout=60000, wait_until="domcontentloaded")
        status = resp.status if resp else "?"
        try:
            page.wait_for_selector(CARDS, timeout=30000)
            outcome = f"{page.locator(CARDS).count()} cards"
        except Exception:
            outcome = "no cards after 30 s"
        print(f"browser page {n}: first response HTTP {status}, {outcome}, title {page.title()[:60]!r}, "
              f"{time.time() - start:.1f}s, cookies {sorted(c['name'] for c in ctx.cookies())}")
        if n == 1:
            first_html = page.content()
        if "no cards" in outcome:
            print("   text:", " ".join(page.inner_text("body").split())[:200])
            break
        time.sleep(3)
    cookies = ctx.cookies()
    browser.close()

# With the browser's token cookie, are plain requests let through too?
session = requests.Session()
for c in cookies:
    session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
for n in (10, 11, 12):
    time.sleep(3)
    r = session.get(SEARCH.format(n), headers={"User-Agent": agent, "Accept-Language": "en-US,en;q=0.9"}, timeout=60)
    cards = len(BeautifulSoup(r.text, "html.parser").select(CARDS))
    print(f"plain page {n} with browser cookies: HTTP {r.status_code}, WAF {r.headers.get('x-amzn-waf-action', '-')}, {cards} cards")

# What page 1 offers besides 30 cards a page.
soup = BeautifulSoup(first_html, "html.parser")
print("\nalternate/feed links:", [(l.get("type"), l.get("href")) for l in soup.select("link[rel=alternate], a[href*=rss], a[href*=feed], a[href*='.xml'], a[href*='.json']")][:10])
print("generator/app meta:", [(m.get("name"), m.get("content")) for m in soup.select("meta[name]") if m.get("name") not in ("viewport", "csrf-token", "csrf-param", "description")][:10])
print("scripts:", [s["src"][:100] for s in soup.select("script[src]")][:8])
for form in soup.select("form"):
    fields = [(f.name, f.get("name"), [o.get("value") for o in f.select("option")][:8]) for f in form.select("input[name], select[name]")]
    print(f"form {form.get('action')!r} {form.get('method')!r}: {fields[:15]}")
print("data-*url* attributes:", sorted({f"{k}={v[:80]}" for el in soup.find_all(True) for k, v in el.attrs.items()
                                         if k.startswith("data-") and "url" in k and isinstance(v, str)})[:15])
print("'/api' mentions:", sorted(set(re.findall(r"[\"'](/[^\"' ]*api[^\"' ]*)[\"']", first_html)))[:10])
print("per-page mentions:", sorted(set(m.lower() for m in re.findall(r"per[-_ ]?page|page[-_]?size|items[-_ ]per[-_ ]page|results per page|page-items", first_html, re.I))))
total = re.search(r"[\d,]+\s+(?:jobs|results|positions|openings)\b[^<]{0,40}", soup.get_text(" "), re.I)
print("result total text:", total.group(0) if total else None)
pager = soup.select_one("nav[aria-label*=agination], .pagination, [class*=paginat]")
print("pagination block:", re.sub(r"\s+", " ", str(pager))[:1500] if pager else None)
