"""
generate_job_pages.py
Reads jobs.csv and writes:
  - jobs/<slug>-<id>/index.html  — standalone SEO-friendly page per open job
      Contains:
        * Per-job <title>, <meta description>, canonical URL
        * Open Graph + Twitter Card tags (with og:image)
        * JobPosting + BreadcrumbList JSON-LD (Google for Jobs)
        * Full visible job description (so Googlebot sees real content)
        * Apply link (tracked as a GA4 apply_click), related jobs at the same
          institution, and a "Browse more" link back to the main site
      Important: these pages DO NOT auto-redirect via JS. Googlebot would
      treat that as a soft 404. Users arriving via Google see a real page.
  - Closed jobs keep a "no longer open" page (noindex) for 60 days, so shared
    links, bookmarks and alert emails don't hit a 404. If a job's title (and
    so its URL) changes, the old URL redirects to the new page for 60 days.
  - Only pages whose content changed are rewritten. Each page's last-changed
    date is kept in scraper/pages_manifest.json for the sitemap's <lastmod>.
  - sitemap.xml      — homepage + all open job URLs
  - jobs-lite.csv    — jobs.csv without descriptions, for the homepage's
                       first paint (descriptions load right after)
  - index.html       — the newest jobs as plain links between the
                       LATEST-JOBS markers, so crawlers see real content
                       without running JS or fetching jobs.csv

Run from repo root:
  python scraper/generate_job_pages.py
"""

import csv
import hashlib
import html
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL   = "https://www.hkacadjobs.org"
OG_IMAGE   = f"{BASE_URL}/og-image.png"
REPO_ROOT  = Path(__file__).parent.parent
CSV_PATH   = REPO_ROOT / "jobs.csv"
LITE_CSV   = REPO_ROOT / "jobs-lite.csv"
INDEX_HTML = REPO_ROOT / "index.html"
JOBS_DIR   = REPO_ROOT / "jobs"
SITEMAP    = REPO_ROOT / "sitemap.xml"
MANIFEST   = Path(__file__).parent / "pages_manifest.json"
HKT        = timezone(timedelta(hours=8))
TODAY      = datetime.now(HKT).date()   # same calendar as the scraper's date_added

CLOSED_KEEP_DAYS = 60   # closed / moved pages stay up this long, then 404
LATEST_COUNT     = 50   # jobs pre-rendered into index.html
RELATED_COUNT    = 5    # related jobs listed on each page

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LATEST_BLOCK = re.compile(r"(<!-- LATEST-JOBS:START[^>]*-->)(.*?)(<!-- LATEST-JOBS:END -->)", re.S)

# Employment type mapping for schema.org
EMPLOYMENT_TYPE_MAP = {
    "full-time":  "FULL_TIME",
    "part-time":  "PART_TIME",
    "contract":   "CONTRACTOR",
    "temporary":  "TEMPORARY",
}

