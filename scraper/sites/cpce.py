"""PolyU CPCE (HKCC / SPEED): job scraper."""

import re
from datetime import datetime

from core import (
    clean, date_in_text, detect_rank, detect_type, get_soup, ISO_DATE, make_id,
    parse_date_text, _existing_descriptions, _has_good_desc,
)


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
