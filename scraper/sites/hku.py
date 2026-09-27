"""University of Hong Kong: job scraper."""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from core import (
    BOT_MARKERS, clean, detect_rank, detect_type, HEADERS, is_active, is_within_retention,
    make_id, parse_date_text, PLACEHOLDER_MARKER, _existing_descriptions, _has_good_desc,
)


def scrape_hku():
    """
    HKU — jobs.hku.hk/en/listing/ (PageUp ATS)
    Fetches every listing row in one request (?page=1&page-items=1000) instead of
    clicking "More Jobs"; falls back to loading that URL in a browser.
    """
    print("📋 Scraping HKU...")

    ADMIN_KEYWORDS = {
        "administrative assistant", "clerical assistant",
        "finance officer", "it officer", "facilities manager",
        "procurement officer", "human resources officer",
        "security officer", "safety officer", "receptionist",
        "estate manager", "accounting officer", "payroll officer",
    }

    def parse_jobs(html, seen):
        result = []
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all("tr"):
            link = row.find("a", href=True)
            if not link:
                continue
            title = clean(link.get_text())
            if not title or len(title) < 5:
                continue
            href = link.get("href", "")
            apply_url = f"https://jobs.hku.hk{href}" if href.startswith("/") else href
            cells = row.find_all("td")
            ref = dept = deadline = ""
            for cell in cells:
                t = clean(cell.get_text())
                if re.match(r"^\d{5,8}$", t):
                    ref = t
                elif re.search(r"Faculty|Department|School|Institute|Centre|Office|Library", t, re.I) and t != title:
                    dept = t
                else:
                    parsed = parse_date_text(t)
                    if parsed and parsed != t:
                        deadline = parsed
            dept = dept or "University of Hong Kong"
            dedup_key = ref if ref else f"{title}|{dept}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            title_lower = title.lower()
            if any(kw in title_lower for kw in ADMIN_KEYWORDS):
                continue
            result.append({
                "id":               make_id("HKU", ref or title[:25]),
                "title":            title,
                "rank":             detect_rank(title),
                "university":       "HKU",
                "university_full":  "University of Hong Kong",
                "department":       dept,
                "deadline":         deadline,
                "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                "reference":        ref,
                "position_type":    detect_type(title),
                "salary":           "",
                "start_date":       "",
                "apply_url":        apply_url,
                "description":      f"{title} — {dept}. Please visit the application link for full details.",
            })
        return result

    jobs = []

    # The listing's "More Jobs" button only fetches the next 20 rows
    # (page=N&page-items=20). Asking for every row in one page is a single
    # request that can't stop half-way — the old click loop waited a fixed
    # 1.5 s per batch and quit early whenever the site was slow.
    LISTING_ALL = "https://jobs.hku.hk/en/listing/?page=1&page-items=1000"
    listing_html = None
    try:
        resp = requests.get(LISTING_ALL, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        listing_html = resp.text
    except Exception as e:
        print(f"  ⚠️  Direct listing fetch failed ({e}); retrying in a browser")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            if listing_html is None:
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(LISTING_ALL, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_selector("a[href*='/en/job/']", timeout=30000)
                listing_html = page.content()
                page.close()

            seen = set()
            parsed = parse_jobs(listing_html, seen)
            jobs.extend(parsed)
            listed = len(set(re.findall(r'href="/en/job/(\d+)', listing_html)))
            print(f"  ↳ Listing has {listed} job links; parsed {len(parsed)} jobs (admin roles skipped)")
            more = BeautifulSoup(listing_html, "html.parser").select_one("a.more-link .count")
            if more and clean(more.get_text()).isdigit() and int(clean(more.get_text())) > 0:
                print(f"  ⚠️  Listing still reports {clean(more.get_text())} more jobs — raise page-items")

            # Fetch detail pages for descriptions (skip known good summaries)
            # Use fresh browser contexts in batches to avoid session-based rate limiting.
            # HKU detail pages are AWS WAF protected — only the first ~35 requests succeed
            # before being blocked. Prioritise tenure-track/lecturer roles so the most
            # valuable jobs get descriptions first.
            RANK_PRIORITY = {
                "Tenure-Track": 0, "Professor": 1, "Associate Professor": 2,
                "Assistant Professor": 3, "Senior Lecturer/Lecturer": 4, "Lecturer": 4,
                "Postdoctoral": 5, "Research Assistant/Associate": 6,
            }
            active = [j for j in parsed if is_within_retention(j["deadline"]) and not _has_good_desc(j["id"])]
            active.sort(key=lambda j: (
                RANK_PRIORITY.get(j.get("rank", ""), 99),
                -(datetime.strptime(j["date_added"], "%Y-%m-%d").toordinal() if j.get("date_added") else 0),
            ))
            if active:
                import random
                print(f"  ↳ Fetching {len(active)} detail pages for descriptions (priority: academic first)...")
                found = 0
                BATCH = 20  # fresh context every N requests
                for batch_start in range(0, len(active), BATCH):
                    batch = active[batch_start:batch_start + BATCH]
                    ctx = browser.new_context()
                    ctx.set_extra_http_headers(HEADERS)
                    detail_page = ctx.new_page()
                    for idx_in_batch, j in enumerate(batch):
                        idx = batch_start + idx_in_batch + 1
                        try:
                            detail_page.goto(j["apply_url"], timeout=20000, wait_until="domcontentloaded")
                            detail_page.wait_for_timeout(random.randint(2500, 4500))
                            text = detail_page.inner_text("body")
                            if any(m in text.lower() for m in BOT_MARKERS):
                                if _has_good_desc(j["id"]):
                                    j["description"] = _existing_descriptions[j["id"]]
                                else:
                                    j["description"] = PLACEHOLDER_MARKER
                                continue
                            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                            # Guard against short/error pages slipping through WAF check
                            if lines and len(" ".join(lines)) >= 200:
                                j["description"] = "\n\n".join(lines[:60])[:8000]
                                found += 1
                            else:
                                j["description"] = PLACEHOLDER_MARKER
                        except Exception:
                            j["description"] = PLACEHOLDER_MARKER
                        if idx % 10 == 0 or idx == len(active):
                            print(f"  ↳ {idx}/{len(active)} done")
                    detail_page.close()
                    ctx.close()
                print(f"  ↳ Got descriptions for {found}/{len(active)} jobs")
            # Restore cached summaries for skipped jobs
            for j in parsed:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ HKU: {len(jobs)} jobs found")
    return jobs