# hiringOrganization.sameAs: each institution's own site
INSTITUTION_SITES = {
    "CPCE":     "https://www.cpce-polyu.edu.hk",
    "CUHK":     "https://www.cuhk.edu.hk",
    "CityU":    "https://www.cityu.edu.hk",
    "EdUHK":    "https://www.eduhk.hk",
    "HKBU":     "https://www.hkbu.edu.hk",
    "HKCHC":    "https://www.chuhai.edu.hk",
    "HKMU":     "https://www.hkmu.edu.hk",
    "HKSYU":    "https://www.hksyu.edu",
    "HKU":      "https://www.hku.hk",
    "HKUSPACE": "https://hkuspace.hku.hk",
    "HKUST":    "https://hkust.edu.hk",
    "HSU":      "https://www.hsu.edu.hk",
    "LU":       "https://www.ln.edu.hk",
    "PolyU":    "https://www.polyu.edu.hk",
    "SFU":      "https://www.sfu.edu.hk",
    "THEI":     "https://www.thei.edu.hk",
    "VTC":      "https://www.vtc.edu.hk",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
_slug_re = re.compile(r"[^a-z0-9]+")

def slugify(text: str) -> str:
    ascii_text = text.encode("ascii", "ignore").decode()
    result = _slug_re.sub("-", ascii_text.lower()).strip("-")[:60]
    return result or "position"

def job_dir_name(row: dict) -> str:
    """Folder (and URL path) of a job's page: /jobs/<slug>-<id>/"""
    return f"{slugify(row['title'])}-{row['id'].lower()}"


def iso(value: str) -> str:
    """The value if it is a YYYY-MM-DD date, else ''."""
    value = (value or "").strip()
    return value if ISO_DATE.match(value) else ""

def format_date_display(iso_date: str) -> str:
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%-d %b %Y")
    except Exception:
        return iso_date

def deadline_display(row: dict) -> str:
    """Deadline as shown to people: a date, or wording like 'Open until filled'."""
    dl = iso(row.get("deadline", ""))
    if dl:
        return format_date_display(dl)
    # Older CSVs kept wording in the deadline column itself
    return (row.get("deadline_note") or row.get("deadline") or "").strip()

def is_active(row: dict) -> bool:
    dl = iso(row.get("deadline", ""))
    return not (dl and dl < TODAY.isoformat())

def safe_url(url: str) -> str:
    """Only http(s) links are ever published."""
    url = (url or "").strip()
    return url if re.match(r"^https?://", url, re.I) else ""

def days_since(iso_date: str) -> int:
    try:
        return (TODAY - date.fromisoformat(iso_date)).days
    except (TypeError, ValueError):
        return 0

def employment_type_schema(position_type: str) -> str:
    pt = (position_type or "").lower()
    for k, v in EMPLOYMENT_TYPE_MAP.items():
        if k in pt:
            return v
    return "FULL_TIME"


_AMOUNT = r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?"
_SALARY_RE = re.compile(
    r"(?:HK\$|HKD|\$)\s*" + _AMOUNT +
    r"(?:\s*(?:-|–|—|to)\s*(?:HK\$|HKD|\$)?\s*" + _AMOUNT + r")?",
    re.I,
)
_SALARY_UNITS = {
    "HOUR":  re.compile(r"\bper\s+hour\b|\bhourly\b|/\s*(?:hour|hr)\b", re.I),
    "DAY":   re.compile(r"\bper\s+day\b|\bdaily\b|/\s*day\b", re.I),
    "MONTH": re.compile(r"\bper\s+(?:month|mensem)\b|\bmonthly\b|/\s*(?:month|mth)\b|\bp\.m\.", re.I),
    "YEAR":  re.compile(r"\bper\s+(?:annum|year)\b|\bannual(?:ly)?\b|/\s*(?:year|yr|annum)\b|\bp\.a\.", re.I),
}

def parse_salary(text: str):
    """schema.org MonetaryAmount for a single clear HKD amount or range with a
    pay period, e.g. 'HK$28,380 – HK$36,530 per month'. Anything vaguer
    ('competitive', grade points, several ranges) returns None."""
    matches = list(_SALARY_RE.finditer(text or ""))
    units = [u for u, rx in _SALARY_UNITS.items() if rx.search(text or "")]
    if len(matches) != 1 or len(units) != 1:
        return None
    m = matches[0]

    def amount(num, k):
        if not num:
            return None
        value = float(num.replace(",", "")) * (1000 if k else 1)
        return int(value) if value.is_integer() else value

    low, high = amount(m.group(1), m.group(2)), amount(m.group(3), m.group(4))
    if not low:
        return None
    value = {"@type": "QuantitativeValue", "unitText": units[0]}
    if high and high != low:
        value["minValue"], value["maxValue"] = min(low, high), max(low, high)
    else:
        value["value"] = low
    return {"@type": "MonetaryAmount", "currency": "HKD", "value": value}


_CONTENT_FIELDS = ("title", "university_full", "department", "rank", "position_type", "reference",
                   "date_posted", "start_date", "salary", "deadline", "deadline_note",
                   "apply_url", "description")

def content_hash(row: dict) -> str:
    """Changes only when the job itself changes (not its related-jobs list),
    which is what the sitemap's <lastmod> should track."""
    text = "\x1f".join(row.get(k) or "" for k in _CONTENT_FIELDS)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def _id_hash(job_id: str) -> int:
    return int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)

def related_jobs(job_id: str, university: str, department: str, by_uni: dict) -> list:
    """Other open jobs at the same institution, same department first.
    Picked by hash distance rather than recency, so a page's list only
    changes when one of its own neighbours opens or closes."""
    h = _id_hash(job_id)

    def key(r):
        d = abs(_id_hash(r["id"]) - h)
        return (0 if department and r["department"] == department else 1, min(d, 2**32 - d))

    others = [r for r in by_uni.get(university, []) if r["id"] != job_id]
    return sorted(others, key=key)[:RELATED_COUNT]


