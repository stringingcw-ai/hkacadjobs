"""
HKAcadJobs Scraper
Scrapes academic job listings from all 8 HK universities.
Outputs: jobs.csv (in the format expected by the website)

Usage:
  python scraper.py              # scrape all universities
  python scraper.py --uni polyu  # scrape one university only

Requirements:
  pip install requests beautifulsoup4 playwright
  playwright install chromium    # for JS-rendered sites
"""

import csv
import re
import sys
import time
import argparse
import hashlib
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Output file path (same directory as this script)
OUTPUT_FILE = Path(__file__).parent.parent / "jobs.csv"

# ── CSV columns (must match website expectations)
FIELDNAMES = [
    "id", "title", "rank", "university", "university_full",
    "department", "deadline", "is_new", "date_added", "reference",
    "position_type", "salary", "start_date", "apply_url", "description"
]

# ── Shared request headers (polite browser-like headers)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TODAY = date.today()


# ══════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════

def clean(text):
    """Strip whitespace and normalise internal spaces."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def make_id(uni_code, ref):
    """Generate a stable unique ID."""
    key = clean(str(ref)) if ref else "unknown"
    if len(key) <= 20 and re.match(r'^[\w\-]+$', key):
        return f"{uni_code.upper()}-{key}"
    return f"{uni_code.upper()}-{hashlib.md5(key.encode()).hexdigest()[:10]}"


def detect_rank(title):
    """Infer rank from job title."""
    t = title.lower()
    if "chair professor" in t:       return "Professor"
    if "associate professor" in t:   return "Associate Professor"
    if "assistant professor" in t:   return "Assistant Professor"
    if "professor" in t:             return "Professor"
    if "postdoc" in t:               return "Postdoc"
    if "research fellow" in t:       return "Postdoc"
    if "lecturer" in t:              return "Lecturer"
    if "teaching fellow" in t:       return "Lecturer"
    if "instructor" in t:            return "Lecturer"
    if "clinical" in t:              return "Lecturer"
    return "Other"


def detect_type(title):
    """Infer position type from title."""
    t = title.lower()
    if "temporary" in t or "fixed-term" in t: return "Fixed-term"
    if "part-time" in t:                       return "Part-time"
    return "Full-time"


def parse_date_text(text):
    """
    Convert various date formats to YYYY-MM-DD.
    Handles: '27 February 2026', '2026-02-27', '27/02/2026', etc.
    Returns '' if unparseable.
    """
    if not text:
        return ""
    text = clean(text)
    formats = [
        "%d %B %Y", "%d %b %Y",
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
        "%B %d, %Y", "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text  # return as-is if can't parse


def is_active(deadline_str):
    """Return True if deadline is today or in the future."""
    if not deadline_str:
        return True  # unknown deadline — assume active
    try:
        d = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        return d >= TODAY
    except ValueError:
        return True


def is_within_retention(deadline_str, days=30):
    """Return True if deadline is empty, active, or closed within the last `days` days."""
    if not deadline_str:
        return True
    try:
        d = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        from datetime import timedelta
        return d >= (TODAY - timedelta(days=days))
    except ValueError:
        return True


def get_soup(url, timeout=15, legacy_ssl=False):
    """Fetch a URL and return a BeautifulSoup object.
    legacy_ssl=True enables unsafe legacy TLS renegotiation (needed for EdUHK).
    """
    try:
        if legacy_ssl:
            import ssl
            import urllib3
            from requests.adapters import HTTPAdapter
            from urllib3.util.ssl_ import create_urllib3_context

            # Create SSL context that allows legacy renegotiation
            ctx = create_urllib3_context()
            ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            class LegacySSLAdapter(HTTPAdapter):
                def init_poolmanager(self, *args, **kwargs):
                    kwargs["ssl_context"] = ctx
                    super().init_poolmanager(*args, **kwargs)

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            session = requests.Session()
            session.mount("https://", LegacySSLAdapter())
            resp = session.get(url, headers=HEADERS, timeout=timeout, verify=False)
        else:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  ⚠️  Failed to fetch {url}: {e}")
        return None


def get_js_soup(url, wait_selector=None, timeout=20000):
    """
    Fetch a JavaScript-rendered page using Playwright.
    Returns a BeautifulSoup object, or None on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)
            page.goto(url, timeout=timeout)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass  # continue even if selector not found
            else:
                page.wait_for_load_state("networkidle", timeout=timeout)
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"  ⚠️  Playwright failed for {url}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# SCRAPERS — one function per university
# ══════════════════════════════════════════════════════════════════

