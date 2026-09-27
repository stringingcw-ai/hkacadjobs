"""HKU SPACE: job scraper."""

import re

from core import (
    clean, detect_rank, get_soup, make_id, parse_date_text, _existing_descriptions,
    _has_good_desc,
)


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