def script_json(data) -> str:
    """JSON safe to embed in a <script> element."""
    return json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")


def render_description_html(raw: str) -> str:
    """Render the (markdown-ish) description into semantic HTML.
    Matches the rendering used by the SPA detail panel so the static page
    looks familiar to users coming from Google search.
    """
    if not raw:
        return "<p>Please visit the application link for full details.</p>"

    bot_markers = [
        "security check", "not a bot", "verify that you are",
        "cloudflare", "complete the security",
    ]
    if any(m in raw.lower() for m in bot_markers):
        return "<p>Please visit the application link for full details.</p>"

    # Structured format: **Section**\n• bullet\n• bullet
    if "**" in raw and "•" in raw:
        blocks_html = []
        for block in raw.split("\n\n"):
            lines = block.split("\n")
            header = lines[0].replace("**", "").strip()
            bullets = [l for l in lines[1:] if l.strip().startswith("•")]
            if not bullets:
                blocks_html.append(f"<p>{html.escape(' '.join(lines))}</p>")
                continue
            items = "".join(
                f"<li>{html.escape(b.lstrip('• ').strip())}</li>"
                for b in bullets
            )
            blocks_html.append(
                f'<section class="desc-section">'
                f'<h2 class="desc-section-title">{html.escape(header)}</h2>'
                f'<ul>{items}</ul>'
                f'</section>'
            )
        return "".join(blocks_html)

    # Legacy plain-prose fallback
    paragraphs = raw.split("\n\n")
    return "".join(
        f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>"
        for p in paragraphs if p.strip()
    )


# ── Page shell ─────────────────────────────────────────────────────────────────
PAGE_CSS = """
    :root {
      --ink: #0f1117;
      --paper: #f5f2eb;
      --cream: #ece8df;
      --accent: #b5451b;
      --muted: #7a7568;
      --border: #d8d3c8;
      --white: #ffffff;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }
    a { color: var(--accent); }

    nav.site-nav {
      background: var(--ink);
      padding: 0 24px;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    nav.site-nav .logo {
      font-family: 'Playfair Display', serif;
      color: var(--paper);
      font-size: 1.25rem;
      text-decoration: none;
      letter-spacing: -0.02em;
    }
    nav.site-nav .logo span { color: var(--accent); }
    nav.site-nav .back-link {
      color: var(--paper);
      font-size: 0.85rem;
      text-decoration: none;
      opacity: 0.8;
    }
    nav.site-nav .back-link:hover { opacity: 1; }

    main {
      max-width: 760px;
      margin: 0 auto;
      padding: 48px 24px 80px;
    }
    .breadcrumb {
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 18px;
    }
    .breadcrumb a { color: var(--muted); text-decoration: none; }
    .breadcrumb a:hover { color: var(--accent); }
    h1.job-title {
      font-family: 'Playfair Display', serif;
      font-size: 2rem;
      line-height: 1.25;
      margin-bottom: 10px;
    }
    p.job-uni {
      font-size: 1rem;
      color: var(--accent);
      font-weight: 600;
      margin-bottom: 28px;
    }
    dl.info-grid {
      background: var(--white);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 22px;
      margin-bottom: 32px;
    }
    .info-row {
      display: flex;
      gap: 16px;
      padding: 8px 0;
      border-bottom: 1px solid var(--cream);
      font-size: 0.9rem;
    }
    .info-row:last-child { border-bottom: none; }
    .info-row dt {
      flex: 0 0 150px;
      color: var(--muted);
      font-weight: 500;
    }
    .info-row dd { flex: 1; color: var(--ink); }

    .desc-section { margin-bottom: 28px; }
    h2.desc-section-title {
      font-family: 'Playfair Display', serif;
      font-size: 1.2rem;
      margin-bottom: 10px;
      color: var(--ink);
    }
    .desc-section ul {
      list-style: none;
      padding: 0;
    }
    .desc-section li {
      position: relative;
      padding-left: 20px;
      margin-bottom: 8px;
      font-size: 0.95rem;
    }
    .desc-section li::before {
      content: "•";
      position: absolute;
      left: 4px;
      color: var(--accent);
      font-weight: bold;
    }

    .closed-banner {
      background: var(--white);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      padding: 14px 18px;
      margin-bottom: 28px;
      font-size: 0.93rem;
    }

    .actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 36px;
      padding-top: 24px;
      border-top: 1px solid var(--border);
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 12px 22px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.92rem;
      text-decoration: none;
      transition: background 0.15s;
    }
    .btn-primary {
      background: var(--accent);
      color: var(--white);
    }
    .btn-primary:hover { background: #9b3a14; }
    .btn-secondary {
      background: var(--cream);
      color: var(--ink);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover { background: var(--white); }

    .related { margin-top: 44px; }
    .related-list { list-style: none; padding: 0; }
    .related-list li {
      padding: 10px 0;
      border-bottom: 1px solid var(--cream);
      font-size: 0.93rem;
    }
    .related-list li:last-child { border-bottom: none; }
    .related-list a { font-weight: 600; text-decoration: none; }
    .related-list a:hover { text-decoration: underline; }
    .related-list span { display: block; color: var(--muted); font-size: 0.82rem; }

    footer {
      max-width: 760px;
      margin: 0 auto;
      padding: 24px;
      font-size: 0.8rem;
      color: var(--muted);
      border-top: 1px solid var(--border);
      text-align: center;
    }
    footer a { color: var(--muted); }

    @media (max-width: 600px) {
      main { padding: 32px 18px 60px; }
      h1.job-title { font-size: 1.55rem; }
      .info-row { flex-direction: column; gap: 2px; padding: 6px 0; }
      .info-row dt { flex-basis: auto; font-size: 0.78rem; }
    }
"""


