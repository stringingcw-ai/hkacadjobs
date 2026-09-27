"""Hong Kong University of Science and Technology: job scraper."""

import re

from core import (
    BOT_MARKERS, clean, detect_rank, detect_type, HEADERS, is_active, is_within_retention,
    make_id, parse_date_text, _existing_descriptions, _has_good_desc, _previous_rows,
)


def scrape_hkust():
    """
    HKUST — hkustcareers.hkust.edu.hk
    Two pages: academic-careers and teaching-support.
    JS extracts raw card text; Python does all parsing.
    """
    print("📋 Scraping HKUST...")

    URLS = [
        ("https://hkustcareers.hkust.edu.hk/join-us/current-opening/academic-careers", "Academic"),
        ("https://hkustcareers.hkust.edu.hk/join-us/current-opening/teaching-support",  "Teaching"),
    ]
    jobs = []

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for url, pos_type in URLS:
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)
                page.wait_for_timeout(3000)

                # Check how many Job IDs are in the page
                full_text = page.inner_text("body")
                job_id_count = full_text.count("Job ID")
                print(f"  ↳ {pos_type}: {job_id_count} Job IDs in page text")

                seen_ids = set()
                for m in re.finditer(r'Job ID: (\d+)', full_text):
                    ref = m.group(1)
                    if ref in seen_ids:
                        continue
                    seen_ids.add(ref)

                    before = full_text[max(0, m.start()-300):m.start()]
                    after  = full_text[m.end():m.end()+300]

                    # Title: last meaningful line before Job ID (skip filter labels like "School (3)")
                    before_lines = [l.strip() for l in before.splitlines() if l.strip()]
                    title = ""
                    for line in reversed(before_lines):
                        if re.search(r'\(\d+\)$', line):
                            continue
                        if len(line) > 4:
                            title = line
                            break

                    # Dept: first non-empty line after Job ID before date lines
                    after_lines = [l.strip() for l in after.splitlines() if l.strip()]
                    dept = ""
                    for line in after_lines:
                        if re.match(r'Open Date|Apply by|\d{4}-\d{2}', line):
                            break
                        if len(line) > 4:
                            dept = line
                            break

                    # Deadline — optional, some cards don't have it
                    deadline_m = re.search(r'Apply by: ([\d\-]+)', after)
                    deadline = parse_date_text(deadline_m.group(1)) if deadline_m else ""

                    title = clean(title)
                    if not title or len(title) < 4:
                        continue

                    # Use ref as unique ID (same title can appear with different Job IDs)
                    jobs.append({
                        "id":               make_id("HKUST", ref),
                        "title":            title,
                        "rank":             detect_rank(title),
                        "university":       "HKUST",
                        "university_full":  "HK University of Science & Technology",
                        "department":       dept,
                        "deadline":         deadline,
                        "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                        "reference":        ref,
                        "position_type":    detect_type(title),
                        "salary":           "",
                        "start_date":       "",
                        "apply_url":        f"https://hrmsxprod.psft.ust.hk:8044/psp/hrmsxprod/EMPLOYEE/HRMS/c/HRS_HRAM.HRS_CE.GBL?Page=HRS_CE_JOB_DTL&Action=A&JobOpeningId={ref}&SiteId=1000&PostingSeq=1",
                        "description":      f"{title}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
                    })

                # Map Interfolio links to job IDs positionally:
                # walk all text nodes in order, collect (jobId, linkHref) pairs where
                # each link is assigned to the most recently seen Job ID before it.
                try:
                    il_map = page.evaluate("""
                        () => {
                            const result = {};
                            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ALL);
                            let currentJobId = null;
                            let node;
                            while (node = walker.nextNode()) {
                                if (node.nodeType === Node.TEXT_NODE) {
                                    const m = node.textContent.trim().match(/^Job ID: (\\d+)$/);
                                    if (m) currentJobId = m[1];
                                } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'A') {
                                    const href = node.href || '';
                                    if (currentJobId && href.includes('interfolio') && !result[currentJobId]) {
                                        result[currentJobId] = href;
                                    }
                                }
                            }
                            return result;
                        }
                    """)
                    for j in jobs:
                        if j["reference"] in il_map:
                            new_url = il_map[j["reference"]]
                            # Refresh the cached summary only if the link changed since
                            # the last run. (This compared against the PeopleSoft URL
                            # built above, so it always differed and ~50 HKUST jobs
                            # were re-summarised every day.)
                            prev_url = (_previous_rows.get(j["id"]) or {}).get("apply_url", "")
                            if prev_url and prev_url != new_url:
                                _existing_descriptions.pop(j["id"], None)
                            j["apply_url"] = new_url
                except Exception:
                    pass

                page.close()

            # Fetch Interfolio detail pages only. The PeopleSoft links are the ones
            # HKUST itself publishes, but their pages need a portal session.
            to_fetch = [
                j for j in jobs
                if is_within_retention(j["deadline"])
                and not _has_good_desc(j["id"])
                and "interfolio" in j.get("apply_url", "")
            ]
            if to_fetch:
                print(f"  ↳ Fetching {len(to_fetch)} detail pages for descriptions...")
                detail_page = browser.new_page()
                detail_page.set_extra_http_headers(HEADERS)
                found = 0
                for idx, j in enumerate(to_fetch, 1):
                    try:
                        detail_page.goto(j["apply_url"], timeout=20000, wait_until="networkidle")
                        detail_page.wait_for_timeout(2000)
                        text = detail_page.inner_text("body")
                        if any(m in text.lower() for m in BOT_MARKERS):
                            continue
                        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                        if lines:
                            j["description"] = "\n\n".join(lines[:60])[:8000]
                            found += 1
                    except Exception:
                        pass
                    if idx % 5 == 0 or idx == len(to_fetch):
                        print(f"  ↳ {idx}/{len(to_fetch)} done")
                detail_page.close()
                print(f"  ↳ Got descriptions for {found}/{len(to_fetch)} jobs")
            # Restore cached summaries for skipped/failed jobs
            for j in jobs:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ HKUST: {len(jobs)} jobs found")
    return jobs
