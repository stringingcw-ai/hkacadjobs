"""City University of Hong Kong: job scraper."""

import re

from core import (
    BOT_MARKERS, clean, detect_rank, detect_type, get_soup, HEADERS, is_active,
    is_within_retention, make_id, parse_date_text, _existing_descriptions, _has_good_desc,
)


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
