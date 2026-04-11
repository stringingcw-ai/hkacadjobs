"""
generate_job_pages.py
Reads jobs.csv and writes:
  - jobs/<slug>-<id>/index.html  — standalone SEO-friendly page per active job
      Contains:
        * Per-job <title>, <meta description>, canonical URL
        * Open Graph + Twitter Card tags (with og:image)
        * JobPosting JSON-LD structured data (for Google for Jobs)
        * Full visible job description (so Googlebot sees real content)
        * Apply link + "Browse all jobs" link back to the main site
      Important: these pages DO NOT auto-redirect via JS. Googlebot would
      treat that as a soft 404. Users arriving via Google see a real page.
  - sitemap.xml  — homepage + all active job URLs

Run from repo root:
  python scraper/generate_job_pages.py
"""

import csv
import html
import json
import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL  = "https://www.hkacadjobs.org"
OG_IMAGE  = f"{BASE_URL}/og-image.png"
REPO_ROOT = Path(__file__).parent.parent
CSV_PATH  = REPO_ROOT / "jobs.csv"
JOBS_DIR  = REPO_ROOT / "jobs"
SITEMAP   = REPO_ROOT / "sitemap.xml"
TODAY     = date.today()

# Employment type mapping for schema.org
EMPLOYMENT_TYPE_MAP = {
    "full-time":  "FULL_TIME",
    "part-time":  "PART_TIME",
    "contract":   "CONTRACTOR",
    "temporary":  "TEMPORARY",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
_slug_re = re.compile(r"[^a-z0-9]+")

def slugify(text: str) -> str:
    ascii_text = text.encode("ascii", "ignore").decode()
    result = _slug_re.sub("-", ascii_text.lower()).strip("-")[:60]
    return result or "position"

def format_date_display(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%-d %b %Y")
    except Exception:
        return iso

def is_active(row: dict) -> bool:
    dl = row.get("deadline", "")
    return not (dl and dl < str(TODAY))

def employment_type_schema(position_type: str) -> str:
    pt = (position_type or "").lower()
    for k, v in EMPLOYMENT_TYPE_MAP.items():
        if k in pt:
            return v
    return "FULL_TIME"

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

# ── Static job page ────────────────────────────────────────────────────────────
def build_page(row: dict, canonical_url: str, job_id: str) -> str:
    title         = row["title"]
    uni_full      = row["university_full"] or row["university"]
    dept          = row["department"]
    rank          = row["rank"]
    deadline      = row["deadline"]
    date_posted   = row["date_posted"] or row["date_added"]
    apply_url     = row["apply_url"]
    description   = row["description"]
    position_type = row["position_type"]
    salary        = row["salary"]
    reference     = row["reference"]
    start_date    = row["start_date"]

    # ── Meta strings ────────────────────────────────────────────────────────
    meta_title = f"{title} – {uni_full} | HK Academic Jobs"
    dept_part  = f" in the {dept}" if dept else ""
    dl_part    = f" Deadline: {format_date_display(deadline)}." if deadline else ""
    meta_desc  = (
        f"{uni_full} is hiring a {title}{dept_part} in Hong Kong.{dl_part} "
        f"View full details and apply on HK Academic Jobs."
    )[:155]

    # ── JobPosting JSON-LD ───────────────────────────────────────────────────
    schema: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": (description or title)[:5000],
        "identifier": {
            "@type": "PropertyValue",
            "name": uni_full,
            "value": job_id,
        },
        "hiringOrganization": {
            "@type": "Organization",
            "name": uni_full,
            "sameAs": BASE_URL,
        },
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
    # Google for Jobs requires validThrough. Fall back to 90 days from
    # datePosted (or today) when the source site doesn't publish a deadline.
    if deadline:
        schema["validThrough"] = deadline + "T23:59:59+08:00"
    else:
        try:
            base = datetime.strptime(date_posted, "%Y-%m-%d").date() if date_posted else TODAY
        except ValueError:
            base = TODAY
        fallback = base + timedelta(days=90)
        schema["validThrough"] = fallback.isoformat() + "T23:59:59+08:00"
    if dept:
        schema["industry"] = dept
    if salary:
        schema["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": "HKD",
            "value": {"@type": "QuantitativeValue", "description": salary},
        }
    if apply_url:
        schema["applicantLocationRequirements"] = {
            "@type": "Country",
            "name": "Hong Kong",
        }

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    # ── Visible content ─────────────────────────────────────────────────────
    description_html = render_description_html(description)

    # Info rows (only show non-empty ones)
    info_rows = []
    if dept:
        info_rows.append(("Department", dept))
    if rank:
        info_rows.append(("Rank", rank))
    if position_type:
        info_rows.append(("Position type", position_type))
    if reference:
        info_rows.append(("Reference", reference))
    if start_date:
        info_rows.append(("Start date", start_date))
    if salary:
        info_rows.append(("Salary / grade", salary))
    if deadline:
        info_rows.append(("Application deadline", format_date_display(deadline)))
    info_html = "".join(
        f'<div class="info-row"><dt>{html.escape(label)}</dt>'
        f'<dd>{html.escape(value)}</dd></div>'
        for label, value in info_rows
    )

    # Deep-link to the SPA detail panel for users who want to browse more jobs
    spa_url = f"{BASE_URL}/?job={job_id}"
    apply_href = html.escape(apply_url) if apply_url else "#"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(meta_title)}</title>
  <meta name="description" content="{html.escape(meta_desc)}">
  <link rel="canonical" href="{canonical_url}">
  <meta name="robots" content="index, follow">

  <!-- Open Graph -->
  <meta property="og:site_name" content="HKAcadJobs">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{html.escape(meta_title)}">
  <meta property="og:description" content="{html.escape(meta_desc)}">
  <meta property="og:url" content="{canonical_url}">
  <meta property="og:image" content="{OG_IMAGE}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">

  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(meta_title)}">
  <meta name="twitter:description" content="{html.escape(meta_desc)}">
  <meta name="twitter:image" content="{OG_IMAGE}">

  <!-- JobPosting structured data (Google for Jobs) -->
  <script type="application/ld+json">
{schema_json}
  </script>

  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">

  <!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-GSSYS240VQ"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'G-GSSYS240VQ');
  </script>

  <style>
    :root {{
      --ink: #0f1117;
      --paper: #f5f2eb;
      --cream: #ece8df;
      --accent: #b5451b;
      --muted: #7a7568;
      --border: #d8d3c8;
      --white: #ffffff;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color: var(--accent); }}

    nav.site-nav {{
      background: var(--ink);
      padding: 0 24px;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    nav.site-nav .logo {{
      font-family: 'Playfair Display', serif;
      color: var(--paper);
      font-size: 1.25rem;
      text-decoration: none;
      letter-spacing: -0.02em;
    }}
    nav.site-nav .logo span {{ color: var(--accent); }}
    nav.site-nav .back-link {{
      color: var(--paper);
      font-size: 0.85rem;
      text-decoration: none;
      opacity: 0.8;
    }}
    nav.site-nav .back-link:hover {{ opacity: 1; }}

    main {{
      max-width: 760px;
      margin: 0 auto;
      padding: 48px 24px 80px;
    }}
    .breadcrumb {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 18px;
    }}
    .breadcrumb a {{ color: var(--muted); text-decoration: none; }}
    .breadcrumb a:hover {{ color: var(--accent); }}
    h1.job-title {{
      font-family: 'Playfair Display', serif;
      font-size: 2rem;
      line-height: 1.25;
      margin-bottom: 10px;
    }}
    p.job-uni {{
      font-size: 1rem;
      color: var(--accent);
      font-weight: 600;
      margin-bottom: 28px;
    }}
    dl.info-grid {{
      background: var(--white);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 22px;
      margin-bottom: 32px;
    }}
    .info-row {{
      display: flex;
      gap: 16px;
      padding: 8px 0;
      border-bottom: 1px solid var(--cream);
      font-size: 0.9rem;
    }}
    .info-row:last-child {{ border-bottom: none; }}
    .info-row dt {{
      flex: 0 0 150px;
      color: var(--muted);
      font-weight: 500;
    }}
    .info-row dd {{ flex: 1; color: var(--ink); }}

    .desc-section {{ margin-bottom: 28px; }}
    h2.desc-section-title {{
      font-family: 'Playfair Display', serif;
      font-size: 1.2rem;
      margin-bottom: 10px;
      color: var(--ink);
    }}
    .desc-section ul {{
      list-style: none;
      padding: 0;
    }}
    .desc-section li {{
      position: relative;
      padding-left: 20px;
      margin-bottom: 8px;
      font-size: 0.95rem;
    }}
    .desc-section li::before {{
      content: "•";
      position: absolute;
      left: 4px;
      color: var(--accent);
      font-weight: bold;
    }}

    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 36px;
      padding-top: 24px;
      border-top: 1px solid var(--border);
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 12px 22px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.92rem;
      text-decoration: none;
      transition: background 0.15s;
    }}
    .btn-primary {{
      background: var(--accent);
      color: var(--white);
    }}
    .btn-primary:hover {{ background: #9b3a14; }}
    .btn-secondary {{
      background: var(--cream);
      color: var(--ink);
      border: 1px solid var(--border);
    }}
    .btn-secondary:hover {{ background: var(--white); }}

    footer {{
      max-width: 760px;
      margin: 0 auto;
      padding: 24px;
      font-size: 0.8rem;
      color: var(--muted);
      border-top: 1px solid var(--border);
      text-align: center;
    }}
    footer a {{ color: var(--muted); }}

    @media (max-width: 600px) {{
      main {{ padding: 32px 18px 60px; }}
      h1.job-title {{ font-size: 1.55rem; }}
      .info-row {{ flex-direction: column; gap: 2px; padding: 6px 0; }}
      .info-row dt {{ flex-basis: auto; font-size: 0.78rem; }}
    }}
  </style>
</head>
<body>
  <nav class="site-nav">
    <a href="{BASE_URL}/" class="logo">HK<span>AcadJobs</span></a>
    <a href="{BASE_URL}/" class="back-link">← All positions</a>
  </nav>

  <main>
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="{BASE_URL}/">HKAcadJobs</a> &rsaquo; {html.escape(uni_full)}
    </nav>

    <h1 class="job-title">{html.escape(title)}</h1>
    <p class="job-uni">{html.escape(uni_full)}</p>

    <dl class="info-grid">
      {info_html}
    </dl>

    <div class="job-description">
      {description_html}
    </div>

    <div class="actions">
      <a href="{apply_href}" class="btn btn-primary" rel="noopener noreferrer" target="_blank">
        Apply on {html.escape(row["university"])} &rarr;
      </a>
      <a href="{spa_url}" class="btn btn-secondary">
        Browse more positions
      </a>
    </div>
  </main>

  <footer>
    <p>
      <a href="{BASE_URL}/">HKAcadJobs</a> aggregates academic openings from 17 Hong Kong institutions.
      Listings are updated daily. This page reflects data as of {TODAY.isoformat()}.
    </p>
  </footer>
</body>
</html>"""


# ── Sitemap ────────────────────────────────────────────────────────────────────
def build_sitemap(job_urls: list[str]) -> str:
    today_str = TODAY.isoformat()
    entries = [f"""  <url>
    <loc>{BASE_URL}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
    <lastmod>{today_str}</lastmod>
  </url>"""]
    for u in job_urls:
        entries.append(f"""  <url>
    <loc>{u}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
    <lastmod>{today_str}</lastmod>
  </url>""")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if JOBS_DIR.exists():
        shutil.rmtree(JOBS_DIR)
    JOBS_DIR.mkdir()

    job_urls = []
    written = skipped = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not is_active(row):
                skipped += 1
                continue

            job_id   = row["id"]
            slug     = slugify(row["title"])
            dir_name = f"{slug}-{job_id.lower()}"
            out_dir  = JOBS_DIR / dir_name
            out_dir.mkdir(exist_ok=True)

            canonical = f"{BASE_URL}/jobs/{dir_name}/"
            (out_dir / "index.html").write_text(
                build_page(row, canonical, job_id), encoding="utf-8"
            )
            job_urls.append(canonical)
            written += 1

    SITEMAP.write_text(build_sitemap(job_urls), encoding="utf-8")
    print(f"Done: {written} job pages written, {skipped} expired skipped")
    print(f"Sitemap: {len(job_urls) + 1} URLs → {SITEMAP}")


if __name__ == "__main__":
    main()
