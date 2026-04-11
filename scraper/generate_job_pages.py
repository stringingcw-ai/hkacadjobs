"""
generate_job_pages.py
Reads jobs.csv and writes:
  - jobs/<slug>-<id>/index.html  — thin SEO page per active job
      Contains: title, meta description, canonical, JobPosting JSON-LD
      JS immediately redirects humans to /?job=<id> (opens the main site
      with the detail panel pre-opened). Googlebot indexes the static content.
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
from datetime import date, datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL  = "https://www.hkacadjobs.org"
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

# ── Thin redirect page ─────────────────────────────────────────────────────────
def build_page(row: dict, canonical_url: str, job_id: str) -> str:
    title       = row["title"]
    uni_full    = row["university_full"] or row["university"]
    dept        = row["department"]
    deadline    = row["deadline"]
    date_posted = row["date_posted"] or row["date_added"]
    apply_url   = row["apply_url"]
    description = row["description"]
    position_type = row["position_type"]
    salary      = row["salary"]

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
        "description": description[:5000] if description else title,
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
    if deadline:
        schema["validThrough"] = deadline + "T23:59:59+08:00"
    if salary:
        schema["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": "HKD",
            "value": {"@type": "QuantitativeValue", "description": salary},
        }

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    # Redirect destination: main site with ?job= param to auto-open the panel
    redirect_url = f"{BASE_URL}/?job={job_id}"

    # Minimal visible fallback for no-JS / Googlebot rendering
    dept_display = f" · {html.escape(dept)}" if dept else ""
    dl_display   = f"<p>Application deadline: <strong>{html.escape(format_date_display(deadline))}</strong></p>" if deadline else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(meta_title)}</title>
  <meta name="description" content="{html.escape(meta_desc)}">
  <link rel="canonical" href="{canonical_url}">
  <meta property="og:title" content="{html.escape(meta_title)}">
  <meta property="og:description" content="{html.escape(meta_desc)}">
  <meta property="og:url" content="{canonical_url}">
  <meta property="og:type" content="website">
  <meta name="robots" content="index, follow">
  <script type="application/ld+json">
{schema_json}
  </script>
  <!-- Redirect JS-enabled users to the main site with the panel pre-opened -->
  <script>window.location.replace({json.dumps(redirect_url)});</script>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f7f6f2; color: #1a1a18;
           max-width: 600px; margin: 60px auto; padding: 0 20px; line-height: 1.6; }}
    h1   {{ font-size: 1.4rem; margin-bottom: 6px; }}
    .uni {{ color: #555; margin-bottom: 16px; font-size: 0.95rem; }}
    a    {{ color: #e6a817; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="uni">{html.escape(uni_full)}{html.escape(dept_display)}</p>
  {dl_display}
  <p>
    <a href="{html.escape(redirect_url)}">View on HK Academic Jobs ↗</a>
    &nbsp;·&nbsp;
    <a href="{html.escape(apply_url)}" rel="noopener noreferrer">Apply directly ↗</a>
  </p>
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
    print(f"Done: {written} redirect pages written, {skipped} expired skipped")
    print(f"Sitemap: {len(job_urls) + 1} URLs → {SITEMAP}")


if __name__ == "__main__":
    main()