def scrape_polyu_detail(ref, debug=False):
    """
    Fetch a PolyU job detail page and extract the description.
    URL: https://jobs.polyu.edu.hk/job_detail.php?job={ref}
    Returns a plain-text description string, or "" on failure.
    """
    url = f"https://jobs.polyu.edu.hk/job_detail.php?job={ref}"
    soup = get_soup(url, timeout=10)
    if not soup:
        return ""

    # Remove noise
    for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()

    if debug:
        print(f"\n  🔍 DEBUG {url}")
        for tag in soup.find_all(["div", "td", "table", "p"], limit=40):
            cls = tag.get("class", "")
            idd = tag.get("id", "")
            t   = clean(tag.get_text(" "))[:100]
            if t:
                print(f"    <{tag.name} class={cls} id={idd}>: {t}")
        return ""

    # PolyU job descriptions live in div.ITS_Content_RichTextEditor
    content = soup.find("div", class_="ITS_Content_RichTextEditor")
    if content:
        seen = set()
        parts = []
        for p in content.find_all("p"):
            t = clean(p.get_text(" "))
            # Normalise whitespace for dedup comparison
            key = re.sub(r"\s+", " ", t).lower()
            if t and key not in seen:
                seen.add(key)
                parts.append(t)
        if parts:
            return " ".join(parts)[:2000]

    # Fallback: largest text block
    candidates = [
        clean(tag.get_text(" "))
        for tag in soup.find_all(["div", "td", "section"])
        if 150 < len(clean(tag.get_text(" "))) < 5000
    ]
    if candidates:
        return max(candidates, key=len)[:2000]

    return ""


def scrape_polyu_page(url, position_type_override=None):
    """
    Scrape one PolyU jobs listing page (table format).
    Column layout across pages:
      Col 0: Department/Unit
      Col 1: Position (always the job title)
      Col 2: Project Title (research.php only — extra column)
      Col 2/3: Closing Date
      Col 3/4: Ref No.
    """
    soup = get_soup(url)
    if not soup:
        return []

    jobs = []
    table = soup.find("table")
    if not table:
        return []

    for row in table.find_all("tr")[1:]:  # skip header row
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        texts = [clean(col.get_text()) for col in cols]

        # Ref is always a 7-10 digit number
        ref = ""
        for t in texts:
            if re.match(r"^\d{7,10}$", t.replace(" ", "")):
                ref = t.replace(" ", "")
                break
        if not ref:
            continue

        dept  = texts[0]
        title = re.sub(r"\s+", " ", texts[1])  # always col 1 = Position

        # Project title: present only on research.php (5 cols)
        # It sits in col 2 when there are 5+ cols and col 2 isn't a date or ref
        project_title = ""
        if len(cols) >= 5:
            candidate = texts[2]
            if candidate and candidate != ref and not re.search(r"\d{4}", candidate):
                project_title = candidate

        # Deadline: first cell that parses as a date
        deadline = ""
        for t in texts:
            parsed = parse_date_text(t)
            if parsed and parsed != t:
                deadline = parsed
                break

        if not title:
            continue

        description = title
        if project_title:
            description += f" — Project: {project_title}"
        description += f" ({dept}). See application link for full details."

        jobs.append({
            "ref":         ref,
            "title":       title,
            "dept":        dept,
            "deadline":    deadline,
            "pos_type":    position_type_override or detect_type(title),
            "description": description,
        })

    return jobs


def scrape_polyu():
    """
    PolyU — scrapes all 5 job listing pages, then fetches each detail page
    for the full job description.

    Pages:
      Central & Senior Management  → central_senior.php
      Deans & Heads                → deans_heads.php
      Academic / Teaching          → academic.php
      Research Assistant Professor → rap.php
      Research / Project Posts     → research.php
    """
    print("📋 Scraping PolyU...")

    base = "https://jobs.polyu.edu.hk"
    pages = [
        (f"{base}/central_senior.php", "Full-time"),
        (f"{base}/deans_heads.php",    "Full-time"),
        (f"{base}/academic.php",       "Full-time"),
        (f"{base}/rap.php",            "Full-time"),
        (f"{base}/research.php",       "Full-time"),
    ]

    # Step 1: collect all jobs from all listing pages
    raw_jobs = []
    seen_refs = set()
    for url, pos_type in pages:
        page_jobs = scrape_polyu_page(url, pos_type)
        for j in page_jobs:
            if j["ref"] not in seen_refs:
                seen_refs.add(j["ref"])
                raw_jobs.append(j)

    print(f"  ↳ Found {len(raw_jobs)} listings across all pages")

    # Step 2: build job records (descriptions: TODO — deferred to future sprint)
    jobs = []
    for j in raw_jobs:
        ref      = j["ref"]
        title    = j["title"]
        dept     = j["dept"]
        deadline = j["deadline"]

        apply_url   = f"{base}/job_detail.php?job={ref}"
        description = j.get("description") or f"{title} — {dept}. See {apply_url} for full details."

        jobs.append({
            "id":               make_id("POLYU", ref),
            "title":            title,
            "rank":             detect_rank(title),
            "university":       "PolyU",
            "university_full":  "Hong Kong Polytechnic University",
            "department":       dept,
            "deadline":         deadline,
            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
            "reference":        ref,
            "position_type":    j["pos_type"],
            "salary":           "",
            "start_date":       "",
            "apply_url":        apply_url,
            "description":      description,
        })

    print(f"  ✅ PolyU: {len(jobs)} jobs found")
    return jobs


