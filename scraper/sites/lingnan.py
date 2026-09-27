"""Lingnan University: job scraper."""

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from core import (
    clean, detect_rank, detect_type, HEADERS, make_id, PLACEHOLDER_MARKER,
    _existing_descriptions, _has_good_desc,
)


def scrape_lingnan():
    """
    Lingnan — lingnan.csod.com (Cornerstone OnDemand ATS)
    The career site lists jobs through a JSON search API
    (uk.api.csod.com/rec-job-search/external/jobs) using a token issued to the
    page. Replaying that request with pageSize=200 returns every job at once;
    falls back to clicking through the result pages. Department comes from the
    title (text after the last comma).
    """
    print("📋 Scraping Lingnan...")
    SITE = "https://lingnan.csod.com/ux/ats/careersite/4/home"

    def make_job(ref, full_title, posted="", expires="", desc_html=""):
        # "Senior HR Officer, Human Resources Office" → title, dept
        if "," in full_title:
            last_comma = full_title.rfind(",")
            title, dept = full_title[:last_comma].strip(), full_title[last_comma + 1:].strip()
        else:
            title, dept = full_title, "Lingnan University"
        desc = BeautifulSoup(desc_html or "", "html.parser").get_text("\n", strip=True)
        if len(desc) < 300 or "INTERNAL JOB DESCRIPTION" in desc.upper():
            desc = f"{title} — {dept}. Please visit the application link for full details."
        return {
            "id":               make_id("LU", ref or title[:25]),
            "title":            title,
            "rank":             detect_rank(title),
            "university":       "LU",
            "university_full":  "Lingnan University",
            "department":       dept,
            "deadline":         expires,
            "is_new":           "TRUE",
            "date_posted":      posted,
            "reference":        ref,
            "position_type":    detect_type(title),
            "salary":           "",
            "start_date":       "",
            "apply_url":        f"{SITE}/requisition/{ref}?c=lingnan",
            "description":      desc[:8000],
        }

    def us_date(text):
        # CSOD dates are M/D/YYYY ("9/25/2026"); "-" means none
        try:
            return datetime.strptime(clean(text), "%m/%d/%Y").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return ""

    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)
            searches = []
            page.on("request", lambda r: searches.append(r) if "rec-job-search" in r.url and r.method == "POST" else None)
            page.goto(f"{SITE}?c=lingnan", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)

            # 1) Replay the page's own search request asking for every job
            if searches:
                try:
                    req = searches[0]
                    payload = json.loads(req.post_data or "{}")
                    payload["pageNumber"], payload["pageSize"] = 1, 200
                    keep = ("authorization", "content-type", "csod-accept-language", "accept")
                    resp = page.request.post(req.url, data=json.dumps(payload),
                                             headers={k: v for k, v in req.headers.items() if k.lower() in keep})
                    data = (resp.json() or {}).get("data") or {}
                    for r in data.get("requisitions") or []:
                        ref = str(r.get("requisitionId") or "")
                        full_title = clean(r.get("displayJobTitle") or "")
                        if not ref or len(full_title) < 5 or ref in seen:
                            continue
                        seen.add(ref)
                        jobs.append(make_job(ref, full_title, us_date(r.get("postingEffectiveDate")),
                                             us_date(r.get("postingExpirationDate")), r.get("externalDescription")))
                    print(f"  ↳ Search API: {len(jobs)} of {data.get('totalCount')} jobs")
                except Exception as e:
                    print(f"  ⚠️  Search API replay failed ({e}); paging through results instead")

            # 2) Fallback: click through the result pages, waiting for each to change
            if not jobs:
                page_num = 1
                while page_num <= 20:
                    for a in BeautifulSoup(page.content(), "html.parser").find_all("a", href=re.compile(r"requisition", re.I)):
                        ref_match = re.search(r"requisition/(\d+)", a.get("href", ""))
                        ref = ref_match.group(1) if ref_match else ""
                        full_title = clean(a.get_text())
                        if not ref or len(full_title) < 5 or ref in seen:
                            continue
                        seen.add(ref)
                        jobs.append(make_job(ref, full_title))
                    first = page.evaluate("() => document.querySelector('a[href*=requisition]')?.getAttribute('href')")
                    clicked = page.evaluate(f"""() => {{
                        const btn = [...document.querySelectorAll('[class*="paginat"] a, [class*="paginat"] button, nav a, nav button')]
                            .find(b => parseInt(b.textContent.trim()) === {page_num + 1})
                            || document.querySelector('[aria-label="Next"]:not([disabled]), [title="Next"]:not([disabled])');
                        if (btn) {{ btn.click(); return true; }}
                        return false;
                    }}""")
                    if not clicked:
                        break
                    try:
                        page.wait_for_function(
                            "f => document.querySelector('a[href*=requisition]')?.getAttribute('href') !== f",
                            arg=first, timeout=15000)
                    except Exception:
                        print(f"  ⚠️  Page {page_num + 1} didn't load")
                        break
                    page_num += 1

            # Fetch detail pages for descriptions (skip known good summaries)
            to_fetch = [j for j in jobs if not _has_good_desc(j["id"]) and PLACEHOLDER_MARKER in j["description"]]
            if to_fetch:
                print(f"  ↳ Fetching {len(to_fetch)} detail pages for descriptions...")
                found = 0
                for j in to_fetch:
                    try:
                        page.goto(j["apply_url"], timeout=30000, wait_until="networkidle")
                        page.wait_for_timeout(1500)
                        text = page.inner_text("body")
                        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
                        if lines:
                            j["description"] = "\n\n".join(lines[:60])[:8000]
                            found += 1
                    except Exception:
                        pass
                print(f"  ↳ Got descriptions for {found}/{len(to_fetch)} jobs")
            # Restore cached summaries for skipped jobs
            for j in jobs:
                if _has_good_desc(j["id"]):
                    j["description"] = _existing_descriptions[j["id"]]
            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")

    print(f"  ✅ Lingnan: {len(jobs)} jobs found")
    return jobs
