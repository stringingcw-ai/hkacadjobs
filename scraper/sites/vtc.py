"""Vocational Training Council: job scraper."""

import re

from core import (
    BOT_MARKERS, clean, detect_rank, get_soup, make_id, parse_date_text, PLACEHOLDER_MARKER,
    _existing_descriptions, _has_good_desc,
)


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