def scrape_eduhk():
    """
    EdUHK — eduhk.hk/en/current-openings
    JS-rendered. Playwright fetches each page; parser anchors on "Ad Date:".
    """
    print("📋 Scraping EdUHK...")

    BASE = "https://www.eduhk.hk"
    CATEGORIES = [
        ("senior-management",              "Senior Management"),
        ("deanship-headship-appointments", "Deanship/Headship"),
        ("academic-teaching-posts",        "Academic"),
        ("research-support-posts",         "Research"),
    ]

    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for category, pos_type in CATEGORIES:
                cat_count = 0
                page_num  = 1
                pw_page   = None

                while True:
                    if page_num == 1:
                        url = f"{BASE}/en/current-openings?category={category}&department=&q="
                    # (subsequent pages are reached by clicking Next, not URL param)

                    try:
                        if page_num == 1:
                            pw_page = browser.new_page()
                            pw_page.set_extra_http_headers(HEADERS)
                            pw_page.goto(url, timeout=60000, wait_until="domcontentloaded")
                            pw_page.wait_for_timeout(3000)
                        # else: pw_page already on next page from previous click

                        full_text = pw_page.inner_text("body")
                    except Exception as page_err:
                        print(f"  ↳ {pos_type} p{page_num}: error ({page_err.__class__.__name__})")
                        try: pw_page.close()
                        except: pass
                        break

                    ad_count = full_text.count("Ad Date:")
                    if ad_count == 0:
                        break

                    jobs_before = len(jobs)
                    # Anchor on each "Ad Date:" occurrence.
                    # Grab 400 chars before for title+dept+ref, 200 chars after for close date.
                    for m in re.finditer(r'Ad Date:', full_text):
                        before = full_text[max(0, m.start()-600):m.start()]
                        after  = full_text[m.end():m.end()+200]

                        before_lines = [l.strip() for l in before.splitlines() if l.strip()]

                        # Title and dept: last 2 lines before metadata
                        # Strip lines that look like pagination/nav
                        content_lines = [l for l in before_lines
                                         if not re.match(r'^(Next|Previous|Go to page|Search|Filter|Home|Menu|\d+)$', l, re.I)
                                         and not re.match(r'^Ref:', l)
                                         and len(l) > 2]
                        if not content_lines:
                            continue

                        # Filter out known UI noise
                        NOISE = {"n/a", "na", "reset", "search", "filter", "apply", "clear", "go", "next", "previous"}
                        content_lines = [l for l in content_lines if l.lower() not in NOISE]

                        if not content_lines:
                            continue

                        # Walk backwards: collect dept-like lines, then first non-dept line = title
                        dept_pattern = re.compile(r'^(Department|Faculty|School|Academy|Division|Office|Centre|Center)', re.I)
                        title = ""
                        dept  = ""
                        for line in reversed(content_lines):
                            if dept_pattern.match(line):
                                if not dept:
                                    dept = line   # take innermost dept-like line
                            else:
                                if not title:
                                    title = line
                                    break
                        # Fallback: only dept-like lines found, use last as title
                        if not title:
                            title = dept
                            dept  = ""

                        if not title or len(title) < 3:
                            continue

                        ref_m = re.search(r'Ref:\s*(\d{6,})', before[-150:] + after[:50])
                        ref   = ref_m.group(1) if ref_m else ""
                        key = f"{title}|{ref}" if ref else f"{title}|{dept}"
                        if key in seen:
                            continue
                        seen.add(key)

                        close_m = re.search(r'Close Date[:\s]+([A-Za-z0-9 ]+)', after)
                        deadline = ""
                        if close_m:
                            raw = close_m.group(1).strip()
                            if raw.upper() not in ("N/A", "NA", ""):
                                deadline = parse_date_text(raw)

                        jobs.append({
                            "id":               make_id("EDUHK", ref if ref else f"{title[:40]}_{dept[:20]}"),
                            "title":            title,
                            "rank":             detect_rank(title),
                            "university":       "EdUHK",
                            "university_full":  "Education University of Hong Kong",
                            "department":       dept,
                            "deadline":         deadline,
                            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                            "reference":        ref,
                            "position_type":    detect_type(title),
                            "salary":           "",
                            "start_date":       "",
                            "apply_url":        f"{BASE}/en/current-openings?category={category}&department=&q=",
                            "description":      f"{title}{' — ' + dept if dept else ''}. See EdUHK website for full details.",
                        })
                        cat_count += 1

                    # Try clicking Next button for next page
                    try:
                        next_btn = pw_page.query_selector("a:has-text('Next'), button:has-text('Next'), [aria-label='Next']")
                        if next_btn and ad_count > 0 and page_num < 20:
                            next_btn.click()
                            pw_page.wait_for_timeout(3000)
                            page_num += 1
                        else:
                            pw_page.close()
                            break
                    except Exception:
                        try: pw_page.close()
                        except: pass
                        break

                print(f"  ↳ {pos_type}: {cat_count} jobs ({page_num} page(s))")

            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")
        import traceback; traceback.print_exc()

    print(f"  ✅ EdUHK: {len(jobs)} jobs found")
    return jobs


