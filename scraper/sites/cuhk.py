"""Chinese University of Hong Kong: job scraper."""

import re

from bs4 import BeautifulSoup

from core import (
    clean, detect_rank, detect_type, due_for_recheck, HEADERS, ISO_DATE, make_id,
    parse_date_text, _has_good_desc, _previous_rows,
)


def scrape_cuhk():
    """
    CUHK — Taleo Enterprise ATS (cuhk.taleo.net)
    Two career sections: teaching + non-teaching (research) posts.
    JS-rendered table: Job Number | Requisition Title | Department/Unit
    Paginates via Next button.
    """
    print("📋 Scraping CUHK...")

    BASE = "https://cuhk.taleo.net"
    SECTIONS = [
        (f"{BASE}/careersection/cu_career_teach/jobsearch.ftl?lang=en",     "Teaching"),
        (f"{BASE}/careersection/cu_career_non_teach/jobsearch.ftl?lang=en", "Research/Non-teaching"),
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
                # One retry: a timed-out section used to be skipped silently,
                # leaving CUHK with half its jobs (30 Jul – 13 Aug 2026)
                loaded = False
                for attempt in (1, 2):
                    try:
                        page.goto(URL, timeout=60000, wait_until="domcontentloaded")
                        page.wait_for_selector("table tr td a", timeout=30000)
                        loaded = True
                        break
                    except Exception:
                        print(f"  ⚠️  {section_name}: job table didn't load (attempt {attempt})")
                if not loaded:
                    page.close()
                    continue

                page_num   = 1
                sect_count = 0

                while True:
                    soup = BeautifulSoup(page.content(), "html.parser")
                    rows = soup.select("table tbody tr, table tr")
                    page_jobs = 0
                    for row in rows:
                        cells = row.find_all("td")
                        if len(cells) < 3:
                            continue
                        ref = title = dept = apply_url = ""
                        for i, cell in enumerate(cells):
                            t = clean(cell.get_text())
                            if not ref and re.match(r"^\d{5,8}$", t):
                                ref = t
                            link = cell.find("a", href=True)
                            if not title and link:
                                title = clean(link.get_text())
                                href  = link.get("href", "")
                                apply_url = f"{BASE}{href}" if href.startswith("/") else href
                            if title and not dept and not link and len(t) > 5 and not re.match(r"^\d+$", t):
                                dept = t
                        if not title or len(title) < 5:
                            continue
                        dedup_key = ref if ref else f"{title}|{dept}"
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        dept = dept or "Chinese University of Hong Kong"
                        jobs.append({
                            "id":               make_id("CUHK", ref if ref else f"{title}|{dept}"),
                            "title":            title,
                            "rank":             detect_rank(title),
                            "university":       "CUHK",
                            "university_full":  "Chinese University of Hong Kong",
                            "department":       dept,
                            "deadline":         "",
                            "is_new":           "TRUE",
                            "reference":        ref,
                            "position_type":    detect_type(title),
                            "salary":           "",
                            "start_date":       "",
                            "apply_url":        apply_url or URL,
                            "description":      f"{title} — {dept}. Please visit the application link for full details.",
                        })
                        page_jobs += 1
                        sect_count += 1

                    # Next button: check disabled via BS4 before clicking
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

            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    # Reuse closing dates found on earlier runs. Only open a detail page for a
    # job without a cached summary, or — once a week per job — one still
    # missing a date (this used to re-open every CUHK job page every day).
    for j in jobs:
        prev = _previous_rows.get(j["id"])
        if prev and not j["deadline"] and ISO_DATE.match(prev.get("deadline") or ""):
            j["deadline"] = prev["deadline"]
    needs_detail = [j for j in jobs if j["apply_url"] and (
        not _has_good_desc(j["id"]) or (not j["deadline"] and due_for_recheck(j["id"])))]
    if needs_detail:
        print(f"  ↳ Fetching {len(needs_detail)} detail pages for dates/descriptions...")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                detail_page = browser.new_page()
                detail_page.set_extra_http_headers(HEADERS)
                found_date = 0
                found_desc = 0
                for job in needs_detail:
                    try:
                        detail_page.goto(job["apply_url"], timeout=30000, wait_until="networkidle")
                        detail_page.wait_for_timeout(3000)
                        text = detail_page.inner_text("body")
                        # Closing date
                        if not job["deadline"]:
                            m = re.search(r'[Cc]losing\s+[Dd]ate[:\s]+(\w+\s+\d{1,2},\s+\d{4})', text)
                            if m:
                                job["deadline"] = parse_date_text(m.group(1))
                                found_date += 1
                        # Description: skip nav/header, take substantive body lines
                        if not _has_good_desc(job["id"]):
                            # Find start of actual content after the header line
                            start_marker = "Description\n"
                            start = text.find(start_marker)
                            block = text[start + len(start_marker):] if start > 0 else text
                            lines = [l.strip() for l in block.splitlines() if len(l.strip()) > 30]
                            if lines:
                                job["description"] = "\n\n".join(lines[:60])[:8000]
                                found_desc += 1
                    except Exception:
                        pass
                detail_page.close()
                browser.close()
            print(f"  ↳ Found closing dates for {found_date}, descriptions for {found_desc}/{len(needs_detail)} jobs")
        except Exception as pe:
            print(f"  ↳ Detail page fetch failed: {pe}")

    print(f"  ✅ CUHK: {len(jobs)} jobs found")
    return jobs