def page_html(*, meta_title: str, meta_desc: str, canonical: str, robots: str,
              structured_data: list, main_html: str, tail_script: str = "") -> str:
    ld = "".join(
        f'  <script type="application/ld+json">\n{script_json(d)}\n  </script>\n'
        for d in structured_data
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(meta_title)}</title>
  <meta name="description" content="{html.escape(meta_desc)}">
  <link rel="canonical" href="{canonical}">
  <meta name="robots" content="{robots}">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">

  <!-- Open Graph -->
  <meta property="og:site_name" content="HKAcadJobs">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{html.escape(meta_title)}">
  <meta property="og:description" content="{html.escape(meta_desc)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{OG_IMAGE}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(meta_title)}">
  <meta name="twitter:description" content="{html.escape(meta_desc)}">
  <meta name="twitter:image" content="{OG_IMAGE}">

{ld}
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">

  <!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-GSSYS240VQ"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-GSSYS240VQ');
  </script>

  <style>{PAGE_CSS}  </style>
</head>
<body>
  <nav class="site-nav">
    <a href="{BASE_URL}/" class="logo">HK<span>AcadJobs</span></a>
    <a href="{BASE_URL}/" class="back-link">← All positions</a>
  </nav>

  <main>
{main_html}
  </main>

  <footer>
    <p>
      <a href="{BASE_URL}/">HKAcadJobs</a> aggregates academic openings from 17 Hong Kong institutions.
      Listings are updated daily.
    </p>
  </footer>
{tail_script}</body>
</html>
"""


def uni_filter_url(university: str) -> str:
    return f"{BASE_URL}/?uni={university}"

def breadcrumb_html(university: str, uni_full: str) -> str:
    return (
        f'    <nav class="breadcrumb" aria-label="Breadcrumb">\n'
        f'      <a href="{BASE_URL}/">HKAcadJobs</a> &rsaquo; '
        f'<a href="{html.escape(uni_filter_url(university))}">{html.escape(uni_full)}</a>\n'
        f'    </nav>'
    )

def breadcrumb_schema(university: str, uni_full: str, title: str, canonical: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "HKAcadJobs", "item": f"{BASE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": uni_full, "item": uni_filter_url(university)},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    }

def related_html(related: list, heading: str) -> str:
    if not related:
        return ""
    items = []
    for r in related:
        meta = " · ".join(x for x in (r["department"], deadline_display(r) and f"Deadline: {deadline_display(r)}") if x)
        items.append(
            f'        <li><a href="/jobs/{job_dir_name(r)}/">{html.escape(r["title"])}</a>'
            + (f"<span>{html.escape(meta)}</span>" if meta else "") + "</li>"
        )
    return (
        f'\n    <section class="related">\n'
        f'      <h2 class="desc-section-title">{html.escape(heading)}</h2>\n'
        '      <ul class="related-list">\n' + "\n".join(items) + "\n      </ul>\n"
        '    </section>'
    )


# ── Static job page ────────────────────────────────────────────────────────────
def build_page(row: dict, canonical_url: str, job_id: str, related: list = ()) -> str:
    title         = row["title"]
    university    = row["university"]
    uni_full      = row["university_full"] or university
    dept          = row["department"]
    rank          = row["rank"]
    deadline      = iso(row["deadline"])
    date_posted   = iso(row["date_posted"]) or iso(row["date_added"])
    apply_url     = safe_url(row["apply_url"])
    description   = row["description"]
    position_type = row["position_type"]
    salary        = row["salary"]
    reference     = row["reference"]
    start_date    = row["start_date"]
    closing       = deadline_display(row)

    # ── Meta strings ────────────────────────────────────────────────────────
    meta_title = f"{title} – {uni_full} | HK Academic Jobs"
    dept_part  = f" in the {dept}" if dept else ""
    dl_part    = f" Deadline: {closing}." if closing else ""
    meta_desc  = (
        f"{uni_full} is hiring a {title}{dept_part} in Hong Kong.{dl_part} "
        f"View full details and apply on HK Academic Jobs."
    )[:155]

    description_html = render_description_html(description)

    # ── JobPosting JSON-LD ───────────────────────────────────────────────────
    organization = {"@type": "Organization", "name": uni_full}
    if INSTITUTION_SITES.get(university):
        organization["sameAs"] = INSTITUTION_SITES[university]
    schema: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": description_html if description else title,
        "identifier": {
            "@type": "PropertyValue",
            "name": uni_full,
            "value": job_id,
        },
        "hiringOrganization": organization,
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Hong Kong",
                "addressCountry": "HK",
            },
        },
        "employmentType": employment_type_schema(position_type),
        "url": canonical_url,
        "directApply": False,
    }
    if date_posted:
        schema["datePosted"] = date_posted
    # Only a real closing date. Google treats validThrough as optional, and a
    # made-up one (or free text) makes the posting invalid or expired.
    if deadline:
        schema["validThrough"] = deadline + "T23:59:59+08:00"
    if dept:
        schema["industry"] = dept
    base_salary = parse_salary(salary)
    if base_salary:
        schema["baseSalary"] = base_salary

    # ── Visible content ─────────────────────────────────────────────────────
    info_rows = []
    if dept:
        info_rows.append(("Department", dept))
    if rank:
        info_rows.append(("Rank", rank))
    if position_type:
        info_rows.append(("Position type", position_type))
    if reference:
        info_rows.append(("Reference", reference))
    if iso(row["date_posted"]):
        info_rows.append(("Posted", format_date_display(row["date_posted"])))
    if start_date:
        info_rows.append(("Start date", format_date_display(start_date)))
    if salary:
        info_rows.append(("Salary / grade", salary))
    if closing:
        info_rows.append(("Application deadline", closing))
    info_html = "".join(
        f'<div class="info-row"><dt>{html.escape(label)}</dt>'
        f'<dd>{html.escape(value)}</dd></div>'
        for label, value in info_rows
    )

    # Deep-link to the SPA detail panel for users who want to browse more jobs
    spa_url = f"{BASE_URL}/?job={job_id}"
    apply_btn = tail_script = ""
    if apply_url:
        apply_btn = (
            f'      <a href="{html.escape(apply_url)}" class="btn btn-primary" id="applyBtn" '
            f'rel="noopener noreferrer" target="_blank"\n'
            f'         data-job-id="{html.escape(job_id)}" data-university="{html.escape(university)}" '
            f'data-rank="{html.escape(rank)}">\n'
            f'        Apply on {html.escape(university)} &rarr;\n'
            f'      </a>\n'
        )
        tail_script = """  <script>
    document.getElementById('applyBtn').addEventListener('click', function () {
      var d = this.dataset;
      gtag('event', 'apply_click', { job_id: d.jobId, university: d.university, rank: d.rank, source: 'static_page' });
    });
  </script>