def scrape_lingnan():
    """
    Lingnan — lingnan.csod.com (Cornerstone OnDemand ATS)
    5 pages of jobs. Fetches all roles (academic + admin).
    Department is extracted from the job title (text after last comma).
    """
    print("📋 Scraping Lingnan...")

    def parse_jobs(html, seen):
        result = []
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"requisition", re.I)):
            full_title = clean(a.get_text())
            if not full_title or len(full_title) < 5 or full_title in seen:
                continue
            seen.add(full_title)

            href = a.get("href", "")
            apply_url = f"https://lingnan.csod.com{href}" if href.startswith("/") else href
            ref_match = re.search(r"requisition/(\d+)", href)
            ref = ref_match.group(1) if ref_match else ""

            # Split title on last comma: "Senior HR Officer, Human Resources Office"
            # → title = "Senior HR Officer", dept = "Human Resources Office"
            if "," in full_title:
                last_comma = full_title.rfind(",")
                title = full_title[:last_comma].strip()
                dept  = full_title[last_comma + 1:].strip()
            else:
                title = full_title
                dept  = "Lingnan University"

            result.append({
                "id":               make_id("LU", ref or title[:25]),
                "title":            title,
                "rank":             detect_rank(title),
                "university":       "LU",
                "university_full":  "Lingnan University",
                "department":       dept,
                "deadline":         "",
                "is_new":           "TRUE",
                "reference":        ref,
                "position_type":    detect_type(title),
                "salary":           "",
                "start_date":       "",
                "apply_url":        apply_url,
                "description":      f"{title} — {dept}. Please visit the application link for full details.",
            })
        return result

    jobs = []

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)
            page.goto("https://lingnan.csod.com/ux/ats/careersite/4/home?c=lingnan", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)

            total_pages = page.evaluate("""
                () => {
                    const btns = Array.from(document.querySelectorAll(
                        '[class*="paginat"] a, [class*="paginat"] button, nav a, nav button'
                    ));
                    const nums = btns.map(b => parseInt(b.textContent.trim())).filter(n => !isNaN(n) && n > 0);
                    return nums.length ? Math.max(...nums) : 1;
                }
            """)
            print(f"  ↳ Detected {total_pages} pages")

            seen = set()

            for pg in range(1, total_pages + 1):
                jobs.extend(parse_jobs(page.content(), seen))

                if pg >= total_pages:
                    break

                clicked = page.evaluate(f"""
                    () => {{
                        const target = {pg + 1};
                        const btns = Array.from(document.querySelectorAll(
                            '[class*="paginat"] a, [class*="paginat"] button, nav a, nav button'
                        ));
                        const btn = btns.find(b => parseInt(b.textContent.trim()) === target);
                        if (btn) {{ btn.click(); return true; }}
                        const next = document.querySelector('[aria-label="Next"], [title="Next"]');
                        if (next) {{ next.click(); return true; }}
                        return false;
                    }}
                """)

                if not clicked:
                    print(f"  ⚠️  Could not click to page {pg + 1}")
                    break

                page.wait_for_load_state("networkidle", timeout=10000)
                page.wait_for_timeout(1000)

            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ Lingnan: {len(jobs)} jobs found")
    return jobs


