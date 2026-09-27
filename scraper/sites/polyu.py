"""Hong Kong Polytechnic University: job scraper."""

import re

from core import (
    clean, detect_rank, detect_type, get_soup, is_active, is_within_retention, make_id,
    parse_date_text,
)


def scrape_polyu_detail(ref, debug=False):
    """
    Fetch a PolyU job detail page and extract the description and posting date.
    URL: https://jobs.polyu.edu.hk/job_detail.php?job={ref}
    Returns (description: str, date_posted: str) — either may be "" on failure.
    """
    url = f"https://jobs.polyu.edu.hk/job_detail.php?job={ref}"
    soup = get_soup(url, timeout=10)
    if not soup:
        return "", ""

    # Remove noise
    for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()

    if debug:
        print(f"\n  🔍 DEBUG {url}")
        for tag in soup.find_all(["div", "td", "table", "p"], limit=40):
            cls = tag.get("class", "")
            idd = tag.get("id", "")
            t   = clean(tag.get_text(" "))[:100]
            if t:
                print(f"    <{tag.name} class={cls} id={idd}>: {t}")
        return "", ""

    # Extract posting date — "Posting date: DD Month YYYY" appears in page body
    page_text = soup.get_text("\n")
    date_posted = ""
    pd_m = re.search(r"Posting date[:\s]+([A-Za-z0-9 ]+)", page_text, re.I)
    if pd_m:
        date_posted = parse_date_text(pd_m.group(1).strip())

    # PolyU job descriptions live in div.ITS_Content_RichTextEditor
    content = soup.find("div", class_="ITS_Content_RichTextEditor")
    if content:
        seen = set()
        parts = []
        for p in content.find_all("p"):
            t = clean(p.get_text(" "))
            # Normalise whitespace for dedup comparison
            key = re.sub(r"\s+", " ", t).lower()
            if t and key not in seen:
                seen.add(key)
                parts.append(t)
        if parts:
            return "\n\n".join(parts)[:8000], date_posted

    # Fallback: largest text block
    candidates = [
        clean(tag.get_text(" "))
        for tag in soup.find_all(["div", "td", "section"])
        if 150 < len(clean(tag.get_text(" "))) < 5000
    ]
    if candidates:
        return max(candidates, key=len)[:8000], date_posted

    return "", date_posted


def scrape_polyu_page(url, position_type_override=None):
    """
    Scrape one PolyU jobs listing page (table format).
    Column layout across pages:
      Col 0: Department/Unit
      Col 1: Position (always the job title)
      Col 2: Project Title (research.php only — extra column)
      Col 2/3: Closing Date
      Col 3/4: Ref No.
    """
    soup = get_soup(url)
    if not soup:
        return []

    jobs = []
    table = soup.find("table")
    if not table:
        return []

    for row in table.find_all("tr")[1:]:  # skip header row
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        texts = [clean(col.get_text()) for col in cols]

        # Ref is always a 7-10 digit number
        ref = ""
        for t in texts:
            if re.match(r"^\d{7,10}$", t.replace(" ", "")):
                ref = t.replace(" ", "")
                break
        if not ref:
            continue

        dept  = texts[0]
        title = re.sub(r"\s+", " ", texts[1])  # always col 1 = Position

        # Project title: present only on research.php (5 cols)
        # It sits in col 2 when there are 5+ cols and col 2 isn't a date or ref
        project_title = ""
        if len(cols) >= 5:
            candidate = texts[2]
            if candidate and candidate != ref and not re.search(r"\d{4}", candidate):
                project_title = candidate

        # Deadline: first cell that parses as a date
        deadline = ""
        for t in texts:
            parsed = parse_date_text(t)
            if parsed and parsed != t:
                deadline = parsed
                break

        if not title:
            continue

        description = title
        if project_title:
            description += f" — Project: {project_title}"
        description += f" ({dept}). See application link for full details."

        jobs.append({
            "ref":         ref,
            "title":       title,
            "dept":        dept,
            "deadline":    deadline,
            "pos_type":    position_type_override or detect_type(title),
            "description": description,
        })

    return jobs


def scrape_polyu():
    """
    PolyU — scrapes all 5 job listing pages, then fetches each detail page
    for the full job description.

    Pages:
      Central & Senior Management  → central_senior.php
      Deans & Heads                → deans_heads.php
      Academic / Teaching          → academic.php
      Research Assistant Professor → rap.php
      Research / Project Posts     → research.php
    """
    print("📋 Scraping PolyU...")

    base = "https://jobs.polyu.edu.hk"
    pages = [
        (f"{base}/central_senior.php", "Full-time"),
        (f"{base}/deans_heads.php",    "Full-time"),
        (f"{base}/academic.php",       "Full-time"),
        (f"{base}/rap.php",            "Full-time"),
        (f"{base}/research.php",       "Full-time"),
    ]

    # Step 1: collect all jobs from all listing pages
    raw_jobs = []
    seen_refs = set()
    for url, pos_type in pages:
        page_jobs = scrape_polyu_page(url, pos_type)
        for j in page_jobs:
            if j["ref"] not in seen_refs:
                seen_refs.add(j["ref"])
                raw_jobs.append(j)

    print(f"  ↳ Found {len(raw_jobs)} listings across all pages")

    # Step 2: fetch detail pages only for jobs within the retention window
    active_jobs = [j for j in raw_jobs if is_within_retention(j["deadline"])]
    skipped = len(raw_jobs) - len(active_jobs)
    print(f"  ↳ Fetching detail pages for {len(active_jobs)} jobs (skipped {skipped} expired)...")
    jobs = []
    for idx, j in enumerate(active_jobs, 1):
        ref      = j["ref"]
        title    = j["title"]
        dept     = j["dept"]
        deadline = j["deadline"]

        apply_url                = f"{base}/job_detail.php?job={ref}"
        description, date_posted = scrape_polyu_detail(ref)
        if not description:
            description = j.get("description") or f"{title} — {dept}. See {apply_url} for full details."

        if idx % 10 == 0 or idx == len(active_jobs):
            print(f"  ↳ {idx}/{len(active_jobs)} detail pages fetched")

        jobs.append({
            "id":               make_id("POLYU", ref),
            "title":            title,
            "rank":             detect_rank(title),
            "university":       "PolyU",
            "university_full":  "Hong Kong Polytechnic University",
            "department":       dept,
            "deadline":         deadline,
            "is_new":           "TRUE" if is_active(deadline) else "FALSE",
            "date_posted":      date_posted,
            "reference":        ref,
            "position_type":    j["pos_type"],
            "salary":           "",
            "start_date":       "",
            "apply_url":        apply_url,
            "description":      description,
        })

    print(f"  ✅ PolyU: {len(jobs)} jobs found")
    return jobs
