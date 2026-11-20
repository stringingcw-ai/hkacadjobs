"""One-off: what HKU's job listing returns to a GitHub runner, as a plain request and
in a browser (the 20 Nov 2026 run got a page with no job links). Read-only; removed after use."""

import re

import requests

from core import HEADERS
from sites.hku import fetch_listing

URL = "https://jobs.hku.hk/en/listing/?page=1&page-items=1000"


def summary(html):
    title = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    links = len(set(re.findall(r'href="/en/job/(\d+)', html or "")))
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I))
    return f"{links} job links, title {title.group(1).strip()[:80] if title else '(none)'!r}, " \
           f"text {' '.join(text.split())[:160]!r}"


for attempt in (1, 2, 3):
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=60)
    except requests.RequestException as e:
        print(f"plain request {attempt}: failed ({e})")
        continue
    kept = {k: v for k, v in resp.headers.items() if k.lower().startswith(("x-amz", "server", "content-type", "x-cache"))}
    print(f"plain request {attempt}: HTTP {resp.status_code}, {len(resp.text)} chars, {summary(resp.text)}")
    print(f"  headers: {kept}")

print("fetch_listing():", "used the plain request" if fetch_listing(URL) else "fell back to the browser")

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_extra_http_headers(HEADERS)
    resp = page.goto(URL, timeout=60000, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("a[href*='/en/job/']", timeout=30000)
    except Exception as e:
        print(f"browser: job links didn't appear ({str(e).splitlines()[0]})")
    print(f"browser: HTTP {resp.status if resp else '?'}, {summary(page.content())}")
    browser.close()
