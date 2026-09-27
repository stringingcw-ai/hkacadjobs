"""Hong Kong Metropolitan University: job scraper."""

import re

from bs4 import BeautifulSoup

from core import (
    clean, detect_rank, detect_type, HEADERS, is_within_retention, make_id, parse_date_text,
    _existing_descriptions, _has_good_desc,
)


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
