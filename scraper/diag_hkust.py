"""One-off: HKUST academic jobs carried the next card's Interfolio link. On the live
listing pages, compare the old mapping (link -> Job ID seen before it) with the new
one (link inside the job's own card), show a card's HTML, and open a few of the new
links to check they are the right job. Read-only; removed after use."""

import re

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from core import HEADERS
from sites.hkust import _open_listing, interfolio_links

OLD_JS = """() => { const result = {}; const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ALL);
  let currentJobId = null; let node;
  while (node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) { const m = node.textContent.trim().match(/^Job ID: (\\d+)$/); if (m) currentJobId = m[1]; }
    else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'A') { const href = node.href || '';
      if (currentJobId && href.includes('interfolio') && !result[currentJobId]) result[currentJobId] = href; } }
  return result; }"""

URLS = ["https://hkustcareers.hkust.edu.hk/join-us/current-opening/academic-careers",
        "https://hkustcareers.hkust.edu.hk/join-us/current-opening/teaching-support"]

checks = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for url in URLS:
        page = browser.new_page()
        page.set_extra_http_headers(HEADERS)
        _open_listing(page, url)
        html = page.content()
        old, new = page.evaluate(OLD_JS), interfolio_links(html, url)
        text = page.inner_text("body")
        refs = list(dict.fromkeys(re.findall(r"Job ID: (\d+)", text)))
        titles = {}
        for m in re.finditer(r"Job ID: (\d+)", text):
            lines = [l.strip() for l in text[max(0, m.start() - 300):m.start()].splitlines() if l.strip()]
            titles.setdefault(m.group(1), next((l for l in reversed(lines) if not re.search(r"\(\d+\)$", l) and len(l) > 4), ""))
        same = sum(old.get(r) == new.get(r) for r in refs)
        print(f"\n=== {url.rsplit('/', 1)[1]}: {len(refs)} jobs; old links {len(old)}, new links {len(new)}, same {same}")
        for r in refs[:6] + refs[-2:]:
            print(f"  {r} {titles[r][:45]:45} old {str(old.get(r))[-7:]:>7}  new {str(new.get(r))[-7:]:>7}")
        soup = BeautifulSoup(html, "html.parser")
        first = soup.find(string=re.compile(r"^\s*Job ID:\s*" + refs[0]))
        card = first.parent
        while card.parent is not None and len(re.findall(r"Job ID:\s*\d+", card.parent.get_text())) == 1:
            card = card.parent
        print("  first card:", re.sub(r"\s+", " ", str(card))[:1800])
        checks += [(r, titles[r], new[r]) for r in refs if r in new][:3]
        page.close()
    page = browser.new_page()
    for ref, title, link in checks:
        try:
            page.goto(link, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)
            body = " ".join(page.inner_text("body").split())
        except Exception as e:
            body = f"(failed: {e})"
        words = [w for w in re.findall(r"[A-Za-z]{5,}", title)]
        hit = sum(w.lower() in body.lower() for w in words)
        print(f"\n{ref} '{title[:60]}' -> {link}\n  title words on the page: {hit}/{len(words)}; page starts: {body[:300]}")
    browser.close()
