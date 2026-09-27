"""Hong Kong Shue Yan University: job scraper."""

import re

import requests

from core import (
    clean, detect_rank, detect_type, get_soup, HEADERS, make_id, parse_date_text,
    PLACEHOLDER_MARKER, _existing_descriptions, _has_good_desc,
)


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
