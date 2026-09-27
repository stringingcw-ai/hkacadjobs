"""Hong Kong Baptist University: job scraper."""

import re

import requests
from bs4 import BeautifulSoup

from core import (
    BOT_MARKERS, clean, detect_rank, detect_type, HEADERS, infer_dept_from_title, ISO_DATE,
    make_id, _existing_descriptions, _has_good_desc,
)


def scrape_hkbu():
    """
    HKBU — Oracle HCM Cloud Candidate Experience (site "hkbu", siteNumber CX_1)
    Calls the same recruitingCEJobRequisitions query the careers site makes
    (finder=findReqs); limit=200 returns every job with its description in one
    request, so no detail pages are needed. (The old "CandidateExperience"
    finder returned 400 on every run.) Falls back to scrolling the careers site.
    """
    print("📋 Scraping HKBU...")

    BASE  = "https://fa-ewqq-saasfaprod1.fa.ocs.oraclecloud.com"
    SITE  = f"{BASE}/hcmUI/CandidateExperience/en/sites/hkbu"
    API   = f"{BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    EXPAND = ("requisitionList.workLocation,requisitionList.otherWorkLocations,"
              "requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields")
    FACETS = "WORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS%3BLOCATIONS"
    PAGE  = 200

    def split_title(full_title, fallback_dept=""):
        # "Senior Officer, Office of Student Affairs" → title, dept
        if "," in full_title:
            last = full_title.rfind(",")
            return full_title[:last].strip(), full_title[last + 1:].strip()
        return full_title, fallback_dept or infer_dept_from_title(full_title)

    def html_text(fragment):
        return BeautifulSoup(fragment, "html.parser").get_text("\n", strip=True) if fragment else ""

    jobs = []
    seen = set()

    try:
        offset, total = 0, None
        while total is None or offset < total:
            finder = (f"findReqs;siteNumber=CX_1,facetsList={FACETS},limit={PAGE},"
                      f"{'offset=' + str(offset) + ',' if offset else ''}sortBy=POSTING_DATES_DESC")
            # Built by hand: requests would re-encode the finder's separators
            resp = requests.get(f"{API}?onlyData=true&expand={EXPAND}&finder={finder}",
                                headers={**HEADERS, "Accept": "application/json"}, timeout=30)
            resp.raise_for_status()
            item = (resp.json().get("items") or [{}])[0]
            reqs = item.get("requisitionList") or []
            total = int(item.get("TotalJobsCount") or 0)
            for r in reqs:
                ref = str(r.get("Id") or "").strip()
                full_title = clean(r.get("Title") or "")
                if not ref or not full_title or ref in seen:
                    continue
                seen.add(ref)
                title, dept = split_title(full_title, clean(r.get("Department") or r.get("Organization") or ""))
                desc_text = "\n\n".join(t for t in (
                    html_text(r.get("ShortDescriptionStr")),
                    html_text(r.get("ExternalResponsibilitiesStr")),
                    html_text(r.get("ExternalQualificationsStr")),
                ) if t)
                if not dept:
                    m = re.search(r"sits under (?:the\s+)?([A-Z][^,.]{3,60}?)(?:\s+at our|\s+campus|,|\.|$)", desc_text)
                    dept = m.group(1).strip() if m else ""
                end_date = str(r.get("PostingEndDate") or "")[:10]
                jobs.append({
                    "id":               make_id("HKBU", ref),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKBU",
                    "university_full":  "Hong Kong Baptist University",
                    "department":       dept or "Hong Kong Baptist University",
                    "deadline":         end_date if ISO_DATE.match(end_date) else "",
                    "is_new":           "TRUE",
                    "date_posted":      str(r.get("PostedDate") or "")[:10],
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        f"{SITE}/job/{ref}",
                    "description":      desc_text[:8000] if len(desc_text) > 80 else
                                        f"{title} — {dept or 'HKBU'}. Please visit the application link for full details.",
                })
            if not reqs:
                break
            offset += PAGE
        print(f"  ↳ API: {len(jobs)} of {total} jobs")
    except Exception as e:
        print(f"  ⚠️  Direct API failed ({e}), falling back to Playwright...")
        jobs, seen = [], set()
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(HEADERS)
                page.goto(f"{SITE}/jobs", timeout=60000)
                page.wait_for_timeout(5000)
                prev_height, stale = 0, 0
                for _ in range(60):
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2500)
                    height = page.evaluate("() => document.body.scrollHeight")
                    stale = stale + 1 if height == prev_height else 0
                    if stale >= 3:
                        break
                    prev_height = height
                links = page.evaluate("""() => [...document.querySelectorAll('a[href*="/job/"]')]
                    .map(a => ({href: a.href, title: (a.textContent || '').trim()}))""")
                browser.close()
            for link in links:
                ref_match = re.search(r"/job/(\d+)", link["href"])
                ref = ref_match.group(1) if ref_match else ""
                full_title = clean(link["title"])
                if not ref or len(full_title) < 4 or ref in seen:
                    continue
                seen.add(ref)
                title, dept = split_title(full_title)
                jobs.append({
                    "id":               make_id("HKBU", ref),
                    "title":            title,
                    "rank":             detect_rank(title),
                    "university":       "HKBU",
                    "university_full":  "Hong Kong Baptist University",
                    "department":       dept or "Hong Kong Baptist University",
                    "deadline":         "",
                    "is_new":           "TRUE",
                    "reference":        ref,
                    "position_type":    detect_type(title),
                    "salary":           "",
                    "start_date":       "",
                    "apply_url":        f"{SITE}/job/{ref}",
                    "description":      f"{title}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
                })
            # Descriptions for jobs without a cached summary (usually just today's new ones)
            needs_desc = [j for j in jobs if not _has_good_desc(j["id"])]
            if needs_desc:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    detail_page = browser.new_page()
                    detail_page.set_extra_http_headers(HEADERS)
                    for j in needs_desc:
                        try:
                            detail_page.goto(j["apply_url"], timeout=30000, wait_until="domcontentloaded")
                            detail_page.wait_for_timeout(2500)
                            text = detail_page.inner_text("body")
                            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                            if lines and not any(m in text.lower() for m in BOT_MARKERS):
                                j["description"] = "\n\n".join(lines[:60])[:8000]
                        except Exception:
                            pass
                    browser.close()
        except Exception as e2:
            print(f"  ⚠️  Playwright also failed: {e2}")

    # Keep cached summaries
    for j in jobs:
        if _has_good_desc(j["id"]):
            j["description"] = _existing_descriptions[j["id"]]

    print(f"  ✅ HKBU: {len(jobs)} jobs found")
    return jobs
