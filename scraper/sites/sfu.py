"""Saint Francis University: job scraper."""

import re

from core import clean, detect_rank, detect_type, get_soup, make_id, text_fragment_url


def scrape_sfu():
    """
    SFU — Saint Francis University (sfu.edu.hk)
    Four static pages: senior-management, deanship-headship, academic-teaching, research-project
    Each job is in <div class="accordion-wrap">
    Title in <a class="accordion-btn"> — includes "(Ref.: XX/XXX/DEPT)"
    Dept extracted by splitting title on last ", " before a school/office keyword
    Deadline in accordion-content as "Deadline\n<date or 'Until the Position is Filled'>"
    """
    print("📋 Scraping SFU...")

    SECTIONS = [
        ("https://www.sfu.edu.hk/en/career/senior-management-positions/index.html",  "Senior Management"),
        ("https://www.sfu.edu.hk/en/career/deanship-headship-positions/index.html",  "Deanship/Headship"),
        ("https://www.sfu.edu.hk/en/career/academic-teaching-positions/index.html",  "Academic/Teaching"),
        ("https://www.sfu.edu.hk/en/career/research-project-positions/index.html",   "Research/Project"),
    ]
    DEPT_KEYWORDS = re.compile(r'\b(School|Department|Office|Centre|Center|Graduate|Faculty|Institute|Registry|Library)\b', re.I)

    jobs = []
    seen = set()

    for url, section_name in SECTIONS:
        soup = get_soup(url)
        if not soup:
            print(f"  ⚠️  Could not fetch {section_name}")
            continue

        accordions = soup.find_all("div", class_="accordion-wrap")
        sect_count = 0

        for acc in accordions:
            btn = acc.find("a", class_="accordion-btn")
            if not btn:
                continue
            title_raw = clean(btn.get_text())

            # Extract ref
            ref_m = re.search(r'Ref\.:\s*([^\)]+)\)', title_raw)
            ref   = ref_m.group(1).strip() if ref_m else ""

            dedup_key = ref if ref else title_raw
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Strip ref from title
            title_clean = re.sub(r'\s*\(Ref\.[^\)]*\)', '', title_raw).strip()

            # Split dept from title on last ", " if right side looks like a dept/school
            dept = ""
            last_comma = title_clean.rfind(", ")
            if last_comma >= 0:
                right = title_clean[last_comma + 2:]
                if DEPT_KEYWORDS.search(right):
                    dept  = right.strip()
                    title_clean = title_clean[:last_comma].strip()

            # Extract deadline and description from accordion content
            content = acc.find("div", class_="accordion-content")
            deadline = ""
            desc_text = ""
            if content:
                # The line after "Deadline": a date or "Until the Position is Filled"
                # (normalise_deadline() turns the latter into a deadline note)
                lines = [l.strip() for l in content.get_text("\n").splitlines() if l.strip()]
                for i, line in enumerate(lines[:-1]):
                    if re.fullmatch(r"Deadline:?", line, re.I):
                        deadline = lines[i + 1]
                        break
                parts = []
                for p in content.find_all(["p", "li"]):
                    t = clean(p.get_text(" "))
                    if t and len(t) > 20 and not re.match(r'Deadline|Until the Position', t, re.I):
                        parts.append(t)
                if parts:
                    desc_text = "\n\n".join(parts)[:8000]

            jobs.append({
                "id":               make_id("SFU", ref or title_clean[:25]),
                "title":            title_clean,
                "rank":             detect_rank(title_clean),
                "university":       "SFU",
                "university_full":  "Saint Francis University",
                "department":       dept or "Saint Francis University",
                "deadline":         deadline,
                "is_new":           "TRUE",
                "reference":        ref,
                "position_type":    detect_type(title_clean),
                "salary":           "",
                "start_date":       "",
                "apply_url":        text_fragment_url(url, title_clean),
                "description":      desc_text or f"{title_clean}{' — ' + dept if dept else ''}. Please visit the application link for full details.",
            })
            sect_count += 1

        print(f"  ↳ {section_name}: {sect_count} jobs")

    print(f"  ✅ SFU: {len(jobs)} jobs found")
    return jobs
