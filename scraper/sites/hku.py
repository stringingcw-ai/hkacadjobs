"""University of Hong Kong: job scraper."""

import math
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import (
    BOT_MARKERS, clean, detect_rank, detect_type, is_active, is_within_retention,
    make_id, parse_date_text, PLACEHOLDER_MARKER, _existing_descriptions, _has_good_desc,
)

BASE = "https://jobs.hku.hk"
# HKU's careers site since 19/20 Nov 2026: 30 jobs per search page (page-items is
# ignored), about 16 pages. Job pages moved from /en/job/<number> to /jobs/<slug>-<uuid>,
# but every card still shows the job number (requisition identifier), so ids carry over.
SEARCH = BASE + "/jobs/search?page={}"
CARDS = ".block-job-search-results .job-search-results-card"
JOB_PAGE_READY = "[class*='job-component']"
MAX_PAGES = 60      # safety stop, about 1,800 jobs
MAX_DETAILS = 40    # job pages read per run; the rest are read on later runs
PAUSE = (2, 4)      # seconds between pages, to go easy on the site
RETRY_WAIT = 30     # seconds before trying a page again

ADMIN_KEYWORDS = {
    "administrative assistant", "clerical assistant",
    "finance officer", "it officer", "facilities manager",
    "procurement officer", "human resources officer",
    "security officer", "safety officer", "receptionist",
    "estate manager", "accounting officer", "payroll officer",
}

RANK_PRIORITY = {
    "Tenure-Track": 0, "Professor": 1, "Associate Professor": 2,
    "Assistant Professor": 3, "Senior Lecturer/Lecturer": 4, "Lecturer": 4,
    "Postdoctoral": 5, "Research Assistant/Associate": 6,
}


def open_page(page, url, ready, sleep=time.sleep, retries=2):
    """The HTML of `url` in the browser once `ready` (a CSS selector) is on it.

    The site is behind AWS WAF, which challenges clients without a token: plain
    requests get a challenge page after about five. Its pages load AWS's script that
    gets a browser that token, so the scrape uses a browser, with its own user agent.
    A page that doesn't show up is tried again after a wait; then this raises."""
    problem = ""
    for attempt in range(retries + 1):
        sleep(random.uniform(*PAUSE) if attempt == 0 else RETRY_WAIT * attempt)
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector(ready, timeout=30000)
            return page.content()
        except Exception as e:  # Playwright timeouts and network errors
            problem = str(e).splitlines()[0][:120] if str(e) else type(e).__name__
            try:
                problem += f"; page title {page.title()!r}"
            except Exception:
                pass
        print(f"  ⚠️  {url}: {problem}" + ("; waiting to retry" if attempt < retries else ""))
    raise RuntimeError(f"{url} didn't load ({problem})")


def closing_date(text):
    """'Closing on: Dec 10 2026' → '2026-12-10'; '' if there's no date."""
    text = re.sub(r"^closing on:?\s*", "", clean(text), flags=re.I)
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    parsed = parse_date_text(text)
    return parsed if parsed != text else ""


def parse_cards(html):
    """The search results on one page (not the Featured Jobs above them), as job rows."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(CARDS):
        link = card.select_one(".job-search-results-card-title a[href]")
        if not link:
            continue
        title = clean(link.get_text())
        if len(title) < 5:
            continue

        def field(name):
            span = card.select_one(f"li.job-component-{name} span")
            return clean(span.get_text()) if span else ""

        ref = field("requisition-identifier")
        dept = field("department") or field("dropdown-field-1") or "University of Hong Kong"
        deadline = closing_date(field("closing-on"))
        jobs.append({
            "id":               make_id("HKU", ref or title[:25]),
            "title":            title,
            "rank":             detect_rank(title),
            "university":       "HKU",
            "university_full":  "University of Hong Kong",
            "department":       dept,
            "deadline":         deadline,
            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
            "reference":        ref,
            "position_type":    detect_type(title),
            "salary":           "",
            "start_date":       "",
            "apply_url":        urljoin(BASE, link["href"]),
            "description":      f"{title} — {dept}. {PLACEHOLDER_MARKER} for full details.",
        })
    return jobs


def search_total(html):
    """The search's job count ('Displaying 1 - 30 of 451 in total'), or None."""
    counts = BeautifulSoup(html, "html.parser").select_one(".table-counts")
    m = re.search(r"of\s+([\d,]+)\s+in total", clean(counts.get_text()) if counts else "")
    return int(m.group(1).replace(",", "")) if m else None


