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
import json
import os
import re
import statistics
import sys
import time
import argparse
import hashlib
import urllib.parse
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Output file path (same directory as this script)
OUTPUT_FILE = Path(__file__).parent.parent / "jobs.csv"

# ── CSV columns (must match website expectations)
FIELDNAMES = [
    "id", "title", "rank", "university", "university_full",
    "department", "deadline", "deadline_note", "is_new", "date_added", "date_posted", "reference",
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

HKT = timezone(timedelta(hours=8))
TODAY = datetime.now(HKT).date()


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


def text_fragment_url(url, text):
    """Deep link into a page that lists many jobs: a #:~:text= fragment makes
    supporting browsers scroll to (and highlight) this job's title; others just
    open the page. Used for portals without a page per job (SFU, Chu Hai)."""
    words = " ".join(clean(text).split()[:8])
    if not words:
        return url
    # "-" and "," have special meaning inside text fragments
    frag = urllib.parse.quote(words, safe="").replace("-", "%2D")
    return f"{url.split('#')[0]}#:~:text={frag}"


def infer_dept_from_title(title):
    """Try to extract a department name from a job title string."""
    # Pattern 1: "Role in Department/Subject Area"
    m = re.search(
        r'\bin\s+([A-Za-z][A-Za-z0-9\s&,\-\/\(\)]+?)'
        r'(?:\s*[\/-]\s*(?:Post|Senior|Research|Lecturer|Professor|Assoc|Assis)'
        r'|\s*\((?!Full|Part|several|multiple|part)'
        r'|\s*$)',
        title,
    )
    if m:
        dept = m.group(1).strip().rstrip(',').rstrip('/')
        if 5 < len(dept) < 80 and not re.search(r'^\d', dept):
            return dept
    # Pattern 2: Director/Head "of [Dept]"
    m = re.search(r'\bof\s+([A-Z][A-Za-z0-9\s&,\-\/]{4,60})', title)
    if m:
        dept = m.group(1).strip()
        if len(dept) < 70:
            return dept
    # Pattern 3: "Role (Department/Section)" at end
    m = re.search(r'\(([A-Za-z][A-Za-z0-9\s&,\-\/]{4,60})\)\s*$', title)
    if m:
        candidate = m.group(1).strip()
        if not re.search(r'full.time|part.time|posts?|positions?|\d+\s*posts?|several|multiple|various', candidate, re.I):
            return candidate
    return ""


def detect_rank(title, description=""):
    """Infer rank from job title (and optionally description)."""
    t = title.lower()
    d = description.lower()
    if ("tenure-track" in t or "tenure track" in t or "substantiation-track" in t) and "non-tenure" not in t:
        return "Tenure-Track"
    # Faculty positions — disambiguate using description (Fix 4)
    if re.search(r'\bfaculty\b', t) and re.search(r'\bpositions?\b', t):
        if ("tenure-track" in d or "tenure track" in d) and "non-tenure" not in d:
            return "Tenure-Track"
        if "lecturer" in d:
            return "Senior Lecturer/Lecturer"
    if "teaching-track" in t:        return "Senior Lecturer/Lecturer"   # Fix 1
    if "chair professor" in t:       return "Professor"
    if "associate professor" in t:   return "Associate Professor"
    if "assistant professor" in t:   return "Assistant Professor"
    if "professor" in t:             return "Professor"
    if "postdoc" in t:               return "Postdoctoral"
    if "post-doctoral" in t:         return "Postdoctoral"
    if "post doctoral" in t:         return "Postdoctoral"
    if "research fellow" in t:       return "Postdoctoral"
    if "dean" in t:                  return "Senior Management"
    if "provost" in t:               return "Senior Management"
    if "head of" in t:               return "Senior Management"
    if "vice-chancellor" in t:       return "Senior Management"
    if "vice chancellor" in t:       return "Senior Management"
    if "vice-president" in t:        return "Senior Management"
    if "vice president" in t:        return "Senior Management"
    if "teaching associate" in t:    return "Teaching Assistant"  # Fix 2
    if "teaching assistant" in t:    return "Teaching Assistant"
    if "research engineer" in t:     return "Research Assistant/Associate"  # Fix 3
    if "research assistant" in t:    return "Research Assistant/Associate"
    if "research associate" in t:    return "Research Assistant/Associate"
    if "research officer" in t:      return "Research Assistant/Associate"
    if "lecturer" in t:              return "Senior Lecturer/Lecturer"
    if "teaching fellow" in t:       return "Senior Lecturer/Lecturer"
    if "instructor" in t:            return "Senior Lecturer/Lecturer"
    if "clinical" in t:              return "Senior Lecturer/Lecturer"
    if "teaching consultant" in t:   return "Senior Lecturer/Lecturer"
    if "consultant" in t and any(k in t for k in ("teaching", "language", "academic", "education", "learning")):
        return "Senior Lecturer/Lecturer"
    NON_ACADEMIC_KEYWORDS = (
        "officer", "manager", "executive", "clerk", "clerical",
        "administrative", "administrator", "accountant", "accounting",
        "librarian", "programmer", "technician", "nurse", "counsellor",
        "secretary", "attendant", "helper", "dental", "registrar",
        "coordinator", "consultant", "director",
        "procurement", "laboratory assistant", "lab assistant",
        "office assistant", "security", "systems analyst",
        "phlebotomist", "editor",
        "project assistant", "project associate", "project fellow",
        "project technical",
    )
    if any(k in t for k in NON_ACADEMIC_KEYWORDS):
        return "Non-Academic"
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
    Returns the text unchanged if unparseable (callers compare with the input
    to detect dates); normalise_deadline() cleans up what reaches the CSV.
    """
    if not text:
        return ""
    text = clean(text)
    formats = [
        "%d %B %Y", "%d %b %Y",
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
        "%d/%b/%Y", "%d-%b-%Y", "%d-%B-%Y",
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


def is_within_retention(deadline_str, days=14):
    """Return True if deadline is empty, active, or closed within the last `days` days."""
    if not deadline_str:
        return True
    try:
        d = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        return d >= (TODAY - timedelta(days=days))
    except ValueError:
        return True


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_IN_TEXT = re.compile(
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-[A-Za-z]{3}-\d{4}"
)
_UNTIL_FILLED = re.compile(r"until\b.{0,40}\bfilled|open until|filled", re.I)
_ONGOING = re.compile(r"on-?\s?going|rolling|continuous", re.I)
_REVIEW_START = re.compile(r"review|commenc|consider|screen|start", re.I)


def date_in_text(text):
    """First recognisable date inside free text, as YYYY-MM-DD ('' if none)."""
    for m in _DATE_IN_TEXT.finditer(text or ""):
        s = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", m.group(0))
        s = re.sub(r"\bSept\b", "Sep", s)
        for cand in (s, re.sub(r"\.", "", s), re.sub(r"[.,]", "", s)):
            parsed = parse_date_text(re.sub(r"\s+", " ", cand))
            if ISO_DATE.match(parsed or ""):
                return parsed
    return ""


def normalise_deadline(job):
    """Keep only real dates in `deadline`; wording such as "Applications will be
    considered until the position is filled" goes to `deadline_note` instead
    (it used to sit in `deadline`, breaking sorting and Google's JobPosting)."""
    raw = clean(job.get("deadline", ""))
    note = clean(job.get("deadline_note", ""))
    if raw and not ISO_DATE.match(raw):
        parsed = parse_date_text(raw)
        date_found = parsed if ISO_DATE.match(parsed or "") else date_in_text(raw)
        if date_found and _REVIEW_START.search(raw):
            # "Review of applications starts on …" is not a closing date
            if not note:
                pretty = datetime.strptime(date_found, "%Y-%m-%d").strftime("%-d %b %Y")
                note = f"Applications reviewed from {pretty}"
            date_found = ""
        elif not note and len(raw) > 2 and not date_found:
            note = ("Open until filled" if _UNTIL_FILLED.search(raw)
                    else "Ongoing recruitment" if _ONGOING.search(raw) else raw[:120])
        raw = date_found
    job["deadline"] = raw
    job["deadline_note"] = note


_KEY_DATE_CLOSING = re.compile(
    r"^(\s*•\s*(?:Application\s+)?(?:Closing\s+date|Application\s+deadline|Deadline)[^:\n]{0,30}:\s*)(.+)$",
    re.I | re.M,
)


_KEY_DATE_START = re.compile(r"^\s*•\s*(?:Expected\s+|Anticipated\s+)?Start(?:ing)?\s+date[^:\n]{0,20}:\s*(.+)$", re.I | re.M)


def reconcile_summary_deadline(job):
    """Keep the AI summary's closing date and the deadline column consistent.

    Summaries are cached, so when a portal extends a deadline the old date
    stayed in the summary (e.g. VTC: column 31 Oct, summary 30 Jul). The
    listing is authoritative: rewrite the summary's closing-date bullet to
    match it. When the listing has no deadline, take it from the summary.
    """
    desc = job.get("description") or ""
    if "**Key Dates**" not in desc:
        return
    if not job.get("start_date"):
        start = _KEY_DATE_START.search(desc)
        if start and not re.search(r"not specified", start.group(1), re.I):
            job["start_date"] = clean(start.group(1))[:80]
    m = _KEY_DATE_CLOSING.search(desc)
    if not m:
        return
    summary_date = date_in_text(m.group(2))
    if not job.get("deadline"):
        if summary_date and not job.get("deadline_note"):
            job["deadline"] = summary_date
        return
    if summary_date and summary_date != job["deadline"]:
        pretty = datetime.strptime(job["deadline"], "%Y-%m-%d").strftime("%-d %B %Y")
        job["description"] = desc[:m.start(2)] + pretty + desc[m.end(2):]


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


# ── Marker used in placeholder descriptions (skip summarising these)
PLACEHOLDER_MARKER = "Please visit the application link"

# ── Cache populated by main() before scrapers run; lets scrapers skip detail
#    page fetches for jobs that already have a good summary.
_existing_descriptions: dict = {}
_previous_rows: dict = {}   # id → previous CSV row (e.g. to reuse deadlines)


def due_for_recheck(job_id):
    """True on one weekday per job id — spreads weekly re-checks across the week."""
    return int(hashlib.md5(job_id.encode()).hexdigest(), 16) % 7 == TODAY.weekday()


BOT_MARKERS = ("security check", "not a bot", "verify that you are", "cloudflare", "complete the security")

def _has_good_desc(job_id: str) -> bool:
    """True if a prior run already produced a real structured summary."""
    d = _existing_descriptions.get(job_id, "")
    if not d or PLACEHOLDER_MARKER in d or len(d) <= 80:
        return False
    if any(m in d.lower() for m in BOT_MARKERS):
        return False
    # Must be new structured format — old plain-prose summaries are re-fetched
    if "**" not in d or "•" not in d:
        return False
    return True


# ── AI summaries (Claude Haiku 4.5, structured output)
SUMMARY_MODEL   = "claude-haiku-4-5-20251001"
SUMMARY_PRICES  = (1.00, 5.00)   # US$ per million input / output tokens; batches cost half
BATCH_MIN_JOBS  = 10             # use the Batches API from this many summaries up
BATCH_MAX_WAIT  = 20 * 60        # seconds; unfinished batch items are then summarised directly

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "duties":       {"type": "array", "items": {"type": "string"}},
        "requirements": {"type": "array", "items": {"type": "string"}},
        "appointment":  {"type": "string"},
        "key_dates":    {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "date": {"type": "string"}},
            "required": ["label", "date"],
            "additionalProperties": False,
        }},
        "salary":       {"type": "string"},
        "start_date":   {"type": "string"},
        "closing_date": {"type": "string"},
    },
    "required": ["duties", "requirements", "appointment", "key_dates", "salary", "start_date", "closing_date"],
    "additionalProperties": False,
}


