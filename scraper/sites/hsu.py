"""Hang Seng University of Hong Kong: job scraper."""

import re

from core import clean, detect_rank, detect_type, get_soup, make_id, parse_date_text


def scrape_hsu():
    """
    HSU — Hang Seng University of Hong Kong
    Static WordPress listing at hsu.edu.hk/en/job-opportunities/
    Links out to recruit.hsu.edu.hk/opening/content.php?id=XXXX
    Title format: "Department - Job Title" — split on first ' - ' or ' – '
    Deadline fetched from detail page: "apply on or before DD Month YYYY"
    """
    print("📋 Scraping HSU...")

    LISTING_URL = "https://www.hsu.edu.hk/en/job-opportunities/"
    jobs = []
    seen = set()

    try:
        soup = get_soup(LISTING_URL)
        if not soup:
            print("  ⚠️  Could not fetch HSU listing page")
            return jobs

        job_links = [a for a in soup.find_all("a", href=True)
                     if "recruit.hsu.edu.hk/opening/content.php" in a["href"]]

        for a in job_links:
            full_text = clean(a.get_text())
            if not full_text:
                continue
            apply_url = a["href"]
            ref_m = re.search(r"id=(\d+)", apply_url)
            ref   = ref_m.group(1) if ref_m else ""

            if ref in seen:
                continue
            seen.add(ref or full_text)

            # Split "Department - Title" on first dash separator
            sep = " – " if " – " in full_text else " - "
            parts = full_text.split(sep, 1)
            dept  = parts[0].strip() if len(parts) > 1 else ""
            title = parts[1].strip() if len(parts) > 1 else full_text

            # Fetch detail page for deadline and description
            deadline = ""
            desc_text = ""
            detail_soup = get_soup(apply_url)
            if detail_soup:
                body = detail_soup.get_text()
                m = re.search(r'(?:on or before|by|before)\s+(\d{1,2}\s+\w+\s+202\d)', body, re.I)
                if m:
                    deadline = parse_date_text(m.group(1))
                for tag in detail_soup.find_all(["nav", "header", "footer", "script", "style"]):
                    tag.decompose()
                candidates = [
                    clean(tag.get_text(" "))
                    for tag in detail_soup.find_all(["div", "section", "article", "main"])
                    if 150 < len(clean(tag.get_text(" "))) < 5000
                ]
                if candidates:
                    desc_text = max(candidates, key=len)[:8000]

            jobs.append({
                "id":               make_id("HSU", ref or title[:25]),
                "title":            title,
                "rank":             detect_rank(title),
                "university":       "HSU",
                "university_full":  "Hang Seng University of Hong Kong",
                "department":       dept or "Hang Seng University of Hong Kong",
                "deadline":         deadline,
                "is_new":           "TRUE",
                "reference":        ref,
                "position_type":    detect_type(title),
                "salary":           "",
                "start_date":       "",
                "apply_url":        apply_url,
                "description":      desc_text or f"{title} — {dept}. Please visit the application link for full details.",
            })

    except Exception as e:
        print(f"  ⚠️  HSU scraper failed: {e}")

    print(f"  ✅ HSU: {len(jobs)} jobs found")
    return jobs
