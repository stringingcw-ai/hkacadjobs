"""Technological and Higher Education Institute of Hong Kong: job scraper."""

import re

from bs4 import BeautifulSoup

from core import (
    clean, detect_rank, detect_type, HEADERS, is_active, make_id, parse_date_text, TODAY,
)


def scrape_thei():
    """
    THEi — thei.edu.hk/career-opportunities/ (WordPress + Elementor loop grids)
    Two grids (Teaching & Academic, Administrative & General), 8 cards a page.
    Each grid pages server-side via ?e-page-<grid id>=N; the next page's URL is
    in the grid's .e-load-more-anchor[data-next-page] (the site fetches it on
    scroll). Following those URLs needs no scrolling or button clicks — the
    click-to-load-more button the old code relied on was removed in Aug 2026.
    """
    print("📋 Scraping THEi...")
    LISTING_URL = "https://thei.edu.hk/career-opportunities/"
    MAX_LISTING_PAGES = 20

    jobs = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_extra_http_headers(HEADERS)

            def open_listing(url, attempts=3):
                """A listing page can abort now and then (net::ERR_ABORTED);
                retry, and skip only that page if it keeps failing."""
                for attempt in range(1, attempts + 1):
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        return True
                    except Exception as e:
                        print(f"  ⚠️  THEi: {url} failed (attempt {attempt}/{attempts}): {str(e).splitlines()[0]}")
                        page.wait_for_timeout(5000 * attempt)
                return False

            cards_data = []
            seen_urls = set()
            queue, visited = [LISTING_URL], set()
            while queue and len(visited) < MAX_LISTING_PAGES:
                listing_url = queue.pop(0)
                if listing_url in visited:
                    continue
                visited.add(listing_url)
                if not open_listing(listing_url):
                    continue
                try:
                    page.wait_for_selector(".e-loop-item", timeout=30000)
                except Exception:
                    print(f"  ⚠️  THEi: no job cards on {listing_url}")
                    continue
                soup = BeautifulSoup(page.content(), "html.parser")
                for anchor in soup.select(".e-load-more-anchor[data-next-page]"):
                    try:
                        current, last = int(anchor.get("data-page") or 1), int(anchor.get("data-max-page") or 1)
                    except ValueError:
                        continue
                    next_url = anchor["data-next-page"]
                    if current < last and next_url not in visited:
                        queue.append(next_url)
                cards_data.extend(_parse_thei_cards(soup, seen_urls))
            print(f"  ↳ {len(cards_data)} job cards from {len(visited)} listing page(s)")

            # Fetch detail pages for ref + description
            used_ids = set()
            for card in cards_data:
                try:
                    page.goto(card["url"], wait_until="domcontentloaded", timeout=45000)
                    try:
                        page.wait_for_selector(".elementor-widget-text-editor", timeout=15000)
                    except Exception:
                        pass
                    detail_soup = BeautifulSoup(page.content(), "html.parser")

                    text_parts = []
                    for widget in detail_soup.find_all(
                        "div", class_=lambda c: c and "elementor-widget-text-editor" in c
                    ):
                        t = widget.get_text(separator="\n", strip=True)
                        if len(t) > 80:
                            text_parts.append(t)
                    full_text = "\n\n".join(text_parts)

                    # Extract ref no. The page often splits it across elements
                    # ("FO ⏎ /AS ⏎ /03/26"), so read up to the next heading and
                    # drop the line breaks; otherwise fall back to one line.
                    ref = ""
                    ref_m = re.search(
                        r"Ref(?:erence)?\.?\s*No\.?\s*[:：]\s*(.{1,80}?)\s*"
                        r"(?=Major Duties|Employment Period|Duties|Responsibilities|$)",
                        full_text, re.I | re.S,
                    ) or re.search(
                        r"Ref(?:erence)?\.?\s*No\.?\s*[:\s]+([A-Za-z0-9/_\-\.\(\)]+)",
                        full_text, re.I,
                    )
                    if ref_m:
                        ref = re.sub(r"\s+", "", ref_m.group(1)).rstrip(".")

                    job_id = make_id("THEI", ref or card["title"])
                    if job_id in used_ids:
                        # Never let two postings share an id (one would be dropped)
                        job_id = make_id("THEI", card["url"].rstrip("/").rsplit("/", 1)[-1])
                    used_ids.add(job_id)

                    jobs.append({
                        "id":              job_id,
                        "title":           card["title"],
                        "rank":            detect_rank(card["title"]),
                        "university":      "THEI",
                        "university_full": "Technological and Higher Education Institute of Hong Kong",
                        "department":      card["dept"],
                        "deadline":        card["deadline"],
                        "is_new":          "TRUE" if is_active(card["deadline"]) else "FALSE",
                        "date_added":      TODAY.strftime("%Y-%m-%d"),
                        "reference":       ref,
                        "position_type":   detect_type(card["title"]),
                        "salary":          "",
                        "start_date":      "",
                        "apply_url":       card["url"],
                        "description":     full_text[:8000],
                    })
                except Exception as e:
                    print(f"  ⚠️  Error fetching {card['url']}: {e}")

            browser.close()

    except Exception as e:
        print(f"  ⚠️  THEi scraper failed: {e}")
        import traceback; traceback.print_exc()

    print(f"  ✅ THEi: {len(jobs)} jobs found")
    return jobs


def _parse_thei_cards(soup, seen_urls):
    """Job cards (title, detail URL, department, closing date) on one THEi listing page."""
    cards_data = []
    for card in soup.find_all("div", class_=lambda c: c and "e-loop-item" in c):
        # Find job URL: first <a> linking to a single-slug thei.edu.hk page
        href = ""
        for a in card.find_all("a", href=True):
            h = a["href"]
            path = h.replace("https://thei.edu.hk/", "").rstrip("/")
            if path and "/" not in path:
                href = h
                break
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        # Title: first <a> with non-empty text, or fall back to any text in card heading
        title = ""
        for a in card.find_all("a", href=True):
            t = clean(a.get_text())
            if t:
                title = t
                break
        if not title:
            # Some cards wrap title in a span inside job-career div
            jc = card.find("div", class_="job-career")
            if jc:
                title = clean(jc.get_text())
        if not title:
            continue

        # Card text parts: title | department | closing_date_text | More Details
        parts = [p.strip() for p in card.get_text(separator="|", strip=True).split("|") if p.strip()]
        dept = parts[1] if len(parts) > 1 else ""
        date_text = parts[2] if len(parts) > 2 else ""

        # Parse closing date — skip "Review of applications..." text
        deadline = ""
        if re.search(r"\d{1,2}\s+\w+\s+\d{4}", date_text):
            m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", date_text)
            if m:
                deadline = parse_date_text(m.group(1))

        cards_data.append({
            "title": title,
            "url": href,
            "dept": dept,
            "deadline": deadline,
        })
    return cards_data