def _summary_request(raw_text, title, dept):
    return {
        "model": SUMMARY_MODEL,
        "max_tokens": 1500,
        "output_config": {"format": {"type": "json_schema", "schema": _SUMMARY_SCHEMA}},
        "messages": [{
            "role": "user",
            "content": (
                "Summarise this academic job advertisement for a job board. Be concise: every list "
                "item is one short sentence. Do not mention the university's name or reference numbers.\n"
                "- duties: the main duties and responsibilities (2-6 items)\n"
                "- requirements: required and preferred qualifications and experience (2-6 items)\n"
                "- appointment: the terms in one line, e.g. 'Full-time, 2-year contract (renewable)'; "
                "'Not specified' if not stated\n"
                "- key_dates: every date mentioned, each with a clear label such as 'Closing date', "
                "'Review date', 'Interview date', 'Start date' or 'Posted date'; empty if none\n"
                "- salary: the salary, salary range or grade exactly as stated "
                "(e.g. 'HK$50,000 - 65,000 per month'); empty string if not stated\n"
                "- start_date: the expected start date as stated; empty string if not stated\n"
                "- closing_date: the application closing date as YYYY-MM-DD, only if a specific date "
                "is stated; otherwise empty string\n\n"
                f"Job title: {title}\nDepartment: {dept}\n\nAdvertisement:\n{raw_text[:12000]}"
            ),
        }],
    }


def _render_summary(data):
    """The structured summary in the site's display format (**Header** + • bullets)."""
    def bullets(items):
        items = [clean(i) for i in items if clean(i)]
        return "\n".join(f"• {i}" for i in items) if items else "• Not specified"
    dates = [f"{clean(d.get('label'))}: {clean(d.get('date'))}" for d in data.get("key_dates") or []
             if clean(d.get("label")) and clean(d.get("date"))]
    return (
        "**Duties & Responsibilities**\n" + bullets(data.get("duties") or []) + "\n\n"
        "**Requirements & Qualifications**\n" + bullets(data.get("requirements") or []) + "\n\n"
        "**Appointment**\n" + bullets([data.get("appointment") or "Not specified"]) + "\n\n"
        "**Key Dates**\n" + bullets(dates)
    )


def _parse_summary(message):
    """(summary text, extras) from a structured-output response; raises if unusable."""
    if message.stop_reason == "max_tokens":
        raise ValueError("summary was cut off at max_tokens")
    data = json.loads(next(b.text for b in message.content if b.type == "text"))
    extras = {k: clean(data.get(k) or "") for k in ("salary", "start_date", "closing_date")}
    return _render_summary(data), extras


def apply_summary_extras(job, extras):
    """Fill fields the listing didn't provide from the summary's structured fields."""
    if extras.get("salary") and not job.get("salary"):
        job["salary"] = extras["salary"][:120]
    if extras.get("start_date") and not job.get("start_date"):
        job["start_date"] = extras["start_date"][:80]
    closing = extras.get("closing_date", "")
    if ISO_DATE.match(closing) and not job.get("deadline") and not job.get("deadline_note"):
        job["deadline"] = closing


