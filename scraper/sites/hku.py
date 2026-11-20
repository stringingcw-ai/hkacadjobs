"""University of Hong Kong: job scraper."""

import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core import (
    BOT_MARKERS, clean, detect_rank, detect_type, HEADERS, is_within_retention,
    make_id, parse_date_text, PLACEHOLDER_MARKER, _existing_descriptions, _has_good_desc,
    is_active,
)

BASE = "https://jobs.hku.hk"
# HKU's careers site since 19/20 Nov 2026: 30 jobs per search page (page-items is
# ignored), about 15 pages. Job pages moved from /en/job/<number> to /jobs/<slug>-<uuid>,
# but every card still shows the job number (requisition identifier), so ids carry over.
SEARCH = BASE + "/jobs/search?page={}"
MAX_PAGES = 60      # safety stop, about 1,800 jobs
MAX_DETAILS = 40    # job pages fetched per run; the rest are fetched on later runs
PAUSE = (3, 6)      # seconds between requests: AWS WAF challenges quick repeated ones
RETRY_WAIT = 30     # seconds to wait after a challenge before asking again

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


def fetch(url, session, sleep=time.sleep, retries=2):
    """A page's HTML from a plain request, after a short pause. AWS WAF answers quick
    repeated requests with a challenge (HTTP 202, no content) that only a browser
    solves, so wait and ask again; raise if the page never comes."""
    problem = ""
    for attempt in range(retries + 1):
        sleep(random.uniform(*PAUSE) if attempt == 0 else RETRY_WAIT * attempt)
        try:
            resp = session.get(url, headers=HEADERS, timeout=60)
        except requests.RequestException as e:
            problem = str(e)
        else:
            if resp.status_code == 200:
                return resp.text
            waf = resp.headers.get("x-amzn-waf-action", "")
            problem = f"HTTP {resp.status_code}" + (f", AWS WAF {waf}" if waf else "")
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
    for card in soup.select(".block-job-search-results .job-search-results-card"):
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


def last_page(html):
    """The highest page number the search's paging links on this page point to."""
    soup = BeautifulSoup(html, "html.parser")
    pages = [int(m.group(1)) for a in soup.select("a[href*='/jobs/search']")
             if (m := re.search(r"[?&]page=(\d+)", a["href"]))]
    return max(pages, default=1)


def search_all(get):
    """Every job in the search, walking its pages; raises if a page doesn't load or
    comes back empty before the last one, so a half-read listing is never taken for
    the whole one."""
    jobs, seen, page, last = [], set(), 1, 1
    while page <= min(last, MAX_PAGES):
        html = get(SEARCH.format(page))
        cards = parse_cards(html)
        if not cards:
            if page < last:
                raise RuntimeError(f"HKU search page {page} of {last} has no jobs")
            break
        for job in cards:
            if job["id"] not in seen:
                seen.add(job["id"])
                jobs.append(job)
        last = max(last, last_page(html))
        page += 1
    if last > MAX_PAGES:
        print(f"  ⚠️  Search has {last} pages; read the first {MAX_PAGES} — raise MAX_PAGES")
    print(f"  ↳ {page - 1} search pages, {len(jobs)} jobs listed")
    return jobs


def description(html):
    """The job page's own text: without the site's header, navigation, footer and the
    other jobs' cards it lists below. '' if too little is left to be a description."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, noscript, header, nav, footer, form, "
                           ".job-search-results-card"):
        tag.decompose()
    body = soup.select_one("main") or soup.body or soup
    lines = [clean(line) for line in body.get_text("\n").splitlines()]
    text = "\n\n".join(line for line in lines if len(line) > 30)
    if len(text) < 200 or any(m in text.lower() for m in BOT_MARKERS):
        return ""
    return text[:8000]


def scrape_hku():
    """HKU — jobs.hku.hk/jobs/search: every search page, then the job pages of new jobs
    for their descriptions (known jobs keep their summaries)."""
    print("📋 Scraping HKU...")
    session = requests.Session()
    get = lambda url: fetch(url, session)  # noqa: E731

    listed = search_all(get)
    jobs = [j for j in listed if not any(kw in j["title"].lower() for kw in ADMIN_KEYWORDS)]
    print(f"  ↳ {len(jobs)} jobs after skipping admin roles")

    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]
    todo = [j for j in jobs if is_within_retention(j["deadline"]) and not _has_good_desc(j["id"])]
    todo.sort(key=lambda j: RANK_PRIORITY.get(j["rank"], 99))
    if todo:
        print(f"  ↳ Fetching {min(len(todo), MAX_DETAILS)} of {len(todo)} job pages for descriptions")
        found = 0
        for j in todo[:MAX_DETAILS]:
            try:
                text = description(get(j["apply_url"]))
            except RuntimeError as e:
                print(f"  ⚠️  Stopped fetching job pages: {e}")
                break
            if text:
                j["description"] = text
                found += 1
        print(f"  ↳ Got descriptions for {found}/{len(todo)} jobs")

    print(f"  ✅ HKU: {len(jobs)} jobs found")
    return jobs