"""

    main_html = f"""{breadcrumb_html(university, uni_full)}

    <h1 class="job-title">{html.escape(title)}</h1>
    <p class="job-uni">{html.escape(uni_full)}</p>

    <dl class="info-grid">
      {info_html}
    </dl>

    <div class="job-description">
      {description_html}
    </div>

    <div class="actions">
{apply_btn}      <a href="{html.escape(spa_url)}" class="btn btn-secondary">
        Browse more positions
      </a>
    </div>{related_html(related, f"More positions at {uni_full}")}"""

    return page_html(
        meta_title=meta_title, meta_desc=meta_desc, canonical=canonical_url,
        robots="index, follow",
        structured_data=[schema, breadcrumb_schema(university, uni_full, title, canonical_url)],
        main_html=main_html, tail_script=tail_script,
    )


def build_closed_page(entry: dict, canonical_url: str, related: list) -> str:
    """Kept for CLOSED_KEEP_DAYS after a job leaves the listings, so old links
    land on something useful instead of a 404. Not indexed."""
    title, university = entry["title"], entry["university"]
    uni_full = entry.get("university_full") or university
    deadline = iso(entry.get("deadline", ""))
    if deadline and deadline < TODAY.isoformat():
        when = f"Its application deadline was {format_date_display(deadline)}."
    else:
        when = f"It was removed from {uni_full}'s job listings on {format_date_display(entry['since'])}."
    main_html = f"""{breadcrumb_html(university, uni_full)}

    <h1 class="job-title">{html.escape(title)}</h1>
    <p class="job-uni">{html.escape(uni_full)}</p>

    <div class="closed-banner">
      <strong>This position is no longer open.</strong> {html.escape(when)}
      See the current openings there below.
    </div>

    <div class="actions">
      <a href="{html.escape(uni_filter_url(university))}" class="btn btn-primary">
        Open positions at {html.escape(university)} &rarr;
      </a>
      <a href="{BASE_URL}/" class="btn btn-secondary">
        Browse all positions
      </a>
    </div>{related_html(related, f"Open positions at {uni_full}")}"""
    return page_html(
        meta_title=f"Closed: {title} – {uni_full} | HK Academic Jobs",
        meta_desc=f"This {uni_full} position is no longer open. Browse current academic jobs in Hong Kong."[:155],
        canonical=canonical_url, robots="noindex, follow", structured_data=[],
        main_html=main_html,
    )


def build_moved_page(new_url: str) -> str:
    """The job's title (and so its URL) changed: send visitors and crawlers on."""
    u = html.escape(new_url)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>This position has moved | HK Academic Jobs</title>
  <link rel="canonical" href="{u}">
  <meta name="robots" content="noindex, follow">
  <meta http-equiv="refresh" content="0; url={u}">