def summarise_job(raw_text, title, dept, client=None):
    """One job → (summary, extras). Falls back to (raw_text, {}) on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return raw_text, {}
    try:
        import anthropic
        client = client or anthropic.Anthropic(api_key=api_key)
        return _parse_summary(client.messages.create(**_summary_request(raw_text, title, dept)))
    except Exception as e:
        print(f"  ⚠️  Summarisation failed for '{title}': {e}")
        return raw_text, {}


def summarise_description(raw_text, title, dept):
    """Summary text only (kept for callers that don't use the extras)."""
    return summarise_job(raw_text, title, dept)[0]


def summarise_jobs(jobs):
    """Summarise jobs in place (description, plus salary / start date / deadline
    when the listing lacked them). Uses the Message Batches API (half price)
    for larger runs; anything it doesn't finish in time is done directly."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not jobs:
        return
    if not api_key:
        print(f"  ℹ️  ANTHROPIC_API_KEY not set — {len(jobs)} descriptions left as raw text")
        return
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    pending = {str(i): j for i, j in enumerate(jobs)}
    tokens = {"direct": [0, 0], "batch": [0, 0]}

    def done(key, message, kind):
        summary, extras = _parse_summary(message)
        job = pending.pop(key)
        job["description"] = summary
        apply_summary_extras(job, extras)
        tokens[kind][0] += message.usage.input_tokens
        tokens[kind][1] += message.usage.output_tokens

    print(f"\n🤖 Summarising {len(jobs)} descriptions via Claude Haiku...")
    if len(jobs) >= BATCH_MIN_JOBS:
        try:
            batch = client.messages.batches.create(requests=[
                {"custom_id": key, "params": _summary_request(j["description"], j["title"], j.get("department", ""))}
                for key, j in pending.items()
            ])
            print(f"  ↳ Batch {batch.id} submitted ({len(pending)} requests)")
            give_up = time.time() + BATCH_MAX_WAIT
            while batch.processing_status != "ended" and time.time() < give_up:
                time.sleep(15)
                batch = client.messages.batches.retrieve(batch.id)
            if batch.processing_status != "ended":
                print(f"  ⚠️  Batch unfinished after {BATCH_MAX_WAIT // 60} min — cancelling, finishing directly")
                client.messages.batches.cancel(batch.id)
                for _ in range(12):          # cancellation keeps finished results
                    time.sleep(10)
                    batch = client.messages.batches.retrieve(batch.id)
                    if batch.processing_status == "ended":
                        break
            if batch.processing_status == "ended":
                for res in client.messages.batches.results(batch.id):
                    if res.result.type == "succeeded" and res.custom_id in pending:
                        try:
                            done(res.custom_id, res.result.message, "batch")
                        except Exception as e:
                            print(f"  ⚠️  Unusable batch result for '{pending[res.custom_id]['title']}': {e}")
        except Exception as e:
            print(f"  ⚠️  Batch summarisation failed ({e}); summarising directly")

    for key, job in list(pending.items()):   # small runs, and anything the batch missed
        try:
            done(key, client.messages.create(**_summary_request(job["description"], job["title"],
                                                                 job.get("department", ""))), "direct")
        except Exception as e:
            print(f"  ⚠️  Summarisation failed for '{job['title']}': {e}")

    (d_in, d_out), (b_in, b_out) = tokens["direct"], tokens["batch"]
    cost = ((d_in + b_in / 2) * SUMMARY_PRICES[0] + (d_out + b_out / 2) * SUMMARY_PRICES[1]) / 1e6
    print(f"  ✅ Summarised {len(jobs) - len(pending)}/{len(jobs)} "
          f"(batch {tokens['batch'][0] and 'yes' or 'no'}; tokens in {d_in + b_in:,}, out {d_out + b_out:,}; ≈ US${cost:.3f})")


# ══════════════════════════════════════════════════════════════════
# SCRAPERS — one function per university
# ══════════════════════════════════════════════════════════════════

def scrape_polyu_detail(ref, debug=False):
    """
    Fetch a PolyU job detail page and extract the description and posting date.
    URL: https://jobs.polyu.edu.hk/job_detail.php?job={ref}
    Returns (description: str, date_posted: str) — either may be "" on failure.
    """
    url = f"https://jobs.polyu.edu.hk/job_detail.php?job={ref}"
    soup = get_soup(url, timeout=10)
    if not soup:
        return "", ""

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
        return "", ""

    # Extract posting date — "Posting date: DD Month YYYY" appears in page body
    page_text = soup.get_text("\n")
    date_posted = ""
    pd_m = re.search(r"Posting date[:\s]+([A-Za-z0-9 ]+)", page_text, re.I)
    if pd_m:
        date_posted = parse_date_text(pd_m.group(1).strip())

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
            return "\n\n".join(parts)[:8000], date_posted

    # Fallback: largest text block
    candidates = [
        clean(tag.get_text(" "))
        for tag in soup.find_all(["div", "td", "section"])
        if 150 < len(clean(tag.get_text(" "))) < 5000
    ]
    if candidates:
        return max(candidates, key=len)[:8000], date_posted

    return "", date_posted


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

    # Step 2: fetch detail pages only for jobs within the retention window
    active_jobs = [j for j in raw_jobs if is_within_retention(j["deadline"])]
    skipped = len(raw_jobs) - len(active_jobs)
    print(f"  ↳ Fetching detail pages for {len(active_jobs)} jobs (skipped {skipped} expired)...")
    jobs = []
    for idx, j in enumerate(active_jobs, 1):
        ref      = j["ref"]
        title    = j["title"]
        dept     = j["dept"]
        deadline = j["deadline"]

        apply_url                = f"{base}/job_detail.php?job={ref}"
        description, date_posted = scrape_polyu_detail(ref)
        if not description:
            description = j.get("description") or f"{title} — {dept}. See {apply_url} for full details."

        if idx % 10 == 0 or idx == len(active_jobs):
            print(f"  ↳ {idx}/{len(active_jobs)} detail pages fetched")

        jobs.append({
            "id":               make_id("POLYU", ref),
            "title":            title,
            "rank":             detect_rank(title),
            "university":       "PolyU",
            "university_full":  "Hong Kong Polytechnic University",
            "department":       dept,
            "deadline":         deadline,
            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
            "date_posted":      date_posted,
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
                        # Extract PDF links in page order (one per job card)
                        pdf_links = pw_page.evaluate(
                            "Array.from(document.querySelectorAll('a[href*=\"/cms/f/career\"]')).map(a => a.href)"
                        )
                    except Exception as page_err:
                        print(f"  ↳ {pos_type} p{page_num}: error ({page_err.__class__.__name__})")
                        try: pw_page.close()
                        except: pass
                        break

                    ad_count = full_text.count("Ad Date:")
                    if ad_count == 0:
                        break

                    jobs_before = len(jobs)
                    pdf_idx = 0
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

                        # Ad Date immediately follows the "Ad Date:" anchor
                        ad_raw = full_text[m.end():m.end()+30].strip().splitlines()[0].strip()
                        date_posted = parse_date_text(ad_raw) if ad_raw else ""

                        apply_url = pdf_links[pdf_idx] if pdf_idx < len(pdf_links) else f"{BASE}/en/current-openings?category={category}&department=&q="
                        pdf_idx += 1
                        jobs.append({
                            "id":               make_id("EDUHK", ref if ref else f"{title[:40]}_{dept[:20]}"),
                            "title":            title,
                            "rank":             detect_rank(title),
                            "university":       "EdUHK",
                            "university_full":  "Education University of Hong Kong",
                            "department":       dept or infer_dept_from_title(title) or "Education University of Hong Kong",
                            "deadline":         deadline,
                            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                            "date_posted":      date_posted,
                            "reference":        ref,
                            "position_type":    detect_type(title),
                            "salary":           "",
                            "start_date":       "",
                            "apply_url":        apply_url,
                            "description":      "",
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

    # Fetch descriptions from PDF job ads (EdUHK only uses PDFs, no HTML detail pages)
    # EdUHK's server requires legacy SSL renegotiation — use urllib with a permissive context.
    needs_desc = [j for j in jobs if not _has_good_desc(j["id"]) and j.get("apply_url", "").endswith(".pdf")]
    if needs_desc:
        import ssl, urllib.request, io
        try:
            from pypdf import PdfReader
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            ssl_ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
            PREAMBLE_END = "in support of its strategic development in diverse areas."
            found_pdf = 0
            print(f"  ↳ Fetching {len(needs_desc)} PDF descriptions...")
            for j in needs_desc:
                try:
                    req = urllib.request.Request(j["apply_url"], headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
                        data = resp.read()
                    reader = PdfReader(io.BytesIO(data))
                    text = "\n".join(page.extract_text() or "" for page in reader.pages)
                    # Skip the standard EdUHK university preamble if present
                    idx = text.find(PREAMBLE_END)
                    body = text[idx + len(PREAMBLE_END):].strip() if idx >= 0 else text.strip()
                    # Take meaningful lines (>50 chars), skip trailing boilerplate
                    lines = []
                    for ln in body.splitlines():
                        ln = ln.strip()
                        if not ln:
                            continue
                        if re.match(r'^(Salary will be|The University only accepts|Applicants should complete|For enquiries|Further information)', ln, re.I):
                            break
                        if len(ln) > 50:
                            lines.append(ln)
                    if lines:
                        j["description"] = "\n\n".join(lines[:60])[:8000]
                        found_pdf += 1
                except Exception:
                    pass
            print(f"  ↳ PDF descriptions: {found_pdf}/{len(needs_desc)} extracted")
        except ImportError:
            print("  ⚠️  pypdf not installed — skipping EdUHK PDF extraction")

    print(f"  ✅ EdUHK: {len(jobs)} jobs found")
    return jobs


def scrape_lingnan():
    """
    Lingnan — lingnan.csod.com (Cornerstone OnDemand ATS)
    The career site lists jobs through a JSON search API
    (uk.api.csod.com/rec-job-search/external/jobs) using a token issued to the
    page. Replaying that request with pageSize=200 returns every job at once;
    falls back to clicking through the result pages. Department comes from the
    title (text after the last comma).
    """
    print("📋 Scraping Lingnan...")
    SITE = "https://lingnan.csod.com/ux/ats/careersite/4/home"

    def make_job(ref, full_title, posted="", expires="", desc_html=""):
        # "Senior HR Officer, Human Resources Office" → title, dept
        if "," in full_title:
            last_comma = full_title.rfind(",")
            title, dept = full_title[:last_comma].strip(), full_title[last_comma + 1:].strip()
        else:
            title, dept = full_title, "Lingnan University"
        desc = BeautifulSoup(desc_html or "", "html.parser").get_text("\n", strip=True)
        if len(desc) < 300 or "INTERNAL JOB DESCRIPTION" in desc.upper():
            desc = f"{title} — {dept}. Please visit the application link for full details."
        return {
            "id":               make_id("LU", ref or title[:25]),
            "title":            title,
            "rank":             detect_rank(title),
            "university":       "LU",
            "university_full":  "Lingnan University",
            "department":       dept,
            "deadline":         expires,
            "is_new":           "TRUE",
            "date_posted":      posted,
            "reference":        ref,
            "position_type":    detect_type(title),
            "salary":           "",
            "start_date":       "",
            "apply_url":        f"{SITE}/requisition/{ref}?c=lingnan",
            "description":      desc[:8000],
        }

    def us_date(text):
        # CSOD dates are M/D/YYYY ("9/25/2026"); "-" means none
        try:
            return datetime.strptime(clean(text), "%m/%d/%Y").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return ""

    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)
            searches = []
            page.on("request", lambda r: searches.append(r) if "rec-job-search" in r.url and r.method == "POST" else None)
            page.goto(f"{SITE}?c=lingnan", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)

            # 1) Replay the page's own search request asking for every job
            if searches:
                try:
                    req = searches[0]
                    payload = json.loads(req.post_data or "{}")
                    payload["pageNumber"], payload["pageSize"] = 1, 200
                    keep = ("authorization", "content-type", "csod-accept-language", "accept")
                    resp = page.request.post(req.url, data=json.dumps(payload),
                                             headers={k: v for k, v in req.headers.items() if k.lower() in keep})
                    data = (resp.json() or {}).get("data") or {}
                    for r in data.get("requisitions") or []:
                        ref = str(r.get("requisitionId") or "")
                        full_title = clean(r.get("displayJobTitle") or "")
                        if not ref or len(full_title) < 5 or ref in seen:
                            continue
                        seen.add(ref)
                        jobs.append(make_job(ref, full_title, us_date(r.get("postingEffectiveDate")),
                                             us_date(r.get("postingExpirationDate")), r.get("externalDescription")))
                    print(f"  ↳ Search API: {len(jobs)} of {data.get('totalCount')} jobs")
                except Exception as e:
                    print(f"  ⚠️  Search API replay failed ({e}); paging through results instead")

            # 2) Fallback: click through the result pages, waiting for each to change
            if not jobs:
                page_num = 1
                while page_num <= 20:
                    for a in BeautifulSoup(page.content(), "html.parser").find_all("a", href=re.compile(r"requisition", re.I)):
                        ref_match = re.search(r"requisition/(\d+)", a.get("href", ""))
                        ref = ref_match.group(1) if ref_match else ""
                        full_title = clean(a.get_text())
                        if not ref or len(full_title) < 5 or ref in seen:
                            continue
                        seen.add(ref)
                        jobs.append(make_job(ref, full_title))
                    first = page.evaluate("() => document.querySelector('a[href*=requisition]')?.getAttribute('href')")
                    clicked = page.evaluate(f"""() => {{
                        const btn = [...document.querySelectorAll('[class*="paginat"] a, [class*="paginat"] button, nav a, nav button')]
                            .find(b => parseInt(b.textContent.trim()) === {page_num + 1})
                            || document.querySelector('[aria-label="Next"]:not([disabled]), [title="Next"]:not([disabled])');
                        if (btn) {{ btn.click(); return true; }}
                        return false;
                    }}""")
                    if not clicked:
                        break
                    try:
                        page.wait_for_function(
                            "f => document.querySelector('a[href*=requisition]')?.getAttribute('href') !== f",
                            arg=first, timeout=15000)
                    except Exception:
                        print(f"  ⚠️  Page {page_num + 1} didn't load")
                        break
                    page_num += 1

            # Fetch detail pages for descriptions (skip known good summaries)
            to_fetch = [j for j in jobs if not _has_good_desc(j["id"]) and PLACEHOLDER_MARKER in j["description"]]
            if to_fetch:
                print(f"  ↳ Fetching {len(to_fetch)} detail pages for descriptions...")
                found = 0
                for j in to_fetch:
                    try:
                        page.goto(j["apply_url"], timeout=30000, wait_until="networkidle")
                        page.wait_for_timeout(1500)
                        text = page.inner_text("body")
                        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                        if lines:
                            j["description"] = "\n\n".join(lines[:60])[:8000]
                            found += 1
                    except Exception:
                        pass
                print(f"  ↳ Got descriptions for {found}/{len(to_fetch)} jobs")
            # Restore cached summaries for skipped jobs
            for j in jobs:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ Lingnan: {len(jobs)} jobs found")
    return jobs


def scrape_hku():
    """
    HKU — jobs.hku.hk/en/listing/ (PageUp ATS)
    Fetches every listing row in one request (?page=1&page-items=1000) instead of
    clicking "More Jobs"; falls back to loading that URL in a browser.
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

    # The listing's "More Jobs" button only fetches the next 20 rows
    # (page=N&page-items=20). Asking for every row in one page is a single
    # request that can't stop half-way — the old click loop waited a fixed
    # 1.5 s per batch and quit early whenever the site was slow.
    LISTING_ALL = "https://jobs.hku.hk/en/listing/?page=1&page-items=1000"
    listing_html = None
    try:
        resp = requests.get(LISTING_ALL, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        listing_html = resp.text
    except Exception as e:
        print(f"  ⚠️  Direct listing fetch failed ({e}); retrying in a browser")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            if listing_html is None:
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(LISTING_ALL, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_selector("a[href*='/en/job/']", timeout=30000)
                listing_html = page.content()
                page.close()

            seen = set()
            parsed = parse_jobs(listing_html, seen)
            jobs.extend(parsed)
            listed = len(set(re.findall(r'href="/en/job/(\d+)', listing_html)))
            print(f"  ↳ Listing has {listed} job links; parsed {len(parsed)} jobs (admin roles skipped)")
            more = BeautifulSoup(listing_html, "html.parser").select_one("a.more-link .count")
            if more and clean(more.get_text()).isdigit() and int(clean(more.get_text())) > 0:
                print(f"  ⚠️  Listing still reports {clean(more.get_text())} more jobs — raise page-items")

            # Fetch detail pages for descriptions (skip known good summaries)
            # Use fresh browser contexts in batches to avoid session-based rate limiting.
            # HKU detail pages are AWS WAF protected — only the first ~35 requests succeed
            # before being blocked. Prioritise tenure-track/lecturer roles so the most
            # valuable jobs get descriptions first.
            RANK_PRIORITY = {
                "Tenure-Track": 0, "Professor": 1, "Associate Professor": 2,
                "Assistant Professor": 3, "Senior Lecturer/Lecturer": 4, "Lecturer": 4,
                "Postdoctoral": 5, "Research Assistant/Associate": 6,
            }
            active = [j for j in parsed if is_within_retention(j["deadline"]) and not _has_good_desc(j["id"])]
            active.sort(key=lambda j: (
                RANK_PRIORITY.get(j.get("rank", ""), 99),
                -(datetime.strptime(j["date_added"], "%Y-%m-%d").toordinal() if j.get("date_added") else 0),
            ))
            if active:
                import random
                print(f"  ↳ Fetching {len(active)} detail pages for descriptions (priority: academic first)...")
                found = 0
                BATCH = 20  # fresh context every N requests
                for batch_start in range(0, len(active), BATCH):
                    batch = active[batch_start:batch_start + BATCH]
                    ctx = browser.new_context()
                    ctx.set_extra_http_headers(HEADERS)
                    detail_page = ctx.new_page()
                    for idx_in_batch, j in enumerate(batch):
                        idx = batch_start + idx_in_batch + 1
                        try:
                            detail_page.goto(j["apply_url"], timeout=20000, wait_until="domcontentloaded")
                            detail_page.wait_for_timeout(random.randint(2500, 4500))
                            text = detail_page.inner_text("body")
                            if any(m in text.lower() for m in BOT_MARKERS):
                                if _has_good_desc(j["id"]):
                                    j["description"] = _existing_descriptions[j["id"]]
                                else:
                                    j["description"] = PLACEHOLDER_MARKER
                                continue
                            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                            # Guard against short/error pages slipping through WAF check
                            if lines and len(" ".join(lines)) >= 200:
                                j["description"] = "\n\n".join(lines[:60])[:8000]
                                found += 1
                            else:
                                j["description"] = PLACEHOLDER_MARKER
                        except Exception:
                            j["description"] = PLACEHOLDER_MARKER
                        if idx % 10 == 0 or idx == len(active):
                            print(f"  ↳ {idx}/{len(active)} done")
                    detail_page.close()
                    ctx.close()
                print(f"  ↳ Got descriptions for {found}/{len(active)} jobs")
            # Restore cached summaries for skipped jobs
            for j in parsed:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
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

                # Map Interfolio links to job IDs positionally:
                # walk all text nodes in order, collect (jobId, linkHref) pairs where
                # each link is assigned to the most recently seen Job ID before it.
                try:
                    il_map = page.evaluate("""
                        () => {
                            const result = {};
                            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ALL);
                            let currentJobId = null;
                            let node;
                            while (node = walker.nextNode()) {
                                if (node.nodeType === Node.TEXT_NODE) {
                                    const m = node.textContent.trim().match(/^Job ID: (\\d+)$/);
                                    if (m) currentJobId = m[1];
                                } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'A') {
                                    const href = node.href || '';
                                    if (currentJobId && href.includes('interfolio') && !result[currentJobId]) {
                                        result[currentJobId] = href;
                                    }
                                }
                            }
                            return result;
                        }
                    """)
                    for j in jobs:
                        if j["reference"] in il_map:
                            new_url = il_map[j["reference"]]
                            # Refresh the cached summary only if the link changed since
                            # the last run. (This compared against the PeopleSoft URL
                            # built above, so it always differed and ~50 HKUST jobs
                            # were re-summarised every day.)
                            prev_url = (_previous_rows.get(j["id"]) or {}).get("apply_url", "")
                            if prev_url and prev_url != new_url:
                                _existing_descriptions.pop(j["id"], None)
                            j["apply_url"] = new_url
                except Exception:
                    pass

                page.close()

            # Fetch Interfolio detail pages only. The PeopleSoft links are the ones
            # HKUST itself publishes, but their pages need a portal session.
            to_fetch = [
                j for j in jobs
                if is_within_retention(j["deadline"])
                and not _has_good_desc(j["id"])
                and "interfolio" in j.get("apply_url", "")
            ]
            if to_fetch:
                print(f"  ↳ Fetching {len(to_fetch)} detail pages for descriptions...")
                detail_page = browser.new_page()
                detail_page.set_extra_http_headers(HEADERS)
                found = 0
                for idx, j in enumerate(to_fetch, 1):
                    try:
                        detail_page.goto(j["apply_url"], timeout=20000, wait_until="networkidle")
                        detail_page.wait_for_timeout(2000)
                        text = detail_page.inner_text("body")
                        if any(m in text.lower() for m in BOT_MARKERS):
                            continue
                        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                        if lines:
                            j["description"] = "\n\n".join(lines[:60])[:8000]
                            found += 1
                    except Exception:
                        pass
                    if idx % 5 == 0 or idx == len(to_fetch):
                        print(f"  ↳ {idx}/{len(to_fetch)} done")
                detail_page.close()
                print(f"  ↳ Got descriptions for {found}/{len(to_fetch)} jobs")
            # Restore cached summaries for skipped/failed jobs
            for j in jobs:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ HKUST: {len(jobs)} jobs found")
    return jobs


def scrape_cityu_detail(apply_url, page):
    """Fetch a CityU job detail page using Playwright and extract the description."""
    try:
        page.goto(apply_url, timeout=20000, wait_until="networkidle")
        page.wait_for_timeout(1500)
        text = page.inner_text("body")
        if any(m in text.lower() for m in BOT_MARKERS):
            return ""
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
        return "\n\n".join(lines[:60])[:8000] if lines else ""
    except Exception:
        return ""


def scrape_cityu():
    """
    CityU — jobs1.cityu.edu.hk/apply/Default.aspx
    Three static HTML tables: SENIOR, ACAD, RS.
    Fetches detail pages for full descriptions.
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
                "description":      "",  # filled in below
            })
            count += 1

        print(f"  ↳ {pos_type}: {count} jobs")

    # Fetch detail pages for full descriptions using Playwright (bypasses Incapsula)
    active = [j for j in jobs if is_within_retention(j["deadline"]) and not _has_good_desc(j["id"])]
    print(f"  ↳ Fetching {len(active)} detail pages for descriptions...")
    if active:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                found = 0
                for idx, j in enumerate(active, 1):
                    desc = scrape_cityu_detail(j["apply_url"], page)
                    j["description"] = desc or f"{j['title']} — {j['department']}. Please visit the application link for full details."
                    if desc:
                        found += 1
                    if idx % 10 == 0 or idx == len(active):
                        print(f"  ↳ {idx}/{len(active)} detail pages fetched")
                browser.close()
            print(f"  ↳ Got descriptions for {found}/{len(active)} jobs")
        except Exception as e:
            print(f"  ↳ Playwright detail fetch failed: {e}")
            for j in active:
                if not j["description"]:
                    j["description"] = f"{j['title']} — {j['department']}. Please visit the application link for full details."
    # Restore cached summaries for skipped jobs
    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]

    print(f"  ✅ CityU: {len(jobs)} jobs found")
    return jobs


def scrape_hkbu():
    """
    HKBU — Oracle HCM Cloud Candidate Experience (site "hkbu", siteNumber CX_1)
    Calls the same recruitingCEJobRequisitions query the careers site makes
    (finder=findReqs); limit=200 returns every job with its description in one
    request, so no detail pages are needed. (The old "CandidateExperience"
    finder returned 400 on every run.) Falls back to scrolling the careers site.
    """
    print("📋 Scraping HKBU...")

    BASE  = "https://fa-ewqq-saasfaprod1.fa.ocs.oraclecloud.com"
    SITE  = f"{BASE}/hcmUI/CandidateExperience/en/sites/hkbu"
    API   = f"{BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    EXPAND = ("requisitionList.workLocation,requisitionList.otherWorkLocations,"
              "requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields")
    FACETS = "WORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS%3BLOCATIONS"
    PAGE  = 200

    def split_title(full_title, fallback_dept=""):
        # "Senior Officer, Office of Student Affairs" → title, dept
        if "," in full_title:
            last = full_title.rfind(",")
            return full_title[:last].strip(), full_title[last + 1:].strip()
        return full_title, fallback_dept or infer_dept_from_title(full_title)

    def html_text(fragment):
        return BeautifulSoup(fragment, "html.parser").get_text("\n", strip=True) if fragment else ""

    jobs = []
    seen = set()

    try:
        offset, total = 0, None
        while total is None or offset < total:
            finder = (f"findReqs;siteNumber=CX_1,facetsList={FACETS},limit={PAGE},"
                      f"{'offset=' + str(offset) + ',' if offset else ''}sortBy=POSTING_DATES_DESC")
            # Built by hand: requests would re-encode the finder's separators
            resp = requests.get(f"{API}?onlyData=true&expand={EXPAND}&finder={finder}",
                                headers={**HEADERS, "Accept": "application/json"}, timeout=30)
            resp.raise_for_status()
            item = (resp.json().get("items") or [{}])[0]
            reqs = item.get("requisitionList") or []
            total = int(item.get("TotalJobsCount") or 0)
            for r in reqs:
                ref = str(r.get("Id") or "").strip()
                full_title = clean(r.get("Title") or "")
                if not ref or not full_title or ref in seen:
                    continue
                seen.add(ref)
                title, dept = split_title(full_title, clean(r.get("Department") or r.get("Organization") or ""))
                desc_text = "\n\n".join(t for t in (
                    html_text(r.get("ShortDescriptionStr")),
                    html_text(r.get("ExternalResponsibilitiesStr")),
                    html_text(r.get("ExternalQualificationsStr")),
                ) if t)
                if not dept:
                    m = re.search(r"sits under (?:the\s+)?([A-Z][^,.]{3,60}?)(?:\s+at our|\s+campus|,|\.|$)", desc_text)
                    dept = m.group(1).strip() if m else ""
                end_date = str(r.get("PostingEndDate") or "")[:10]
                jobs.append({
                    "id":               make_id("HKBU", ref),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKBU",
                    "university_full":  "Hong Kong Baptist University",
                    "department":       dept or "Hong Kong Baptist University",
                    "deadline":         end_date if ISO_DATE.match(end_date) else "",
                    "is_new":           "TRUE",
                    "date_posted":      str(r.get("PostedDate") or "")[:10],
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        f"{SITE}/job/{ref}",
                    "description":      desc_text[:8000] if len(desc_text) > 80 else
                                        f"{title} — {dept or 'HKBU'}. Please visit the application link for full details.",
                })
            if not reqs:
                break
            offset += PAGE
        print(f"  ↳ API: {len(jobs)} of {total} jobs")
    except Exception as e:
        print(f"  ⚠️  Direct API failed ({e}), falling back to Playwright...")
        jobs, seen = [], set()
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(f"{SITE}/jobs", timeout=60000)
                page.wait_for_timeout(5000)
                prev_height, stale = 0, 0
                for _ in range(60):
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2500)
                    height = page.evaluate("() => document.body.scrollHeight")
                    stale = stale + 1 if height == prev_height else 0
                    if stale >= 3:
                        break
                    prev_height = height
                links = page.evaluate("""() => [...document.querySelectorAll('a[href*="/job/"]')]
                    .map(a => ({href: a.href, title: (a.textContent || '').trim()}))""")
                browser.close()
            for link in links:
                ref_match = re.search(r"/job/(\d+)", link["href"])
                ref = ref_match.group(1) if ref_match else ""
                full_title = clean(link["title"])
                if not ref or len(full_title) < 4 or ref in seen:
                    continue
                seen.add(ref)
                title, dept = split_title(full_title)
                jobs.append({
                    "id":               make_id("HKBU", ref),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKBU",
                    "university_full":  "Hong Kong Baptist University",
                    "department":       dept or "Hong Kong Baptist University",
                    "deadline":         "",
                    "is_new":           "TRUE",
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        f"{SITE}/job/{ref}",
                    "description":      f"{title}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
                })
            # Descriptions for jobs without a cached summary (usually just today's new ones)
            needs_desc = [j for j in jobs if not _has_good_desc(j["id"])]
            if needs_desc:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    detail_page = browser.new_page()
                    detail_page.set_extra_http_headers(HEADERS)
                    for j in needs_desc:
                        try:
                            detail_page.goto(j["apply_url"], timeout=30000, wait_until="domcontentloaded")
                            detail_page.wait_for_timeout(2500)
                            text = detail_page.inner_text("body")
                            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                            if lines and not any(m in text.lower() for m in BOT_MARKERS):
                                j["description"] = "\n\n".join(lines[:60])[:8000]
                        except Exception:
                            pass
                    browser.close()
        except Exception as e2:
            print(f"  ⚠️  Playwright also failed: {e2}")

    # Keep cached summaries
    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]

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
                # One retry: a timed-out section used to be skipped silently,
                # leaving CUHK with half its jobs (30 Jul – 13 Aug 2026)
                loaded = False
                for attempt in (1, 2):
                    try:
                        page.goto(URL, timeout=60000, wait_until="domcontentloaded")
                        page.wait_for_selector("table tr td a", timeout=30000)
                        loaded = True
                        break
                    except Exception:
                        print(f"  ⚠️  {section_name}: job table didn't load (attempt {attempt})")
                if not loaded:
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

    # Reuse closing dates found on earlier runs. Only open a detail page for a
    # job without a cached summary, or — once a week per job — one still
    # missing a date (this used to re-open every CUHK job page every day).
    for j in jobs:
        prev = _previous_rows.get(j["id"])
        if prev and not j["deadline"] and ISO_DATE.match(prev.get("deadline") or ""):
            j["deadline"] = prev["deadline"]
    needs_detail = [j for j in jobs if j["apply_url"] and (
        not _has_good_desc(j["id"]) or (not j["deadline"] and due_for_recheck(j["id"])))]
    if needs_detail:
        print(f"  ↳ Fetching {len(needs_detail)} detail pages for dates/descriptions...")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                detail_page = browser.new_page()
                detail_page.set_extra_http_headers(HEADERS)
                found_date = 0
                found_desc = 0
                for job in needs_detail:
                    try:
                        detail_page.goto(job["apply_url"], timeout=30000, wait_until="networkidle")
                        detail_page.wait_for_timeout(3000)
                        text = detail_page.inner_text("body")
                        # Closing date
                        if not job["deadline"]:
                            m = re.search(r'[Cc]losing\s+[Dd]ate[:\s]+(\w+\s+\d{1,2},\s+\d{4})', text)
                            if m:
                                job["deadline"] = parse_date_text(m.group(1))
                                found_date += 1
                        # Description: skip nav/header, take substantive body lines
                        if not _has_good_desc(job["id"]):
                            # Find start of actual content after the header line
                            start_marker = "Description\n"
                            start = text.find(start_marker)
                            block = text[start + len(start_marker):] if start > 0 else text
                            lines = [l.strip() for l in block.splitlines() if len(l.strip()) > 30]
                            if lines:
                                job["description"] = "\n\n".join(lines[:60])[:8000]
                                found_desc += 1
                    except Exception:
                        pass
                detail_page.close()
                browser.close()
            print(f"  ↳ Found closing dates for {found_date}, descriptions for {found_desc}/{len(needs_detail)} jobs")
        except Exception as pe:
            print(f"  ↳ Detail page fetch failed: {pe}")

    print(f"  ✅ CUHK: {len(jobs)} jobs found")
    return jobs


def scrape_hksyu():
    """
    HKSYU — Hong Kong Shue Yan University
    Single static page: hksyu.edu/en/snippets/external-vacancy
    Four tables: Academic | Non-academic | Project-specific | Research
    Columns: Department / Unit | Position | FT/PT | Closing Date
    Each position links to a PDF (apply_url).
    Deadline format: DD/MM/YYYY or "-"
    """
    print("📋 Scraping HKSYU...")

    URL  = "https://www.hksyu.edu/en/snippets/external-vacancy"
    BASE = "https://www.hksyu.edu"
    jobs = []
    seen = set()

    try:
        soup = get_soup(URL)
        if not soup:
            print("  ⚠️  Could not fetch HKSYU page")
            return jobs

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 4:
                    continue
                dept     = clean(cells[0].get_text())
                title    = clean(cells[1].get_text())
                deadline_raw = clean(cells[3].get_text())

                # Skip header row
                if dept == "Department / Unit" or not title or len(title) < 3:
                    continue
                # Skip non-English/non-meaningful entries
                if not re.search(r'[A-Za-z]', title):
                    continue

                link = row.find("a", href=True)
                apply_url = BASE + link["href"] if link and link["href"].startswith("/") else (link["href"] if link else URL)

                ref_m = re.search(r'/([^/]+)\.pdf', apply_url)
                ref   = ref_m.group(1) if ref_m else ""

                dedup_key = ref if ref else f"{dept}|{title}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Parse deadline — may contain extra text like "or until positions are filled"
                deadline = ""
                date_m = re.search(r'\d{1,2}/\d{1,2}/\d{4}', deadline_raw)
                if date_m:
                    deadline = parse_date_text(date_m.group())

                jobs.append({
                    "id":               make_id("HKSYU", ref or title[:25]),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKSYU",
                    "university_full":  "Hong Kong Shue Yan University",
                    "department":       dept or "Hong Kong Shue Yan University",
                    "deadline":         deadline,
                    "is_new":           "TRUE",
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        apply_url,
                    "description":      PLACEHOLDER_MARKER,
                })

    except Exception as e:
        print(f"  ⚠️  HKSYU scraper failed: {e}")

    # Extract text from PDF apply links for AI summarisation
    needs_desc = [j for j in jobs if not _has_good_desc(j["id"]) and j["apply_url"].endswith(".pdf")]
    if needs_desc:
        print(f"  ↳ Extracting text from {len(needs_desc)} PDF job ads...")
        try:
            import pypdf, io
            found = 0
            for j in needs_desc:
                try:
                    r = requests.get(j["apply_url"], headers=HEADERS, timeout=15)
                    r.raise_for_status()
                    reader = pypdf.PdfReader(io.BytesIO(r.content))
                    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                    if text and len(text) > 80:
                        j["description"] = text[:8000]
                        found += 1
                except Exception:
                    pass
            print(f"  ↳ Got PDF text for {found}/{len(needs_desc)} jobs")
        except ImportError:
            print("  ↳ pypdf not installed — skipping PDF extraction")
    # Restore cached summaries
    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]

    print(f"  ✅ HKSYU: {len(jobs)} jobs found")
    return jobs


def scrape_sfu():
    """
    SFU — Saint Francis University (sfu.edu.hk)
    Four static pages: senior-management, deanship-headship, academic-teaching, research-project
    Each job is in <div class="accordion-wrap">
    Title in <a class="accordion-btn"> — includes "(Ref.: XX/XXX/DEPT)"
    Dept extracted by splitting title on last ", " before a school/office keyword
    Deadline in accordion-content as "Deadline\n<date or 'Until the Position is Filled'>"
    """
    print("📋 Scraping SFU...")

    SECTIONS = [
        ("https://www.sfu.edu.hk/en/career/senior-management-positions/index.html",  "Senior Management"),
        ("https://www.sfu.edu.hk/en/career/deanship-headship-positions/index.html",  "Deanship/Headship"),
        ("https://www.sfu.edu.hk/en/career/academic-teaching-positions/index.html",  "Academic/Teaching"),
        ("https://www.sfu.edu.hk/en/career/research-project-positions/index.html",   "Research/Project"),
    ]
    DEPT_KEYWORDS = re.compile(r'\b(School|Department|Office|Centre|Center|Graduate|Faculty|Institute|Registry|Library)\b', re.I)

    jobs = []
    seen = set()

    for url, section_name in SECTIONS:
        soup = get_soup(url)
        if not soup:
            print(f"  ⚠️  Could not fetch {section_name}")
            continue

        accordions = soup.find_all("div", class_="accordion-wrap")
        sect_count = 0

        for acc in accordions:
            btn = acc.find("a", class_="accordion-btn")
            if not btn:
                continue
            title_raw = clean(btn.get_text())

            # Extract ref
            ref_m = re.search(r'Ref\.:\s*([^\)]+)\)', title_raw)
            ref   = ref_m.group(1).strip() if ref_m else ""

            dedup_key = ref if ref else title_raw
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Strip ref from title
            title_clean = re.sub(r'\s*\(Ref\.[^\)]*\)', '', title_raw).strip()

            # Split dept from title on last ", " if right side looks like a dept/school
            dept = ""
            last_comma = title_clean.rfind(", ")
            if last_comma >= 0:
                right = title_clean[last_comma + 2:]
                if DEPT_KEYWORDS.search(right):
                    dept  = right.strip()
                    title_clean = title_clean[:last_comma].strip()

            # Extract deadline and description from accordion content
            content = acc.find("div", class_="accordion-content")
            deadline = ""
            desc_text = ""
            if content:
                # The line after "Deadline": a date or "Until the Position is Filled"
                # (normalise_deadline() turns the latter into a deadline note)
                lines = [l.strip() for l in content.get_text("\n").splitlines() if l.strip()]
                for i, line in enumerate(lines[:-1]):
                    if re.fullmatch(r"Deadline:?", line, re.I):
                        deadline = lines[i + 1]
                        break
                parts = []
                for p in content.find_all(["p", "li"]):
                    t = clean(p.get_text(" "))
                    if t and len(t) > 20 and not re.match(r'Deadline|Until the Position', t, re.I):
                        parts.append(t)
                if parts:
                    desc_text = "\n\n".join(parts)[:8000]

            jobs.append({
                "id":               make_id("SFU", ref or title_clean[:25]),
                "title":            title_clean,
                "rank":             detect_rank(title_clean),
                "university":       "SFU",
                "university_full":  "Saint Francis University",
                "department":       dept or "Saint Francis University",
                "deadline":         deadline,
                "is_new":           "TRUE",
                "reference":        ref,
                "position_type":    detect_type(title_clean),
                "salary":           "",
                "start_date":       "",
                "apply_url":        text_fragment_url(url, title_clean),
                "description":      desc_text or f"{title_clean}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
            })
            sect_count += 1

        print(f"  ↳ {section_name}: {sect_count} jobs")

    print(f"  ✅ SFU: {len(jobs)} jobs found")
    return jobs


def scrape_hsu():
    """
    HSU — Hang Seng University of Hong Kong
    Static WordPress listing at hsu.edu.hk/en/job-opportunities/
    Links out to recruit.hsu.edu.hk/opening/content.php?id=XXXX
    Title format: "Department - Job Title" — split on first ' - ' or ' – '
    Deadline fetched from detail page: "apply on or before DD Month YYYY"
    """
    print("📋 Scraping HSU...")

    LISTING_URL = "https://www.hsu.edu.hk/en/job-opportunities/"
    jobs = []
    seen = set()

    try:
        soup = get_soup(LISTING_URL)
        if not soup:
            print("  ⚠️  Could not fetch HSU listing page")
            return jobs

        job_links = [a for a in soup.find_all("a", href=True)
                     if "recruit.hsu.edu.hk/opening/content.php" in a["href"]]

        for a in job_links:
            full_text = clean(a.get_text())
            if not full_text:
                continue
            apply_url = a["href"]
            ref_m = re.search(r"id=(\d+)", apply_url)
            ref   = ref_m.group(1) if ref_m else ""

            if ref in seen:
                continue
            seen.add(ref or full_text)

            # Split "Department - Title" on first dash separator
            sep = " – " if " – " in full_text else " - "
            parts = full_text.split(sep, 1)
            dept  = parts[0].strip() if len(parts) > 1 else ""
            title = parts[1].strip() if len(parts) > 1 else full_text

            # Fetch detail page for deadline and description
            deadline = ""
            desc_text = ""
            detail_soup = get_soup(apply_url)
            if detail_soup:
                body = detail_soup.get_text()
                m = re.search(r'(?:on or before|by|before)\s+(\d{1,2}\s+\w+\s+202\d)', body, re.I)
                if m:
                    deadline = parse_date_text(m.group(1))
                for tag in detail_soup.find_all(["nav", "header", "footer", "script", "style"]):
                    tag.decompose()
                candidates = [
                    clean(tag.get_text(" "))
                    for tag in detail_soup.find_all(["div", "section", "article", "main"])
                    if 150 < len(clean(tag.get_text(" "))) < 5000
                ]
                if candidates:
                    desc_text = max(candidates, key=len)[:8000]

            jobs.append({
                "id":               make_id("HSU", ref or title[:25]),
                "title":            title,
                "rank":             detect_rank(title),
                "university":       "HSU",
                "university_full":  "Hang Seng University of Hong Kong",
                "department":       dept or "Hang Seng University of Hong Kong",
                "deadline":         deadline,
                "is_new":           "TRUE",
                "reference":        ref,
                "position_type":    detect_type(title),
                "salary":           "",
                "start_date":       "",
                "apply_url":        apply_url,
                "description":      desc_text or f"{title} — {dept}. Please visit the application link for full details.",
            })

    except Exception as e:
        print(f"  ⚠️  HSU scraper failed: {e}")

    print(f"  ✅ HSU: {len(jobs)} jobs found")
    return jobs


def scrape_hkmu():
    """
    HKMU — Taleo Enterprise ATS (hkmu.taleo.net)
    Two career sections: full-time + non-full-time posts.
    JS-rendered table: <th> job title/link | dept <td> | closing date <td>
    Closing date already present in table as DD/Mon/YYYY (e.g. 12/Mar/2026).
    Requires networkidle wait for full JS render.
    """
    print("📋 Scraping HKMU...")

    BASE = "https://hkmu.taleo.net"
    SECTIONS = [
        (f"{BASE}/careersection/ex_full_time/jobsearch.ftl?lang=en",                       "Full-time"),
        (f"{BASE}/careersection/ex_non_full_time/jobsearch.ftl?lang=en&portal=8115100149", "Non-full-time"),
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
                page.goto(URL, timeout=60000, wait_until="networkidle")
                page.wait_for_timeout(3000)

                page_num   = 1
                sect_count = 0

                while True:
                    soup = BeautifulSoup(page.content(), "html.parser")
                    table = soup.find("table")
                    if not table:
                        break
                    rows = table.find_all("tr")

                    for row in rows:
                        # Job title is in <th scope="row">, dept and deadline in <td>
                        th = row.find("th", {"scope": "row"})
                        if not th:
                            continue
                        link = th.find("a", href=True)
                        if not link:
                            continue
                        title = clean(link.get_text())
                        if not title or len(title) < 5:
                            continue
                        href      = link.get("href", "")
                        apply_url = f"{BASE}{href}" if href.startswith("/") else href

                        # Ref from job ID in URL (e.g. ?job=26000BV)
                        ref_m = re.search(r"[?&]job=([^&]+)", href)
                        ref   = ref_m.group(1) if ref_m else ""

                        dedup_key = ref if ref else title
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)

                        # dept = 2nd <td>, deadline = 3rd <td>
                        tds = row.find_all("td")
                        dept     = clean(tds[1].get_text()) if len(tds) > 1 else ""
                        deadline_raw = clean(tds[2].get_text()) if len(tds) > 2 else ""
                        deadline = parse_date_text(deadline_raw)
                        dept = dept or "Hong Kong Metropolitan University"

                        jobs.append({
                            "id":               make_id("HKMU", ref or title[:25]),
                            "title":            title,
                            "rank":             detect_rank(title),
                            "university":       "HKMU",
                            "university_full":  "Hong Kong Metropolitan University",
                            "department":       dept,
                            "deadline":         deadline,
                            "is_new":           "TRUE",
                            "reference":        ref,
                            "position_type":    detect_type(title),
                            "salary":           "",
                            "start_date":       "",
                            "apply_url":        apply_url or URL,
                            "description":      f"{title} — {dept}. Please visit the application link for full details.",
                        })
                        sect_count += 1

                    # Pagination via Next button
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

            # Fetch detail pages for descriptions (skip known good summaries)
            to_fetch = [j for j in jobs if is_within_retention(j["deadline"]) and not _has_good_desc(j["id"])]
            if to_fetch:
                print(f"  ↳ Fetching {len(to_fetch)} detail pages for descriptions...")
                detail_page = browser.new_page()
                detail_page.set_extra_http_headers(HEADERS)
                found = 0
                for idx, j in enumerate(to_fetch, 1):
                    try:
                        detail_page.goto(j["apply_url"], timeout=30000, wait_until="networkidle")
                        detail_page.wait_for_timeout(2000)
                        text = detail_page.inner_text("body")
                        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                        if lines:
                            j["description"] = "\n\n".join(lines[:60])[:8000]
                            found += 1
                    except Exception:
                        pass
                    if idx % 10 == 0 or idx == len(to_fetch):
                        print(f"  ↳ {idx}/{len(to_fetch)} done")
                detail_page.close()
                print(f"  ↳ Got descriptions for {found}/{len(to_fetch)} jobs")
            # Restore cached summaries for skipped jobs
            for j in jobs:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ HKMU: {len(jobs)} jobs found")
    return jobs


def scrape_vtc():
    """
    VTC — Vocational Training Council
    Single page: vtc.edu.hk/html/en/career.html
    Tabs: div#tab1 = Full-time, div#tab2 = Part-time
    Columns: Position (Ref. no) | Division/Member Institution | Department/Section | Closing Date
    Link text is empty — title comes from cell text; link provides detail URL.
    Detail page: jobDetail.php?id=<id>  (content in div#innerContent)
    """
    print("📋 Scraping VTC...")

    BASE     = "https://www.vtc.edu.hk/html/en/"
    LIST_URL = BASE + "career.html"
    jobs     = []
    seen     = set()

    try:
        soup = get_soup(LIST_URL)
        if not soup:
            print("  ⚠️  VTC: could not fetch listing page")
            return jobs

        for tab_id, position_type in [("tab1", "Full-time"), ("tab2", "Part-time")]:
            tab_div = soup.find("div", id=tab_id)
            if not tab_div:
                continue

            for table in tab_div.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue

                    # Title is in cell[0] text; link provides detail URL
                    link_tag = row.find("a", href=lambda h: h and "jobDetail" in h)
                    if not link_tag:
                        continue

                    href = link_tag["href"]
                    detail_url = href if href.startswith("http") else BASE + href.lstrip("/")
                    raw_title = clean(cells[0].get_text())

                    # Skip header rows
                    if "Position" in raw_title:
                        continue

                    # Extract ref from trailing parens e.g. "Term Instructor (O/PA_EN/Term I/02/26)"
                    ref   = ""
                    title = raw_title
                    ref_m = re.search(r'\(([^)]+)\)\s*$', raw_title)
                    if ref_m:
                        ref   = ref_m.group(1).strip()
                        title = raw_title[:ref_m.start()].strip()

                    if len(title) < 3:
                        continue

                    division    = clean(cells[1].get_text())
                    if len(cells) >= 4:
                        dept        = clean(cells[2].get_text())
                        closing_raw = clean(cells[3].get_text())
                    else:
                        dept        = division
                        closing_raw = clean(cells[2].get_text())

                    # "--" means no separate department — fall back to division
                    if dept in ("--", ""):
                        dept = division
                    dept = dept or "Vocational Training Council"

                    deadline = parse_date_text(closing_raw)

                    dedup_key = ref if ref else f"{title}|{dept}"
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    job_id = make_id("VTC", ref or title[:25])

                    # Fetch description from detail page
                    if _has_good_desc(job_id):
                        description = _existing_descriptions[job_id]
                    else:
                        try:
                            dsoup = get_soup(detail_url)
                            raw_text = ""
                            if dsoup:
                                content = (dsoup.find("div", id="innerContent")
                                           or dsoup.find("div", class_=re.compile(r'content', re.I))
                                           or dsoup.find("main"))
                                if content:
                                    raw_text = content.get_text("\n", strip=True)
                            if any(m in raw_text.lower() for m in BOT_MARKERS):
                                raw_text = ""
                            if raw_text and len(raw_text) > 80:
                                description = raw_text[:8000]   # summarised once in main()
                            else:
                                description = PLACEHOLDER_MARKER
                        except Exception as e:
                            print(f"  ⚠️  VTC detail fetch failed for '{title}': {e}")
                            description = PLACEHOLDER_MARKER

                    jobs.append({
                        "id":               job_id,
                        "title":            title,
                        "rank":             detect_rank(title),
                        "university":       "VTC",
                        "university_full":  "Vocational Training Council",
                        "department":       dept,
                        "deadline":         deadline,
                        "is_new":           "TRUE",
                        "reference":        ref,
                        "position_type":    position_type,
                        "salary":           "",
                        "start_date":       "",
                        "apply_url":        detail_url,
                        "description":      description,
                    })
                    print(f"    VTC [{position_type}]: {title} | {dept}")

    except Exception as e:
        print(f"  ⚠️  VTC scraper failed: {e}")

    print(f"  ✅ VTC: {len(jobs)} jobs found")
    return jobs


def scrape_cpce():
    """
    CPCE (HKCC / SPEED) — jas.cpce-polyu.edu.hk
    Six listing pages (id=5010–5015) covering Senior Management, Academic,
    Management/Senior Professional, Executive/Professional, General, Research.
    Listing: <table class="list-table"> with <tr class="list-row" data-id="...">
    Columns: Unit | Position | Initial screening date/Closing date | Ref. no.
    Detail: /detail?id=<data-id>  — static HTML, Duties → Qualifications sections.
    Both HKCC and SPEED share this portal (unit names distinguish them).
    """
    print("📋 Scraping CPCE (HKCC/SPEED)...")

    BASE = "https://jas.cpce-polyu.edu.hk"
    SECTIONS = [
        (5010, "Senior Management"),
        (5011, "Academic"),
        (5012, "Management/Senior Professional"),
        (5013, "Executive/Professional"),
        (5014, "General"),
        (5015, "Research"),
    ]
    jobs = []
    seen = set()

    for section_id, section_name in SECTIONS:
        try:
            soup = get_soup(f"{BASE}/list?id={section_id}&sort=sort_rel")
            if not soup:
                continue
            rows = soup.select("table.list-table tr.list-row")
            for row in rows:
                data_id = row.get("data-id", "")
                cells = row.find_all("td")
                if len(cells) < 4 or not data_id:
                    continue
                dept     = clean(cells[0].get_text())
                title    = clean(cells[1].get_text())
                # The column is "Initial screening date/Closing date": usually
                # the date review *starts* (the post stays open after it), so
                # it only becomes a deadline if the detail page says so.
                listed_date = parse_date_text(clean(cells[2].get_text()))
                ref      = clean(cells[3].get_text())
                if not title or len(title) < 5:
                    continue
                if data_id in seen:
                    continue
                seen.add(data_id)
                jobs.append({
                    "id":              make_id("CPCE", data_id),
                    "title":           title,
                    "rank":            detect_rank(title),
                    "university":      "CPCE",
                    "university_full": "HKCC / SPEED (CPCE)",
                    "department":      dept or "CPCE",
                    "deadline":        "",
                    "_listed_date":    listed_date,
                    "is_new":          "TRUE",
                    "reference":       ref,
                    "position_type":   detect_type(title),
                    "salary":          "",
                    "start_date":      "",
                    "apply_url":       f"{BASE}/detail?id={data_id}",
                    "description":     f"{title} — {dept}. Please visit the application link for full details.",
                })
        except Exception as e:
            print(f"  ⚠️  CPCE section {section_id} failed: {e}")

    # ── Detail pages: date wording for every job (static pages, one request
    #    each), plus the description for jobs without a cached summary
    if jobs:
        print(f"  ↳ Fetching {len(jobs)} detail pages...")
    found = 0
    for j in jobs:
        listed = j.pop("_listed_date", "")
        text = ""
        try:
            dsoup = get_soup(j["apply_url"])
            text = dsoup.get_text("\n", strip=True) if dsoup else ""
        except Exception:
            pass
        closing = re.search(r"closing date[^:\n]{0,20}[:\s]+([^\n]{6,40})", text, re.I)
        closing_date = date_in_text(closing.group(1)) if closing else ""
        commence = re.search(r"Consideration of applications will commence on (.+?) until", text, re.I | re.S)
        if closing_date:
            j["deadline"] = closing_date
        elif commence or listed:
            start = date_in_text(commence.group(1)) if commence else listed
            pretty = datetime.strptime(start, "%Y-%m-%d").strftime("%-d %b %Y") if ISO_DATE.match(start or "") else ""
            j["deadline_note"] = f"Applications considered from {pretty} until filled" if pretty else "Open until filled"
        if text and not _has_good_desc(j["id"]):
            # Extract from "Duties" to "Conditions of Service" or "Apply Now"
            start = next((text.find(m) for m in ["Duties\n", "Duties\r"] if text.find(m) > -1), -1)
            end   = next((text.find(m) for m in ["Apply Now", "Posting Date", "Conditions of Service"] if text.find(m) > -1), -1)
            block = (text[start:end] if end > start else text[start:]) if start > -1 else text
            lines = [l.strip() for l in block.splitlines() if len(l.strip()) > 30]
            if lines:
                j["description"] = "\n\n".join(lines[:60])[:8000]
                found += 1
    print(f"  ↳ Got new descriptions for {found} jobs")

    # Restore cached summaries
    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]

    print(f"  ✅ CPCE: {len(jobs)} jobs found")
    return jobs


def scrape_hkuspace():
    """
    HKU SPACE — jobs.hkuspace.hku.hk
    Two listing pages:
      - Full-time: /jobs/job.php  (table: Title | Closing Date | Ref | Apply)
      - Part-time: /jobs/list_pt.php  (tables grouped by college;
                   rows: Posting Date | Programme Type | Module/Title | Closing Date | Ref | Apply)
    Detail page: /jobs/job_dtls.php?lang=eng&jcode=<ref>
      Static HTML: Duties → Requirements → Terms of Appointment → Closing Date for Applications
    """
    print("📋 Scraping HKU SPACE...")

    BASE     = "https://jobs.hkuspace.hku.hk"
    DETAIL   = BASE + "/jobs/job_dtls.php?lang=eng&jcode={jcode}"
    jobs     = []
    seen     = set()

    # ── Full-time listing ────────────────────────────────────────────
    try:
        soup = get_soup(f"{BASE}/jobs/job.php?lang=eng")
        if soup:
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue
                    link = row.find("a", href=lambda h: h and "job_dtls" in h)
                    if not link:
                        continue
                    title = clean(cells[0].get_text())
                    if not title or len(title) < 5:
                        continue
                    # jcode may have &apply=1 appended — strip it
                    href  = link["href"]
                    jcode = href.split("jcode=")[-1].split("&")[0]
                    ref_text = clean(cells[2].get_text()).replace("RF:", "").strip()
                    deadline = parse_date_text(clean(cells[1].get_text()))
                    # Infer dept from "in the College/Unit/..." suffix
                    dept_m = re.search(r'\bin the (.+)$', title, re.I)
                    dept = dept_m.group(1).strip() if dept_m else "HKU SPACE"
                    dedup = jcode or title[:40]
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    jobs.append({
                        "id":              make_id("HKUSPACE", jcode or title[:30]),
                        "title":           title,
                        "rank":            detect_rank(title),
                        "university":      "HKUSPACE",
                        "university_full": "HKU SPACE",
                        "department":      dept,
                        "deadline":        deadline,
                        "is_new":          "TRUE",
                        "reference":       ref_text,
                        "position_type":   "Full-time",
                        "salary":          "",
                        "start_date":      "",
                        "apply_url":       DETAIL.format(jcode=jcode) if jcode else f"{BASE}/jobs/job.php",
                        "description":     f"{title} — {dept}. Please visit the application link for full details.",
                    })
    except Exception as e:
        print(f"  ⚠️  HKU SPACE full-time fetch failed: {e}")

    # ── Part-time listing ────────────────────────────────────────────
    try:
        soup = get_soup(f"{BASE}/jobs/list_pt.php?lang=eng")
        if soup:
            current_college = "HKU SPACE"
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    # Single-cell rows are college section headers
                    if len(cells) == 1:
                        current_college = clean(cells[0].get_text()) or current_college
                        continue
                    if len(cells) < 5:
                        continue
                    link = row.find("a", href=lambda h: h and "job_dtls" in h)
                    if not link:
                        continue
                    # Cells: Posting Date | Programme Type | Module/Title | Closing Date | Ref | Apply
                    prog_type = clean(cells[1].get_text())
                    title     = clean(cells[2].get_text())
                    if not title or len(title) < 3:
                        continue
                    deadline  = parse_date_text(clean(cells[3].get_text()))
                    ref_text  = clean(cells[4].get_text()).replace("RF:", "").strip()
                    href      = link["href"]
                    jcode     = href.split("jcode=")[-1].split("&")[0]
                    full_title = f"{title} ({prog_type})" if prog_type and prog_type.lower() not in title.lower() else title
                    dedup = jcode or full_title[:40]
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    jobs.append({
                        "id":              make_id("HKUSPACE", jcode or full_title[:30]),
                        "title":           full_title,
                        "rank":            detect_rank(full_title),
                        "university":      "HKUSPACE",
                        "university_full": "HKU SPACE",
                        "department":      current_college,
                        "deadline":        deadline,
                        "is_new":          "TRUE",
                        "reference":       ref_text,
                        "position_type":   "Part-time",
                        "salary":          "",
                        "start_date":      "",
                        "apply_url":       BASE + "/jobs/" + href if href.startswith("job_dtls") else href,
                        "description":     f"{full_title} — {current_college}. Please visit the application link for full details.",
                    })
    except Exception as e:
        print(f"  ⚠️  HKU SPACE part-time fetch failed: {e}")

    # ── Detail pages for descriptions ────────────────────────────────
    needs_desc = [j for j in jobs if not _has_good_desc(j["id"])]
    if needs_desc:
        print(f"  ↳ Fetching {len(needs_desc)} detail pages...")
        found = 0
        for j in needs_desc:
            try:
                dsoup = get_soup(j["apply_url"])
                if not dsoup:
                    continue
                text = dsoup.get_text("\n", strip=True)
                # Extract from "Duties:" to "Applications:" or "Closing Date"
                start = text.find("Duties:")
                end   = text.find("Applications:")
                if start == -1:
                    start = text.find("Requirements:")
                block = text[start:end] if start > -1 and end > start else (text[start:] if start > -1 else "")
                lines = [l.strip() for l in block.splitlines() if len(l.strip()) > 30]
                if lines:
                    j["description"] = "\n\n".join(lines[:60])[:8000]
                    found += 1
                # Closing date from detail page if not already set
                if not j["deadline"]:
                    m = re.search(r'Closing Date for Applications[:\s]+(.+?)(?:\n|$)', text)
                    if m:
                        j["deadline"] = parse_date_text(m.group(1).strip())
            except Exception:
                pass
        print(f"  ↳ Got descriptions for {found}/{len(needs_desc)} jobs")

    # Restore cached summaries
    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]

    print(f"  ✅ HKU SPACE: {len(jobs)} jobs found")
    return jobs


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def scrape_chuhai():
    """
    Hong Kong Chu Hai College — chuhai.edu.hk/en/page/jobs
    Four category pages; each loads its job list from a JSON API that requires
    JS-generated session cookies. Playwright intercepts the API responses.
    All jobs in a category are returned as one HTML blob (accordion widgets);
    BeautifulSoup extracts individual jobs from that blob.
    """
    print("📋 Scraping Chu Hai...")

    GROUPS = {
        "3feba8ec-0307-4709-8c72-bc7c316e63f3": "Research / Project",
        "cd303cce-dd3e-484d-ba93-a956d2d4c15d": "Administrative",
        "b9f07df8-bc36-430a-91ea-b8f196e36f18": "Academic",
        "e80af52a-59d4-40ae-ab0b-cbb879e41a02": "Management",
    }

    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)

            api_responses = {}

            def capture(response):
                if "api/special/careers" in response.url:
                    try:
                        api_responses[response.url] = response.json()
                    except Exception:
                        pass

            page.on("response", capture)

            for gid in GROUPS:
                page.goto(f"https://www.chuhai.edu.hk/en/page/jobs?id={gid}",
                          timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(1000)

            browser.close()

        for url, data in api_responses.items():
            if data.get("code") != 200:
                continue
            gid = url.split("groupId=")[-1]
            pos_type = GROUPS.get(gid, "")
            content_html = (data.get("data") or {}).get("content", {}).get("article_content", "")
            if not content_html:
                continue

            soup = BeautifulSoup(content_html, "html.parser")
            apply_url = f"https://www.chuhai.edu.hk/en/page/jobs?id={gid}"

            # Default dept to category name; overridden by <h3> headers for Research group
            current_dept = pos_type
            for el in soup.children:
                if not hasattr(el, "name") or not el.name:
                    continue
                # Department headers are top-level <h3> tags outside accordion widgets
                if el.name == "h3":
                    text = el.get_text(strip=True)
                    if text and not re.search(r'no job opening', text, re.I):
                        current_dept = text
                    continue
                if el.name != "div" or "accordion-wrapper" not in el.get("class", []):
                    continue

                # Title from accordion header h3
                title_el = el.select_one(".accordion-title h3, .accordion-header h3")
                title = clean(title_el.get_text()) if title_el else ""
                if not title or len(title) < 3:
                    continue

                key = f"{title}|{current_dept}"
                if key in seen:
                    continue
                seen.add(key)

                body = el.select_one(".accordion-body")
                desc_text = ""
                deadline = ""

                if body:
                    # Try table format first (Research jobs), fall back to paragraph text
                    rows = body.find_all("tr")
                    if rows:
                        parts = []
                        for row in rows:
                            cells = row.find_all("td")
                            if len(cells) == 2:
                                label = cells[0].get_text(strip=True)
                                val   = cells[1].get_text(separator=" ", strip=True)
                                if label and val:
                                    parts.append(f"{label} {val}")
                                elif val:
                                    parts.append(val)
                            elif len(cells) == 1:
                                val = cells[0].get_text(separator=" ", strip=True)
                                if val:
                                    parts.append(val)
                        desc_text = "\n".join(p for p in parts if len(p) > 10)[:8000]
                    else:
                        # Paragraph-based format (Academic / Management)
                        lines = [p.get_text(separator=" ", strip=True)
                                 for p in body.find_all("p") if p.get_text(strip=True)]
                        desc_text = "\n".join(ln for ln in lines if len(ln) > 20)[:8000]

                    # Closing date from "Closing Date:" table cell
                    for td in body.find_all("td"):
                        if re.search(r'closing date', td.get_text(), re.I):
                            sibling = td.find_next_sibling("td")
                            if sibling:
                                raw = sibling.get_text(strip=True)
                                if raw and not re.search(r'until.*filled|invitation|not to fill', raw, re.I):
                                    deadline = parse_date_text(raw)
                            break

                # Reference number
                ref = ""
                ref_m = re.search(r'(?:Ref(?:erence)?\.?\s*(?:No\.?)?|ref\s*no\.?)[:\s]+([A-Za-z0-9/_\-\.]+)',
                                   desc_text, re.I)
                if ref_m:
                    ref = ref_m.group(1).strip()

                jobs.append({
                    "id":              make_id("HKCHC", ref or f"{title[:40]}_{current_dept[:20]}"),
                    "title":           title,
                    "rank":            detect_rank(title),
                    "university":      "HKCHC",
                    "university_full": "Hong Kong Chu Hai College",
                    "department":      current_dept,
                    "deadline":        deadline,
                    "is_new":          "TRUE" if is_active(deadline) else "FALSE",
                    "reference":       ref,
                    "position_type":   detect_type(title),
                    "salary":          "",
                    "start_date":      "",
                    "apply_url":       text_fragment_url(apply_url, title),
                    "description":     desc_text,
                })

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")
        import traceback; traceback.print_exc()

    print(f"  ✅ Chu Hai: {len(jobs)} jobs found")
    return jobs


def scrape_thei():
    """
    THEi — thei.edu.hk/career-opportunities/ (WordPress + Elementor loop grids)
    Two grids (Teaching & Academic, Administrative & General), 8 cards a page.
    Each grid pages server-side via ?e-page-<grid id>=N; the next page's URL is
    in the grid's .e-load-more-anchor[data-next-page] (the site fetches it on
    scroll). Following those URLs needs no scrolling or button clicks — the
    click-to-load-more button the old code relied on was removed in Aug 2026.
    """
    print("📋 Scraping THEi...")
    LISTING_URL = "https://thei.edu.hk/career-opportunities/"
    MAX_LISTING_PAGES = 20

    jobs = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_extra_http_headers(HEADERS)

            cards_data = []
            seen_urls = set()
            queue, visited = [LISTING_URL], set()
            while queue and len(visited) < MAX_LISTING_PAGES:
                listing_url = queue.pop(0)
                if listing_url in visited:
                    continue
                visited.add(listing_url)
                page.goto(listing_url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_selector(".e-loop-item", timeout=30000)
                except Exception:
                    print(f"  ⚠️  THEi: no job cards on {listing_url}")
                    continue
                soup = BeautifulSoup(page.content(), "html.parser")
                for anchor in soup.select(".e-load-more-anchor[data-next-page]"):
                    try:
                        current, last = int(anchor.get("data-page") or 1), int(anchor.get("data-max-page") or 1)
                    except ValueError:
                        continue
                    next_url = anchor["data-next-page"]
                    if current < last and next_url not in visited:
                        queue.append(next_url)
                cards_data.extend(_parse_thei_cards(soup, seen_urls))
            print(f"  ↳ {len(cards_data)} job cards from {len(visited)} listing page(s)")

            # Fetch detail pages for ref + description
            used_ids = set()
            for card in cards_data:
                try:
                    page.goto(card["url"], wait_until="domcontentloaded", timeout=45000)
                    try:
                        page.wait_for_selector(".elementor-widget-text-editor", timeout=15000)
                    except Exception:
                        pass
                    detail_soup = BeautifulSoup(page.content(), "html.parser")

                    text_parts = []
                    for widget in detail_soup.find_all(
                        "div", class_=lambda c: c and "elementor-widget-text-editor" in c
                    ):
                        t = widget.get_text(separator="\n", strip=True)
                        if len(t) > 80:
                            text_parts.append(t)
                    full_text = "\n\n".join(text_parts)

                    # Extract ref no. The page often splits it across elements
                    # ("FO ⏎ /AS ⏎ /03/26"), so read up to the next heading and
                    # drop the line breaks; otherwise fall back to one line.
                    ref = ""
                    ref_m = re.search(
                        r"Ref(?:erence)?\.?\s*No\.?\s*[:：]\s*(.{1,80}?)\s*"
                        r"(?=Major Duties|Employment Period|Duties|Responsibilities|$)",
                        full_text, re.I | re.S,
                    ) or re.search(
                        r"Ref(?:erence)?\.?\s*No\.?\s*[:\s]+([A-Za-z0-9/_\-\.\(\)]+)",
                        full_text, re.I,
                    )
                    if ref_m:
                        ref = re.sub(r"\s+", "", ref_m.group(1)).rstrip(".")

                    job_id = make_id("THEI", ref or card["title"])
                    if job_id in used_ids:
                        # Never let two postings share an id (one would be dropped)
                        job_id = make_id("THEI", card["url"].rstrip("/").rsplit("/", 1)[-1])
                    used_ids.add(job_id)

                    jobs.append({
                        "id":              job_id,
                        "title":           card["title"],
                        "rank":            detect_rank(card["title"]),
                        "university":      "THEI",
                        "university_full": "Technological and Higher Education Institute of Hong Kong",
                        "department":      card["dept"],
                        "deadline":        card["deadline"],
                        "is_new":          "TRUE" if is_active(card["deadline"]) else "FALSE",
                        "date_added":      TODAY.strftime("%Y-%m-%d"),
                        "reference":       ref,
                        "position_type":   detect_type(card["title"]),
                        "salary":          "",
                        "start_date":      "",
                        "apply_url":       card["url"],
                        "description":     full_text[:8000],
                    })
                except Exception as e:
                    print(f"  ⚠️  Error fetching {card['url']}: {e}")

            browser.close()

    except Exception as e:
        print(f"  ⚠️  THEi scraper failed: {e}")
        import traceback; traceback.print_exc()

    print(f"  ✅ THEi: {len(jobs)} jobs found")
    return jobs


def _parse_thei_cards(soup, seen_urls):
    """Job cards (title, detail URL, department, closing date) on one THEi listing page."""
    cards_data = []
    for card in soup.find_all("div", class_=lambda c: c and "e-loop-item" in c):
        # Find job URL: first <a> linking to a single-slug thei.edu.hk page
        href = ""
        for a in card.find_all("a", href=True):
            h = a["href"]
            path = h.replace("https://thei.edu.hk/", "").rstrip("/")
            if path and "/" not in path:
                href = h
                break
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        # Title: first <a> with non-empty text, or fall back to any text in card heading
        title = ""
        for a in card.find_all("a", href=True):
            t = clean(a.get_text())
            if t:
                title = t
                break
        if not title:
            # Some cards wrap title in a span inside job-career div
            jc = card.find("div", class_="job-career")
            if jc:
                title = clean(jc.get_text())
        if not title:
            continue

        # Card text parts: title | department | closing_date_text | More Details
        parts = [p.strip() for p in card.get_text(separator="|", strip=True).split("|") if p.strip()]
        dept = parts[1] if len(parts) > 1 else ""
        date_text = parts[2] if len(parts) > 2 else ""

        # Parse closing date — skip "Review of applications..." text
        deadline = ""
        if re.search(r"\d{1,2}\s+\w+\s+\d{4}", date_text):
            m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", date_text)
            if m:
                deadline = parse_date_text(m.group(1))

        cards_data.append({
            "title": title,
            "url": href,
            "dept": dept,
            "deadline": deadline,
        })
    return cards_data


SCRAPERS = {
    "polyu":  scrape_polyu,
    "eduhk":  scrape_eduhk,
    "lingnan": scrape_lingnan,
    "hku":    scrape_hku,
    "hkust":  scrape_hkust,
    "cityu":  scrape_cityu,
    "hkbu":   scrape_hkbu,
    "cuhk":   scrape_cuhk,
    "hkmu":   scrape_hkmu,
    "hsu":    scrape_hsu,
    "sfu":    scrape_sfu,
    "hksyu":    scrape_hksyu,
    "vtc":      scrape_vtc,
    "hkuspace": scrape_hkuspace,
    "cpce":     scrape_cpce,
    "chuhai":   scrape_chuhai,
    "thei":     scrape_thei,
}


# Scraper name → university code(s) used in the CSV. Used to fall back to the
# previous run's rows when a scraper crashes or under-delivers.
SCRAPER_UNI_CODES = {
    "polyu": ["PolyU"], "eduhk": ["EdUHK"], "lingnan": ["LU"],
    "hku": ["HKU"], "hkust": ["HKUST"], "cityu": ["CityU"],
    "hkbu": ["HKBU"], "cuhk": ["CUHK"], "hkmu": ["HKMU"],
    "hsu": ["HSU"], "sfu": ["SFU"], "hksyu": ["HKSYU"],
    "vtc": ["VTC"], "hkuspace": ["HKUSPACE"], "cpce": ["CPCE"],
    "chuhai": ["HKCHC"], "thei": ["THEI"],
}

# ── Scrape health: every full run appends per-scraper results to this file;
#    scraper/health.py reads it after publishing and fails the workflow if any
#    institution crashed, came back empty, or came back well short of usual.
HEALTH_FILE          = Path(__file__).parent / "scrape_health.json"
HEALTH_KEEP_RUNS     = 30    # runs kept in the file
PARTIAL_RATIO        = 0.7   # fewer than this share of the usual count = partial failure
PARTIAL_MIN_BASELINE = 10    # small portals swing naturally; only an empty result counts there


def load_health_runs():
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8")).get("runs", [])
    except (OSError, ValueError):
        return []


def expected_count(runs, name, previous_count):
    """A scraper's usual job count: the median of its last 7 recorded runs plus
    the previous CSV's count, so it works from the first run and settles within
    a few days if a portal genuinely shrinks."""
    samples = [r["results"][name]["scraped"] for r in runs[-7:] if name in r.get("results", {})]
    samples.append(previous_count)
    return statistics.median(samples)


# ── Job registry: the first and last day each job id was actually scraped.
#    Unlike the previous CSV, it remembers jobs through portal outages, so a
#    job that drops out and comes back keeps its original date_added and isn't
#    re-flagged NEW (or re-alerted to subscribers).
REGISTRY_FILE        = Path(__file__).parent / "job_registry.json"
REAPPEAR_WINDOW_DAYS = 60    # absent longer than this → treated as a new posting
REGISTRY_KEEP_DAYS   = 180   # forget ids not scraped for this long
FALLBACK_MAX_DAYS    = 14    # stop showing a failing portal's old jobs after this


def load_registry():
    """{job id: [first_seen, last_seen]} as ISO dates (HKT)."""
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8")).get("jobs", {})
    except (OSError, ValueError):
        return {}


def save_registry(registry):
    cutoff = (TODAY - timedelta(days=REGISTRY_KEEP_DAYS)).isoformat()
    lines = [f"{json.dumps(k, ensure_ascii=False)}:{json.dumps(v)}"
             for k, v in sorted(registry.items()) if v[1] >= cutoff]
    # One job per line keeps daily diffs small and readable
    REGISTRY_FILE.write_text('{"version":1,"jobs":{\n' + ",\n".join(lines) + "\n}}\n", encoding="utf-8")


def days_since(date_str):
    try:
        return (TODAY - date.fromisoformat(date_str)).days
    except (TypeError, ValueError):
        return 10 ** 6


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
    parser.add_argument("--force-resummary", action="store_true", help="Re-run AI summarisation for all jobs, ignoring cached summaries")
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
    existing = {}      # id → full row dict from previous CSV
    existing_rows = {} # university code → list of full rows (for fallback on scraper failure)
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    jid = row.get("id", "")
                    if jid:
                        existing[jid] = dict(row)
                        uni = row.get("university", "")
                        if uni:
                            existing_rows.setdefault(uni, []).append(dict(row))
            print(f"↳ Previous CSV: {len(existing)} jobs loaded")
        except Exception as e:
            print(f"  ⚠️  Could not read previous CSV: {e}")

    # Expose existing descriptions so scrapers can skip re-fetching known jobs
    global _existing_descriptions, _previous_rows
    _existing_descriptions = {jid: row.get("description", "") for jid, row in existing.items()}
    _previous_rows = existing

    all_jobs = []
    health_runs, health_results = None, {}
    registry = load_registry()
    scraped_ids = set()   # ids actually returned by a scraper today (not kept from before)

    if args.uni:
        # Scrape single university
        uni = args.uni.lower()
        if uni not in SCRAPERS:
            print(f"Unknown university: {uni}. Options: {', '.join(SCRAPERS.keys())}")
            sys.exit(1)
        all_jobs = SCRAPERS[uni]()
        scraped_ids = {j["id"] for j in all_jobs}
        # Keep every other institution's rows so jobs.csv isn't overwritten
        # with a single university
        own_codes = set(SCRAPER_UNI_CODES.get(uni, []))
        all_jobs += [r for code, rows in existing_rows.items() if code not in own_codes for r in rows]
    else:
        # Scrape all
        health_runs = load_health_runs()
        for name, scraper in SCRAPERS.items():
            previous = [r for code in SCRAPER_UNI_CODES.get(name, []) for r in existing_rows.get(code, [])]
            expected = expected_count(health_runs, name, len(previous))
            error = ""
            try:
                jobs = scraper() or []
            except Exception as e:
                print(f"  ❌ {name} crashed: {e}")
                jobs, error = [], f"{type(e).__name__}: {e}"

            if error:
                status = "crashed"
            elif not jobs:
                status = "empty"
            elif expected >= PARTIAL_MIN_BASELINE and len(jobs) < PARTIAL_RATIO * expected:
                status = "partial"
            else:
                status = "ok"

            # On any failure, keep the previous run's rows for this institution
            # that weren't re-scraped, so they don't vanish today and come back
            # tomorrow as "new" (re-alerted, re-summarised, new date_added).
            # Rows not actually scraped for FALLBACK_MAX_DAYS are dropped, so a
            # portal that stays broken doesn't show stale jobs indefinitely.
            kept = []
            if status != "ok":
                these_ids = {j["id"] for j in jobs}
                candidates = [r for r in previous if r["id"] not in these_ids]
                kept = [r for r in candidates
                        if days_since(registry.get(r["id"], [today_str, today_str])[1]) <= FALLBACK_MAX_DAYS]
                stale = len(candidates) - len(kept)
                print(f"  ⚠️  {name}: {status} — {len(jobs)} scraped vs ~{expected:.0f} usual; "
                      f"keeping {len(kept)} jobs from the previous run"
                      + (f" (dropped {stale} not seen for {FALLBACK_MAX_DAYS}+ days)" if stale else ""))
            all_jobs.extend(jobs)
            all_jobs.extend(kept)
            scraped_ids.update(j["id"] for j in jobs)

            health_results[name] = {
                "university": ",".join(SCRAPER_UNI_CODES.get(name, [])),
                "status": status,
                "scraped": len(jobs),
                "expected": round(expected),
                "kept_from_previous": len(kept),
            }
            if error:
                health_results[name]["error"] = error[:300]
            time.sleep(1)  # polite delay between universities

    all_jobs = deduplicate(all_jobs)
    for j in all_jobs:
        normalise_deadline(j)
    # Keep: active jobs, no-deadline jobs, and jobs closed within the last 14 days
    all_jobs = [j for j in all_jobs if is_within_retention(j.get("deadline", ""))]

    # Re-rank using both title and description now that descriptions are available
    for j in all_jobs:
        j["rank"] = detect_rank(j["title"], j.get("description", ""))

    # Override is_new and set date_added based on previous runs.
    # is_new = TRUE only for job IDs never seen before (or not seen for
    # REAPPEAR_WINDOW_DAYS) — a job that dropped out briefly isn't new.
    for j in all_jobs:
        # Ensure date_posted field exists (scrapers that don't set it leave it blank)
        if "date_posted" not in j:
            j["date_posted"] = ""
        seen = registry.get(j["id"])
        if seen and days_since(seen[1]) > REAPPEAR_WINDOW_DAYS:
            seen = None   # back after a long gap: a new posting, with a fresh history
        if j["id"] in existing:
            j["is_new"] = "FALSE"
            j["date_added"] = existing[j["id"]]["date_added"]
            # Preserve previously captured date_posted if scraper didn't return one this run
            if not j["date_posted"]:
                j["date_posted"] = existing[j["id"]].get("date_posted", "")
        elif seen and days_since(seen[1]) <= REAPPEAR_WINDOW_DAYS:
            # Back after a portal hiccup or partial scrape: keep its original date
            j["is_new"] = "FALSE"
            j["date_added"] = seen[0]
        else:
            # Don't mark as new if the deadline has already passed
            j["is_new"] = "TRUE" if is_active(j.get("deadline", "")) else "FALSE"
            j["date_added"] = today_str
        # Flaps before the registry existed reset some date_added values
        if seen and seen[0] < (j["date_added"] or today_str):
            j["date_added"] = seen[0]
        # Record today's sighting (only for jobs a scraper actually returned)
        if j["id"] in scraped_ids:
            registry[j["id"]] = [j["date_added"] or today_str, today_str]

    # ── AI summarisation via Claude Haiku
    # Reuse existing summaries for known jobs; only call the API for jobs
    # that have real scraped content but no summary yet.
    # _has_good_desc() is the single source of truth: requires **+• markers,
    # no placeholder text, and length > 80. Any job that doesn't meet this
    # standard is treated as needing a fresh fetch + summarisation.
    POOR_PATTERNS = (
        PLACEHOLDER_MARKER.lower(),           # "please visit the application link"
        "see application link",
        "see eduhk website",
        "please visit the application",       # catches redirect stubs specifically
        r"please visit.*for full details",    # "please visit ... for full details"
    )
    def _is_poor_content(desc):
        if not desc or len(desc.strip()) <= 300:
            return True
        d = desc.strip().lower()
        return any(re.search(p, d) for p in POOR_PATTERNS)

    to_summarise = []
    for j in all_jobs:
        prev_desc = existing.get(j["id"], {}).get("description", "")
        if _has_good_desc(j["id"]) and not args.force_resummary:
            j["description"] = prev_desc  # reuse existing AI summary
        elif not _is_poor_content(j.get("description", "")):
            to_summarise.append(j)

    summarise_jobs(to_summarise)

    # Summary closing date ↔ deadline column (fills blanks, fixes stale dates)
    for j in all_jobs:
        reconcile_summary_deadline(j)
        # Raw (unsummarised) text is only kept in full for the next attempt at
        # summarising; cap it so a Claude outage can't bloat jobs.csv
        if "**" not in (j.get("description") or "") and len(j.get("description") or "") > 3000:
            j["description"] = j["description"][:3000]
    all_jobs = [j for j in all_jobs if is_within_retention(j.get("deadline", ""))]

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
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"✅ Saved to {OUTPUT_FILE}")

    # Record this run for scraper/health.py (full runs only; written after the
    # CSV so a recorded run always means data was published)
    if health_runs is not None:
        save_registry(registry)
        health_runs.append({
            "date": today_str,
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_jobs": len(all_jobs),
            "new_jobs": new_count,
            "results": health_results,
        })
        HEALTH_FILE.write_text(
            json.dumps({"runs": health_runs[-HEALTH_KEEP_RUNS:]}, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        problems = {n: r["status"] for n, r in health_results.items() if r["status"] != "ok"}
        print(f"🩺 Scrape health: {'all institutions OK' if not problems else problems}")

    print(f"🌐 Your website will update automatically within minutes.\n")


if __name__ == "__main__":
    main()