def scrape_hku():
    """
    HKU — jobs.hku.hk/en/listing/ (PageUp ATS)
    Clicks "More Jobs" until count stops changing, with proper wait between clicks.
    """
    print("📋 Scraping HKU...")

    ADMIN_KEYWORDS = {
        "administrative assistant", "clerical assistant",
        "finance officer", "it officer", "facilities manager",
        "procurement officer", "human resources officer",
        "security officer", "safety officer", "receptionist",
        "estate manager", "accounting officer", "payroll officer",
    }

    def parse_jobs(html, seen):
        result = []
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all("tr"):
            link = row.find("a", href=True)
            if not link:
                continue
            title = clean(link.get_text())
            if not title or len(title) < 5:
                continue
            href = link.get("href", "")
            apply_url = f"https://jobs.hku.hk{href}" if href.startswith("/") else href
            cells = row.find_all("td")
            ref = dept = deadline = ""
            for cell in cells:
                t = clean(cell.get_text())
                if re.match(r"^\d{5,8}$", t):
                    ref = t
                elif re.search(r"Faculty|Department|School|Institute|Centre|Office|Library", t, re.I) and t != title:
                    dept = t
                else:
                    parsed = parse_date_text(t)
                    if parsed and parsed != t:
                        deadline = parsed
            dept = dept or "University of Hong Kong"
            dedup_key = ref if ref else f"{title}|{dept}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            title_lower = title.lower()
            if any(kw in title_lower for kw in ADMIN_KEYWORDS):
                continue
            result.append({
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
                "apply_url":        apply_url,
                "description":      f"{title} — {dept}. Please visit the application link for full details.",
            })
        return result

    jobs = []

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)
            page.goto("https://jobs.hku.hk/en/listing/", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)

            seen = set()
            clicks = 0
            prev_count = 0

            while True:
                current_count = page.evaluate("() => document.querySelectorAll('tr').length")

                if clicks > 0 and current_count <= prev_count:
                    print(f"  ↳ No new rows after click {clicks} (still {current_count}), stopping")
                    break

                # Scroll to bottom first so the button enters the viewport
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)

                clicked = page.evaluate("""
                    () => {
                        const all = Array.from(document.querySelectorAll("button, a, input[type=button]"));
                        const btn = all.find(b =>
                            /more.?job/i.test(b.textContent) ||
                            /load.?more/i.test(b.textContent) ||
                            /show.?more/i.test(b.textContent) ||
                            /view.?more/i.test(b.textContent)
                        );
                        if (btn) {
                            btn.scrollIntoView();
                            btn.click();
                            return btn.textContent.trim();
                        }
                        return null;
                    }
                """)

                if not clicked:
                    print(f"  ↳ Button gone after {clicks} clicks — all jobs loaded ({current_count} rows)")
                    break

                if clicks == 0:
                    remaining_m = re.search(r'\d+', clicked)
                    remaining = int(remaining_m.group()) if remaining_m else '?'
                    print(f"  ↳ Found button: '{clicked}' (~{remaining} jobs remaining to load)")

                prev_count = current_count
                clicks += 1
                page.wait_for_timeout(1500)

                if clicks > 500:
                    break

            print(f"  ↳ Clicked More Jobs {clicks} times, loaded {prev_count} rows")
            jobs.extend(parse_jobs(page.content(), seen))
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ HKU: {len(jobs)} jobs found")
    return jobs


def scrape_hkust():
    """
    HKUST — hkustcareers.hkust.edu.hk
    Two pages: academic-careers and teaching-support.
    JS extracts raw card text; Python does all parsing.
    """
    print("📋 Scraping HKUST...")

    URLS = [
        ("https://hkustcareers.hkust.edu.hk/join-us/current-opening/academic-careers", "Academic"),
        ("https://hkustcareers.hkust.edu.hk/join-us/current-opening/teaching-support",  "Teaching"),
    ]
    BASE = "https://hkustcareers.hkust.edu.hk"
    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for url, pos_type in URLS:
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)
                page.wait_for_timeout(3000)

                # Check how many Job IDs are in the page
                full_text = page.inner_text("body")
                job_id_count = full_text.count("Job ID")
                print(f"  ↳ {pos_type}: {job_id_count} Job IDs in page text")

                seen_ids = set()
                for m in re.finditer(r'Job ID: (\d+)', full_text):
                    ref = m.group(1)
                    if ref in seen_ids:
                        continue
                    seen_ids.add(ref)

                    before = full_text[max(0, m.start()-300):m.start()]
                    after  = full_text[m.end():m.end()+300]

                    # Title: last meaningful line before Job ID (skip filter labels like "School (3)")
                    before_lines = [l.strip() for l in before.splitlines() if l.strip()]
                    title = ""
                    for line in reversed(before_lines):
                        if re.search(r'\(\d+\)$', line):
                            continue
                        if len(line) > 4:
                            title = line
                            break

                    # Dept: first non-empty line after Job ID before date lines
                    after_lines = [l.strip() for l in after.splitlines() if l.strip()]
                    dept = ""
                    for line in after_lines:
                        if re.match(r'Open Date|Apply by|\d{4}-\d{2}', line):
                            break
                        if len(line) > 4:
                            dept = line
                            break

                    # Deadline — optional, some cards don't have it
                    deadline_m = re.search(r'Apply by: ([\d\-]+)', after)
                    deadline = parse_date_text(deadline_m.group(1)) if deadline_m else ""

                    title = clean(title)
                    if not title or len(title) < 4:
                        continue

                    # Use ref as unique ID (same title can appear with different Job IDs)
                    jobs.append({
                        "id":               make_id("HKUST", ref),
                        "title":            title,
                        "rank":             detect_rank(title),
                        "university":       "HKUST",
                        "university_full":  "HK University of Science & Technology",
                        "department":       dept,
                        "deadline":         deadline,
                        "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                        "reference":        ref,
                        "position_type":    detect_type(title),
                        "salary":           "",
                        "start_date":       "",
                        "apply_url":        f"https://hrmsxprod.psft.ust.hk:8044/psp/hrmsxprod/EMPLOYEE/HRMS/c/HRS_HRAM.HRS_CE.GBL?Page=HRS_CE_JOB_DTL&Action=A&JobOpeningId={ref}&SiteId=1000&PostingSeq=1",
                        "description":      f"{title}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
                    })

                page.close()
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ HKUST: {len(jobs)} jobs found")
    return jobs


