"""
Shared helpers for the scrapers: text cleanup, ids, rank and job-type detection,
dates and deadlines, page fetching, and the previous run's data.
"""

import hashlib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup


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
    # ASCII only (\w would also accept Chinese titles), so ids and page URLs stay plain
    if len(key) <= 20 and re.match(r'^[A-Za-z0-9_\-]+$', key):
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