def last_page(html):
    """The highest page number the search's paging links on this page point to."""
    soup = BeautifulSoup(html, "html.parser")
    pages = [int(m.group(1)) for a in soup.select("a[href*='/jobs/search']")
             if (m := re.search(r"[?&]page=(\d+)", a["href"]))]
    return max(pages, default=1)


def search_all(get):
    """Every job in the search, page by page; raises if a page doesn't load or has no
    jobs before the last one, so a half-read listing is never taken for the whole one."""
    jobs, seen, page, last, total = [], set(), 1, 1, None
    while page <= min(last, MAX_PAGES):
        html = get(SEARCH.format(page), CARDS)
        cards = parse_cards(html)
        if not cards:
            if page < last:
                raise RuntimeError(f"HKU search page {page} of {last} has no jobs")
            break
        if page == 1:
            total = search_total(html)
            if total:
                last = math.ceil(total / len(cards))
        last = max(last, last_page(html))
        for job in cards:
            if job["id"] not in seen:
                seen.add(job["id"])
                jobs.append(job)
        page += 1
    if last > MAX_PAGES:
        print(f"  ⚠️  Search has {last} pages; read the first {MAX_PAGES} — raise MAX_PAGES")
    print(f"  ↳ {page - 1} search pages, {len(jobs)} jobs listed (the site says {total})")
    if total and len(jobs) < total:
        print(f"  ⚠️  Read {len(jobs)} of the {total} jobs the site lists — did the search change while it was read?")
    return jobs


BLOCK_TAGS = ["p", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "ul", "ol", "section"]
BREAK = ""  # marks where a line ends; newlines in the HTML source are just spaces


def text_lines(el):
    """The element's text, a line per paragraph, list item or heading; bold text and
    links stay inside their sentence."""
    for br in el.find_all("br"):
        br.replace_with(BREAK)
    for block in el.find_all(BLOCK_TAGS):
        block.insert_before(BREAK)
        block.append(BREAK)
    return [line for line in (clean(t) for t in el.get_text().split(BREAK)) if line]


def description(html):
    """The job page's description (div.job-description), or failing that its main
    text without the site's header, navigation, footer and the other jobs it lists
    below. '' if too little is left to be a description."""
    soup = BeautifulSoup(html, "html.parser")
    parts = [d for d in soup.select(".job-description") if not d.find_parent(class_="job-description")]
    if parts:
        lines = [line for part in parts for line in text_lines(part)]
    else:
        for tag in soup.select("script, style, noscript, header, nav, footer, form, "
                               ".job-search-results-card"):
            tag.decompose()
        lines = [line for line in text_lines(soup.select_one("main") or soup.body or soup) if len(line) > 30]
    text = "\n\n".join(lines)
    if len(text) < 200 or any(m in text.lower() for m in BOT_MARKERS):
        return ""
    return text[:8000]


def collect(get):
    """All HKU jobs from the search, with descriptions: known jobs keep their summaries,
    new ones (most senior first, up to MAX_DETAILS) get their job page's text."""
    listed = search_all(get)
    jobs = [j for j in listed if not any(kw in j["title"].lower() for kw in ADMIN_KEYWORDS)]
    print(f"  ↳ {len(jobs)} jobs after skipping admin roles")

    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]
    todo = [j for j in jobs if is_within_retention(j["deadline"]) and not _has_good_desc(j["id"])]
    todo.sort(key=lambda j: RANK_PRIORITY.get(j["rank"], 99))
    if todo:
        print(f"  ↳ Reading {min(len(todo), MAX_DETAILS)} of {len(todo)} job pages for descriptions")
        found = 0
        for j in todo[:MAX_DETAILS]:
            try:
                text = description(get(j["apply_url"], JOB_PAGE_READY))
            except RuntimeError as e:
                print(f"  ⚠️  Stopped reading job pages: {e}")
                break
            if text:
                j["description"] = text
                found += 1
        print(f"  ↳ Got descriptions for {found}/{len(todo)} jobs")
    return jobs


def scrape_hku():
    """HKU — jobs.hku.hk/jobs/search, read in a headless browser (see open_page)."""
    print("📋 Scraping HKU...")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Full Chromium in headless mode, not the headless shell: what was checked to
        # get the AWS WAF token (20 Nov 2026). No user agent override either.
        browser = p.chromium.launch(channel="chromium", headless=True)
        try:
            page = browser.new_page()
            jobs = collect(lambda url, ready: open_page(page, url, ready))
        finally:
            browser.close()
    print(f"  ✅ HKU: {len(jobs)} jobs found")
    return jobs