def scrape_cityu():
    """
    CityU — jobs1.cityu.edu.hk/apply/Default.aspx
    Three static HTML tables: SENIOR, ACAD, RS.
    """
    print("📋 Scraping CityU...")

    URLS = [
        ("https://jobs1.cityu.edu.hk/apply/Default.aspx?jobtype=SENIOR", "Senior Management"),
        ("https://jobs1.cityu.edu.hk/apply/Default.aspx?jobtype=ACAD",   "Academic Faculty"),
        ("https://jobs1.cityu.edu.hk/apply/Default.aspx?jobtype=RS",     "Research"),
    ]

    jobs = []
    seen = set()

    for url, pos_type in URLS:
        soup = get_soup(url)
        if not soup:
            print(f"  ↳ {pos_type}: fetch failed")
            continue

        rows = soup.select("table tr")
        count = 0
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            # First cell: title link
            a = cells[0].find("a", href=True)
            if not a:
                continue
            title = clean(a.get_text())
            if not title or len(title) < 3:
                continue

            href = a["href"]
            apply_url = href if href.startswith("http") else f"https://www.cityu.edu.hk{href}"

            ref_m = re.search(r"ref=([\w\-]+)", href, re.I)
            ref   = ref_m.group(1) if ref_m else ""

            if ref in seen:
                continue
            seen.add(ref or title)

            # Second cell: department
            dept = clean(cells[1].get_text())

            # Third cell: deadline (may say "until filled")
            deadline = ""
            if len(cells) >= 3:
                date_text = cells[2].get_text()
                deadline  = parse_date_text(date_text)

            jobs.append({
                "id":               make_id("CITYU", ref or title[:25]),
                "title":            title,
                "rank":             detect_rank(title),
                "university":       "CityU",
                "university_full":  "City University of Hong Kong",
                "department":       dept,
                "deadline":         deadline,
                "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                "reference":        ref,
                "position_type":    detect_type(title),
                "salary":           "",
                "start_date":       "",
                "apply_url":        apply_url,
                "description":      f"{title} — {dept}. Please visit the application link for full details.",
            })
            count += 1

        print(f"  ↳ {pos_type}: {count} jobs")

    print(f"  ✅ CityU: {len(jobs)} jobs found")
    return jobs


def scrape_hkbu():
    """
    HKBU — Oracle HCM Cloud ATS
    Hits the Oracle recruiting API directly with pagination (25 jobs/page).
    URL pattern discovered via Playwright network interception.
    """
    print("📋 Scraping HKBU...")

    BASE = "https://fa-ewqq-saasfaprod1.fa.ocs.oraclecloud.com"
    API  = f"{BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    # Exact finder string observed in network requests
    FINDER = (
        "CandidateExperience;siteNumber=CX_1,"
        "facetsList=LOCATIONS%3BWORK_LOCATIONS%3BTITLES%3BCATEGORIES"
        "%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS"
    )

    HKBU_HEADERS = {
        **HEADERS,
        "Referer":  f"{BASE}/hcmUI/CandidateExperience/en/sites/hkbu/jobs",
        "Origin":   BASE,
    }

    jobs = []
    seen = set()
    offset = 0

    try:
        while True:
            params = {
                "onlyData": "true",
                "finder":   FINDER,
                "limit":    "25",
                "offset":   str(offset),
                "sortBy":   "POSTING_DATES_DESC",
            }
            resp = requests.get(API, params=params, headers=HKBU_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            items    = data.get("items", [])
            has_more = data.get("hasMore", False)

            for r in items:
                full_title = clean(str(
                    r.get("Title") or r.get("title") or
                    r.get("JobTitle") or r.get("displayTitle") or ""
                ))
                if not full_title or full_title in seen:
                    continue
                seen.add(full_title)

                ref = str(r.get("Id") or r.get("id") or r.get("RequisitionNumber") or
                          r.get("requisitionNumber") or r.get("ExternalReqNumber") or "")
                apply_url = f"{BASE}/hcmUI/CandidateExperience/en/sites/hkbu/job/{ref}" if ref else f"{BASE}/hcmUI/CandidateExperience/en/sites/hkbu/jobs"

                deadline = parse_date_text(str(
                    r.get("PostedEndDate") or r.get("postedEndDate") or
                    r.get("ClosingDate") or r.get("closingDate") or ""
                ))

                desc_text = clean(str(
                    r.get("ExternalDescriptionStr") or r.get("ShortDescription") or
                    r.get("description") or ""
                ))

                # Dept: comma split or "sits under" pattern
                if "," in full_title:
                    last = full_title.rfind(",")
                    title = full_title[:last].strip()
                    dept  = full_title[last + 1:].strip()
                else:
                    title = full_title
                    dept  = ""

                if not dept and desc_text:
                    m = re.search(r"sits under (?:the\s+)?([A-Z][^,.]{3,60}?)(?:\s+at our|\s+campus|,|\.|$)", desc_text)
                    if m:
                        dept = m.group(1).strip()
                dept = dept or "Hong Kong Baptist University"

                jobs.append({
                    "id":               make_id("HKBU", ref or title[:25]),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKBU",
                    "university_full":  "Hong Kong Baptist University",
                    "department":       dept,
                    "deadline":         deadline,
                    "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        apply_url,
                    "description":      desc_text[:500] if desc_text else f"{title} — {dept}. Please visit the application link for full details.",
                })

            if not has_more or not items:
                break
            offset += 25
            if offset > 1000:
                break

    except Exception as e:
        print(f"  ⚠️  Direct API failed ({e}), falling back to Playwright...")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(f"{BASE}/hcmUI/CandidateExperience/en/sites/hkbu/jobs", timeout=30000)
                page.wait_for_timeout(5000)
                prev_height = 0
                stale = 0
                for _ in range(60):
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2500)
                    height = page.evaluate("() => document.body.scrollHeight")
                    if height == prev_height:
                        stale += 1
                        if stale >= 3:
                            break
                    else:
                        stale = 0
                    prev_height = height
                job_data = page.evaluate("""
                    () => {
                        var results = [];
                        var seen = {};
                        Array.from(document.querySelectorAll("a")).forEach(function(a) {
                            if (!a.href || a.href.indexOf("/job/") === -1) return;
                            var title = a.textContent.trim();
                            var cardText = "";
                            var el = a.parentElement;
                            for (var i = 0; i < 6; i++) {
                                if (!el) break;
                                if (!title || title.length < 4) {
                                    var h = el.querySelector("h1,h2,h3,h4,[class*=title],[class*=job-name]");
                                    if (h && h.textContent.trim().length > 4) title = h.textContent.trim();
                                }
                                if (el.textContent.trim().length > 100) {
                                    cardText = el.textContent.trim().slice(0, 500);
                                    break;
                                }
                                el = el.parentElement;
                            }
                            if (!title || title.length < 4 || seen[title]) return;
                            seen[title] = true;
                            results.push({ href: a.href, title: title, cardText: cardText });
                        });
                        return results;
                    }
                """)
                browser.close()
            seen2 = set()
            for jd in job_data:
                full_title = clean(jd["title"])
                if not full_title or full_title in seen2:
                    continue
                seen2.add(full_title)
                ref_match = re.search(r"/job/(\d+)", jd["href"])
                ref = ref_match.group(1) if ref_match else ""
                card_text = jd.get("cardText", "")

                # Dept: comma split only
                if "," in full_title:
                    last = full_title.rfind(",")
                    title = full_title[:last].strip()
                    dept  = full_title[last + 1:].strip()
                else:
                    title = full_title
                    dept  = ""

                # Leave empty if not found (don't fall back to university name)
                jobs.append({
                    "id":               make_id("HKBU", ref or title[:25]),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKBU",
                    "university_full":  "Hong Kong Baptist University",
                    "department":       dept,
                    "deadline":         "",
                    "is_new":           "TRUE",
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        jd["href"],
                    "description":      f"{title}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
                })
        except Exception as e2:
            print(f"  ⚠️  Playwright also failed: {e2}")

    print(f"  ✅ HKBU: {len(jobs)} jobs found")
    return jobs


