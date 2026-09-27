"""Education University of Hong Kong: job scraper."""

import re

from core import (
    detect_rank, detect_type, HEADERS, infer_dept_from_title, is_active, make_id,
    parse_date_text, _has_good_desc,
)


def scrape_eduhk():
    """
    EdUHK — eduhk.hk/en/current-openings
    JS-rendered. Playwright fetches each page; parser anchors on "Ad Date:".
    """
    print("📋 Scraping EdUHK...")

    BASE = "https://www.eduhk.hk"
    CATEGORIES = [
        ("senior-management",              "Senior Management"),
        ("deanship-headship-appointments", "Deanship/Headship"),
        ("academic-teaching-posts",        "Academic"),
        ("research-support-posts",         "Research"),
    ]

    jobs = []
    seen = set()

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for category, pos_type in CATEGORIES:
                cat_count = 0
                page_num  = 1
                pw_page   = None

                while True:
                    if page_num == 1:
                        url = f"{BASE}/en/current-openings?category={category}&department=&q="
                    # (subsequent pages are reached by clicking Next, not URL param)

                    try:
                        if page_num == 1:
                            pw_page = browser.new_page()
                            pw_page.set_extra_http_headers(HEADERS)
                            pw_page.goto(url, timeout=60000, wait_until="domcontentloaded")
                            pw_page.wait_for_timeout(3000)
                        # else: pw_page already on next page from previous click

                        full_text = pw_page.inner_text("body")
                        # Extract PDF links in page order (one per job card)
                        pdf_links = pw_page.evaluate(
                            "Array.from(document.querySelectorAll('a[href*=\"/cms/f/career\"]')).map(a => a.href)"
                        )
                    except Exception as page_err:
                        print(f"  ↳ {pos_type} p{page_num}: error ({page_err.__class__.__name__})")
                        try: pw_page.close()
                        except: pass
                        break

                    ad_count = full_text.count("Ad Date:")
                    if ad_count == 0:
                        break

                    pdf_idx = 0
                    # Anchor on each "Ad Date:" occurrence.
                    # Grab 400 chars before for title+dept+ref, 200 chars after for close date.
                    for m in re.finditer(r'Ad Date:', full_text):
                        before = full_text[max(0, m.start()-600):m.start()]
                        after  = full_text[m.end():m.end()+200]

                        before_lines = [l.strip() for l in before.splitlines() if l.strip()]

                        # Title and dept: last 2 lines before metadata
                        # Strip lines that look like pagination/nav
                        content_lines = [l for l in before_lines
                                         if not re.match(r'^(Next|Previous|Go to page|Search|Filter|Home|Menu|\d+)$', l, re.I)
                                         and not re.match(r'^Ref:', l)
                                         and len(l) > 2]
                        if not content_lines:
                            continue

                        # Filter out known UI noise
                        NOISE = {"n/a", "na", "reset", "search", "filter", "apply", "clear", "go", "next", "previous"}
                        content_lines = [l for l in content_lines if l.lower() not in NOISE]

                        if not content_lines:
                            continue

                        # Walk backwards: collect dept-like lines, then first non-dept line = title
                        dept_pattern = re.compile(r'^(Department|Faculty|School|Academy|Division|Office|Centre|Center)', re.I)
                        title = ""
                        dept  = ""
                        for line in reversed(content_lines):
                            if dept_pattern.match(line):
                                if not dept:
                                    dept = line   # take innermost dept-like line
                            else:
                                if not title:
                                    title = line
                                    break
                        # Fallback: only dept-like lines found, use last as title
                        if not title:
                            title = dept
                            dept  = ""

                        if not title or len(title) < 3:
                            continue

                        ref_m = re.search(r'Ref:\s*(\d{6,})', before[-150:] + after[:50])
                        ref   = ref_m.group(1) if ref_m else ""
                        key = f"{title}|{ref}" if ref else f"{title}|{dept}"
                        if key in seen:
                            continue
                        seen.add(key)

                        close_m = re.search(r'Close Date[:\s]+([A-Za-z0-9 ]+)', after)
                        deadline = ""
                        if close_m:
                            raw = close_m.group(1).strip()
                            if raw.upper() not in ("N/A", "NA", ""):
                                deadline = parse_date_text(raw)

                        # Ad Date immediately follows the "Ad Date:" anchor
                        ad_raw = full_text[m.end():m.end()+30].strip().splitlines()[0].strip()
                        date_posted = parse_date_text(ad_raw) if ad_raw else ""

                        apply_url = pdf_links[pdf_idx] if pdf_idx < len(pdf_links) else f"{BASE}/en/current-openings?category={category}&department=&q="
                        pdf_idx += 1
                        jobs.append({
                            "id":               make_id("EDUHK", ref if ref else f"{title[:40]}_{dept[:20]}"),
                            "title":            title,
                            "rank":             detect_rank(title),
                            "university":       "EdUHK",
                            "university_full":  "Education University of Hong Kong",
                            "department":       dept or infer_dept_from_title(title) or "Education University of Hong Kong",
                            "deadline":         deadline,
                            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
                            "date_posted":      date_posted,
                            "reference":        ref,
                            "position_type":    detect_type(title),
                            "salary":           "",
                            "start_date":       "",
                            "apply_url":        apply_url,
                            "description":      "",
                        })
                        cat_count += 1

                    # Try clicking Next button for next page
                    try:
                        next_btn = pw_page.query_selector("a:has-text('Next'), button:has-text('Next'), [aria-label='Next']")
                        if next_btn and ad_count > 0 and page_num < 20:
                            next_btn.click()
                            pw_page.wait_for_timeout(3000)
                            page_num += 1
                        else:
                            pw_page.close()
                            break
                    except Exception:
                        try: pw_page.close()
                        except: pass
                        break

                print(f"  ↳ {pos_type}: {cat_count} jobs ({page_num} page(s))")

            browser.close()

    except Exception as e:
        print(f"  ⚠️  Playwright failed: {e}")
        import traceback; traceback.print_exc()

    # Fetch descriptions from PDF job ads (EdUHK only uses PDFs, no HTML detail pages)
    # EdUHK's server requires legacy SSL renegotiation — use urllib with a permissive context.
    needs_desc = [j for j in jobs if not _has_good_desc(j["id"]) and j.get("apply_url", "").endswith(".pdf")]
    if needs_desc:
        import ssl, urllib.request, io
        try:
            from pypdf import PdfReader
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            ssl_ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
            PREAMBLE_END = "in support of its strategic development in diverse areas."
            found_pdf = 0
            print(f"  ↳ Fetching {len(needs_desc)} PDF descriptions...")
            for j in needs_desc:
                try:
                    req = urllib.request.Request(j["apply_url"], headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
                        data = resp.read()
                    reader = PdfReader(io.BytesIO(data))
                    text = "\n".join(page.extract_text() or "" for page in reader.pages)
                    # Skip the standard EdUHK university preamble if present
                    idx = text.find(PREAMBLE_END)
                    body = text[idx + len(PREAMBLE_END):].strip() if idx >= 0 else text.strip()
                    # Take meaningful lines (>50 chars), skip trailing boilerplate
                    lines = []
                    for ln in body.splitlines():
                        ln = ln.strip()
                        if not ln:
                            continue
                        if re.match(r'^(Salary will be|The University only accepts|Applicants should complete|For enquiries|Further information)', ln, re.I):
                            break
                        if len(ln) > 50:
                            lines.append(ln)
                    if lines:
                        j["description"] = "\n\n".join(lines[:60])[:8000]
                        found_pdf += 1
                except Exception:
                    pass
            print(f"  ↳ PDF descriptions: {found_pdf}/{len(needs_desc)} extracted")
        except ImportError:
            print("  ⚠️  pypdf not installed — skipping EdUHK PDF extraction")

    print(f"  ✅ EdUHK: {len(jobs)} jobs found")
    return jobs