</head>
<body>
  <p>This position has moved to <a href="{u}">{u}</a>.</p>
</body>
</html>
"""


# ── Sitemap ────────────────────────────────────────────────────────────────────
def build_sitemap(pages: list) -> str:
    """pages: [(url, lastmod)]"""
    entries = [f"""  <url>
    <loc>{BASE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <lastmod>{TODAY.isoformat()}</lastmod>
  </url>"""]
    for url, lastmod in pages:
        entries.append(f"""  <url>
    <loc>{url}</loc>
    <lastmod>{lastmod}</lastmod>
  </url>""")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


# ── Homepage block and lite CSV ────────────────────────────────────────────────
def build_latest_block(open_rows: list) -> str:
    newest = sorted(open_rows, key=lambda r: (iso(r["date_added"]), r["id"]), reverse=True)[:LATEST_COUNT]
    items = []
    for r in newest:
        meta = " · ".join(x for x in (
            r["university_full"] or r["university"], r["department"],
            deadline_display(r) and f"Deadline: {deadline_display(r)}") if x)
        items.append(
            f'      <li><a href="/jobs/{job_dir_name(r)}/">{html.escape(r["title"])}</a> '
            f'<span>{html.escape(meta)}</span></li>'
        )
    counts = Counter(r["university"] for r in open_rows)
    unis = " ".join(
        f'<a href="/?uni={html.escape(u)}">{html.escape(u)}&nbsp;({n})</a>'
        for u, n in sorted(counts.items())
    )
    return f"""
<section class="latest-jobs" id="latestJobs" aria-labelledby="latestJobsTitle">
  <h2 id="latestJobsTitle">Latest academic jobs in Hong Kong</h2>
  <p>{len(open_rows):,} open positions across {len(counts)} institutions, updated {format_date_display(TODAY.isoformat())}.</p>
  <p class="latest-unis">{unis}</p>
  <ul>
{chr(10).join(items)}
  </ul>
</section>
"""


def update_index(open_rows: list) -> bool:
    text = INDEX_HTML.read_text(encoding="utf-8")
    if not LATEST_BLOCK.search(text):
        print("::warning::index.html has no LATEST-JOBS markers; homepage block not updated")
        return False
    block = build_latest_block(open_rows)
    updated = LATEST_BLOCK.sub(lambda m: m.group(1) + block + m.group(3), text, count=1)
    return write_if_changed(INDEX_HTML, updated)


def lite_csv_text(fieldnames: list, rows: list) -> str:
    import io
    out = io.StringIO()
    lite_fields = [f for f in fieldnames if f != "description"]
    writer = csv.DictWriter(out, fieldnames=lite_fields, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


# ── Manifest ───────────────────────────────────────────────────────────────────
def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}

def save_manifest(manifest: dict):
    # One page per line keeps the daily git diff small
    lines = [
        f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}"
        for k, v in sorted(manifest.items())
    ]
    MANIFEST.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    today = TODAY.isoformat()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    for r in rows:
        for k in ("deadline_note",):   # older CSVs lack newer columns
            r.setdefault(k, "")

    open_by_dir, open_dir_by_id = {}, {}
    for r in rows:
        d = job_dir_name(r)
        if is_active(r) and d not in open_by_dir:
            open_by_dir[d] = r
            open_dir_by_id[r["id"]] = d
    open_rows = list(open_by_dir.values())
    by_uni = defaultdict(list)
    for r in open_rows:
        by_uni[r["university"]].append(r)

    old = load_manifest()
    manifest, pages = {}, {}

    for d, r in open_by_dir.items():
        canonical = f"{BASE_URL}/jobs/{d}/"
        pages[d] = build_page(r, canonical, r["id"],
                              related_jobs(r["id"], r["university"], r["department"], by_uni))
        h, prev = content_hash(r), old.get(d)
        if prev and prev.get("status") == "open" and prev.get("lastmod"):
            lastmod = prev["lastmod"] if prev.get("hash") == h else today
        elif prev or old:                # reopened, retitled or brand new
            lastmod = today
        else:                            # first run: when the job was first seen
            added = iso(r["date_added"])
            lastmod = added if added and added <= today else today
        manifest[d] = {
            "id": r["id"], "status": "open", "title": r["title"],
            "university": r["university"], "university_full": r["university_full"],
            "department": r["department"], "deadline": iso(r["deadline"]),
            "hash": h, "lastmod": lastmod,
        }

    closed = moved = expired = 0
    for d, prev in old.items():
        if d in pages:
            continue
        since = prev.get("since") if prev.get("status") in ("closed", "moved") else today
        if days_since(since) > CLOSED_KEEP_DAYS:
            expired += 1
            continue
        entry = {**prev, "since": since}
        entry.pop("lastmod", None)
        entry.pop("hash", None)
        new_dir = open_dir_by_id.get(prev.get("id"))
        if new_dir:
            entry["status"] = "moved"
            pages[d] = build_moved_page(f"{BASE_URL}/jobs/{new_dir}/")
            moved += 1
        else:
            entry["status"] = "closed"
            pages[d] = build_closed_page(
                entry, f"{BASE_URL}/jobs/{d}/",
                related_jobs(prev.get("id", d), prev["university"], prev.get("department", ""), by_uni))
            closed += 1
        manifest[d] = entry

    written = sum(write_if_changed(JOBS_DIR / d / "index.html", content) for d, content in pages.items())

    removed = 0
    if JOBS_DIR.exists():
        for p in JOBS_DIR.iterdir():
            if p.is_dir() and p.name not in pages:
                shutil.rmtree(p)
                removed += 1

    save_manifest(manifest)
    sitemap = sorted(
        (f"{BASE_URL}/jobs/{d}/", e["lastmod"]) for d, e in manifest.items() if e["status"] == "open"
    )
    write_if_changed(SITEMAP, build_sitemap(sitemap))
    write_if_changed(LITE_CSV, lite_csv_text(fieldnames, rows))
    index_changed = update_index(open_rows)

    print(f"Done: {len(open_rows)} open job pages, {closed} closed and {moved} moved pages kept; "
          f"{written} files written, {removed} folders removed ({expired} past {CLOSED_KEEP_DAYS} days)")
    print(f"Sitemap: {len(sitemap) + 1} URLs → {SITEMAP}")
    print(f"Homepage latest-jobs block {'updated' if index_changed else 'unchanged'}")


if __name__ == "__main__":
    main()