def scrape_cuhk():
    """
    CUHK — Taleo Enterprise ATS (cuhk.taleo.net)
    Two career sections: teaching + non-teaching (research) posts.
    JS-rendered table: Job Number | Requisition Title | Department/Unit
    Paginates via Next button.
    """
    print("📋 Scraping CUHK...")

    BASE = "https://cuhk.taleo.net"
    SECTIONS = [
        (f"{BASE}/careersection/cu_career_teach/jobsearch.ftl?lang=en",     "Teaching"),
        (f"{BASE}/careersection/cu_career_non_teach/jobsearch.ftl?lang=en", "Research/Non-teaching"),
    ]
    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for URL, section_name in SECTIONS:
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(URL, timeout=60000, wait_until="domcontentloaded")

                try:
                    page.wait_for_selector("table tr td a", timeout=20000)
                except Exception:
                    print(f"  ⚠️  {section_name}: timed out waiting for job table")
                    page.close()
                    continue

                page_num   = 1
                sect_count = 0

                while True:
                    soup = BeautifulSoup(page.content(), "html.parser")
                    rows = soup.select("table tbody tr, table tr")
                    page_jobs = 0
                    for row in rows:
                        cells = row.find_all("td")
                        if len(cells) < 3:
                            continue
                        ref = title = dept = apply_url = ""
                        for i, cell in enumerate(cells):
                            t = clean(cell.get_text())
                            if not ref and re.match(r"^\d{5,8}$", t):
                                ref = t
                            link = cell.find("a", href=True)
                            if not title and link:
                                title = clean(link.get_text())
                                href  = link.get("href", "")
                                apply_url = f"{BASE}{href}" if href.startswith("/") else href
                            if title and not dept and not link and len(t) > 5 and not re.match(r"^\d+$", t):
                                dept = t
                        if not title or len(title) < 5:
                            continue
                        dedup_key = ref if ref else f"{title}|{dept}"
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        dept = dept or "Chinese University of Hong Kong"
                        jobs.append({
                            "id":               make_id("CUHK", ref if ref else f"{title}|{dept}"),
                            "title":            title,
                            "rank":             detect_rank(title),
                            "university":       "CUHK",
                            "university_full":  "Chinese University of Hong Kong",
                            "department":       dept,
                            "deadline":         "",
                            "is_new":           "TRUE",
                            "reference":        ref,
                            "position_type":    detect_type(title),
                            "salary":           "",
                            "start_date":       "",
                            "apply_url":        apply_url or URL,
                            "description":      f"{title} — {dept}. Please visit the application link for full details.",
                        })
                        page_jobs += 1
                        sect_count += 1

                    # Next button: check disabled via BS4 before clicking
                    next_link = soup.find("a", title="Next") or soup.find("a", string=re.compile(r"^Next$", re.I))
                    if not next_link:
                        break
                    link_class = " ".join(next_link.get("class", [])).lower()
                    if "disabled" in link_class or "inactive" in link_class:
                        break
                    next_btn = page.query_selector("a[title='Next'], a:has-text('Next')")
                    if next_btn and page_num < 50:
                        try:
                            next_btn.click(timeout=5000)
                        except Exception:
                            break
                        page.wait_for_timeout(3000)
                        page_num += 1
                    else:
                        break

                print(f"  ↳ {section_name}: {sect_count} jobs ({page_num} page(s))")
                page.close()

            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ CUHK: {len(jobs)} jobs found")
    return jobs


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

