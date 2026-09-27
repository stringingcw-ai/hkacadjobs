"""Hong Kong Chu Hai College: job scraper."""

import re

from bs4 import BeautifulSoup

from core import (
    clean, detect_rank, detect_type, HEADERS, is_active, make_id, parse_date_text,
    text_fragment_url,
)


# MAIN
# ══════════════════════════════════════════════════════════════════

def scrape_chuhai():
    """
    Hong Kong Chu Hai College — chuhai.edu.hk/en/page/jobs
    Four category pages; each loads its job list from a JSON API that requires
    JS-generated session cookies. Playwright intercepts the API responses.
    All jobs in a category are returned as one HTML blob (accordion widgets);
    BeautifulSoup extracts individual jobs from that blob.
    """
    print("📋 Scraping Chu Hai...")

    GROUPS = {
        "3feba8ec-0307-4709-8c72-bc7c316e63f3": "Research / Project",
        "cd303cce-dd3e-484d-ba93-a956d2d4c15d": "Administrative",
        "b9f07df8-bc36-430a-91ea-b8f196e36f18": "Academic",
        "e80af52a-59d4-40ae-ab0b-cbb879e41a02": "Management",
    }

    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers(HEADERS)

            api_responses = {}

            def capture(response):
                if "api/special/careers" in response.url:
                    try:
                        api_responses[response.url] = response.json()
                    except Exception:
                        pass

            page.on("response", capture)

            for gid in GROUPS:
                page.goto(f"https://www.chuhai.edu.hk/en/page/jobs?id={gid}",
                          timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(1000)

            browser.close()

        for url, data in api_responses.items():
            if data.get("code") != 200:
                continue
            gid = url.split("groupId=")[-1]
            pos_type = GROUPS.get(gid, "")
            content_html = (data.get("data") or {}).get("content", {}).get("article_content", "")
            if not content_html:
                continue

            soup = BeautifulSoup(content_html, "html.parser")
            apply_url = f"https://www.chuhai.edu.hk/en/page/jobs?id={gid}"

            # Default dept to category name; overridden by <h3> headers for Research group
            current_dept = pos_type
            for el in soup.children:
                if not hasattr(el, "name") or not el.name:
                    continue
                # Department headers are top-level <h3> tags outside accordion widgets
                if el.name == "h3":
                    text = el.get_text(strip=True)
                    if text and not re.search(r'no job opening', text, re.I):
                        current_dept = text
                    continue
                if el.name != "div" or "accordion-wrapper" not in el.get("class", []):
                    continue

                # Title from accordion header h3
                title_el = el.select_one(".accordion-title h3, .accordion-header h3")
                title = clean(title_el.get_text()) if title_el else ""
                if not title or len(title) < 3:
                    continue

                key = f"{title}|{current_dept}"
                if key in seen:
                    continue
                seen.add(key)

                body = el.select_one(".accordion-body")
                desc_text = ""
                deadline = ""

                if body:
                    # Try table format first (Research jobs), fall back to paragraph text
                    rows = body.find_all("tr")
                    if rows:
                        parts = []
                        for row in rows:
                            cells = row.find_all("td")
                            if len(cells) == 2:
                                label = cells[0].get_text(strip=True)
                                val   = cells[1].get_text(separator=" ", strip=True)
                                if label and val:
                                    parts.append(f"{label} {val}")
                                elif val:
                                    parts.append(val)
                            elif len(cells) == 1:
                                val = cells[0].get_text(separator=" ", strip=True)
                                if val:
                                    parts.append(val)
                        desc_text = "\n".join(p for p in parts if len(p) > 10)[:8000]
                    else:
                        # Paragraph-based format (Academic / Management)
                        lines = [p.get_text(separator=" ", strip=True)
                                 for p in body.find_all("p") if p.get_text(strip=True)]
                        desc_text = "\n".join(ln for ln in lines if len(ln) > 20)[:8000]

                    # Closing date from "Closing Date:" table cell
                    for td in body.find_all("td"):
                        if re.search(r'closing date', td.get_text(), re.I):
                            sibling = td.find_next_sibling("td")
                            if sibling:
                                raw = sibling.get_text(strip=True)
                                if raw and not re.search(r'until.*filled|invitation|not to fill', raw, re.I):
                                    deadline = parse_date_text(raw)
                            break

                # Reference number
                ref = ""
                ref_m = re.search(r'(?:Ref(?:erence)?\.?\s*(?:No\.?)?|ref\s*no\.?)[:\s]+([A-Za-z0-9/_\-\.]+)',
                                   desc_text, re.I)
                if ref_m:
                    ref = ref_m.group(1).strip()

                jobs.append({
                    "id":              make_id("HKCHC", ref or f"{title[:40]}_{current_dept[:20]}"),
                    "title":           title,
                    "rank":            detect_rank(title),
                    "university":      "HKCHC",
                    "university_full": "Hong Kong Chu Hai College",
                    "department":      current_dept,
                    "deadline":        deadline,
                    "is_new":          "TRUE" if is_active(deadline) else "FALSE",
                    "reference":       ref,
                    "position_type":   detect_type(title),
                    "salary":          "",
                    "start_date":      "",
                    "apply_url":       text_fragment_url(apply_url, title),
                    "description":     desc_text,
                })

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")
        import traceback; traceback.print_exc()

    print(f"  ✅ Chu Hai: {len(jobs)} jobs found")
    return jobs