SCRAPERS = {
    "polyu":  scrape_polyu,
    "eduhk":  scrape_eduhk,
    "lingnan": scrape_lingnan,
    "hku":    scrape_hku,
    "hkust":  scrape_hkust,
    "cityu":  scrape_cityu,
    "hkbu":   scrape_hkbu,
    "cuhk":   scrape_cuhk,
}


def deduplicate(jobs):
    """Remove duplicate jobs by id."""
    seen = set()
    unique = []
    for j in jobs:
        if j["id"] not in seen:
            seen.add(j["id"])
            unique.append(j)
    return unique


def main():
    parser = argparse.ArgumentParser(description="HKAcadJobs Scraper")
    parser.add_argument("--uni", help="Scrape one university only (e.g. polyu, hku)")
    parser.add_argument("--output", help="Output CSV path (default: ../jobs.csv)")
    parser.add_argument("--debug-polyu", metavar="REF", help="Debug a single PolyU detail page")
    args = parser.parse_args()

    if args.debug_polyu:
        print(f"🔍 Debugging PolyU detail page for ref: {args.debug_polyu}")
        scrape_polyu_detail(args.debug_polyu, debug=True)
        return


    if args.output:
        global OUTPUT_FILE
        OUTPUT_FILE = Path(args.output)

    print(f"\n🎓 HKAcadJobs Scraper — {TODAY.strftime('%d %B %Y')}")
    print("=" * 50)

    # Load previous run to detect which jobs are genuinely new today
    today_str = TODAY.strftime("%Y-%m-%d")
    existing = {}  # id → date_added from previous CSV
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    jid = row.get("id", "")
                    if jid:
                        existing[jid] = row.get("date_added", today_str)
            print(f"↳ Previous CSV: {len(existing)} jobs loaded")
        except Exception as e:
            print(f"  ⚠️  Could not read previous CSV: {e}")

    all_jobs = []

    if args.uni:
        # Scrape single university
        uni = args.uni.lower()
        if uni not in SCRAPERS:
            print(f"Unknown university: {uni}. Options: {', '.join(SCRAPERS.keys())}")
            sys.exit(1)
        all_jobs = SCRAPERS[uni]()
    else:
        # Scrape all
        for name, scraper in SCRAPERS.items():
            try:
                jobs = scraper()
                all_jobs.extend(jobs)
                time.sleep(1)  # polite delay between universities
            except Exception as e:
                print(f"  ❌ {name} crashed: {e}")

    all_jobs = deduplicate(all_jobs)
    # Keep: active jobs, no-deadline jobs, and jobs closed within the last 30 days
    all_jobs = [j for j in all_jobs if is_within_retention(j.get("deadline", ""))]

    # Override is_new and set date_added based on previous run.
    # is_new = TRUE only for job IDs not seen in the previous CSV (new today).
    for j in all_jobs:
        if j["id"] in existing:
            j["is_new"] = "FALSE"
            j["date_added"] = existing[j["id"]]
        else:
            j["is_new"] = "TRUE"
            j["date_added"] = today_str

    new_count    = sum(1 for j in all_jobs if j["is_new"] == "TRUE")
    active_count = sum(1 for j in all_jobs if is_active(j.get("deadline", "")))

    print("\n" + "=" * 50)
    print(f"📊 Total jobs scraped : {len(all_jobs)}")
    print(f"📊 Active (open)      : {active_count}")
    print(f"📊 New today          : {new_count}")
    print(f"📊 Closed / expired   : {len(all_jobs) - active_count}")

    # Write CSV
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"✅ Saved to {OUTPUT_FILE}")
    print(f"🌐 Your website will update automatically within minutes.\n")


if __name__ == "__main__":
    main()
