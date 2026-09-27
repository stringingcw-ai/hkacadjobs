"""generate_job_pages.py on a temporary copy of the site: stable pages,
closed and moved pages, valid JobPosting data, homepage block, lite CSV."""
import csv
import json
import re
from datetime import timedelta

import pytest

import generate_job_pages as g

FIELDS = ["id", "title", "rank", "university", "university_full", "department", "deadline", "deadline_note",
          "is_new", "date_added", "date_posted", "reference", "position_type", "salary", "start_date",
          "apply_url", "description"]


def row(n, **kw):
    r = {"id": f"HKU-{n}", "title": f"Assistant Professor {n}", "rank": "Assistant Professor", "university": "HKU",
         "university_full": "University of Hong Kong", "department": "Department of Physics",
         "deadline": (g.TODAY + timedelta(days=30)).isoformat(), "deadline_note": "", "is_new": "FALSE",
         "date_added": "2026-09-01", "date_posted": "", "reference": str(n), "position_type": "Full-time",
         "salary": "", "start_date": "", "apply_url": f"https://jobs.hku.hk/{n}",
         "description": "**Duties & Responsibilities**\n• Teach\n\n**Requirements & Qualifications**\n• PhD"}
    r.update(kw)
    return r


@pytest.fixture
def site(tmp_path, monkeypatch):
    for name, path in [("CSV_PATH", "jobs.csv"), ("LITE_CSV", "jobs-lite.csv"), ("INDEX_HTML", "index.html"),
                       ("JOBS_DIR", "jobs"), ("SITEMAP", "sitemap.xml"), ("MANIFEST", "manifest.json")]:
        monkeypatch.setattr(g, name, tmp_path / path)
    (tmp_path / "index.html").write_text(
        "<main><!-- LATEST-JOBS:START (generated) -->\n<!-- LATEST-JOBS:END --></main>", encoding="utf-8")

    def build(rows):
        with open(tmp_path / "jobs.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        g.main()
        return json.loads((tmp_path / "manifest.json").read_text())

    build.dir = tmp_path
    return build


def page(site, d):
    return (site.dir / "jobs" / d / "index.html").read_text(encoding="utf-8")


def json_ld(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">\n(.*?)\n  </script>', html, re.S)]


def test_pages_are_stable_and_closed_jobs_keep_a_page(site):
    rows = [row(n) for n in range(6)]
    site(rows)
    d0 = g.job_dir_name(rows[0])
    before = (site.dir / "jobs" / d0 / "index.html").stat().st_mtime_ns
    m = site(rows)
    assert (site.dir / "jobs" / d0 / "index.html").stat().st_mtime_ns == before   # untouched
    m = site(rows[1:])
    assert m[d0]["status"] == "closed"
    assert 'content="noindex, follow"' in page(site, d0) and "no longer open" in page(site, d0)
    assert d0 not in (site.dir / "sitemap.xml").read_text()


def test_retitled_job_redirects(site):
    rows = [row(n) for n in range(3)]
    site(rows)
    old = g.job_dir_name(rows[0])
    rows[0] = row(0, title="Associate Professor 0")
    m = site(rows)
    assert m[old]["status"] == "moved"
    assert f'url={g.BASE_URL}/jobs/{g.job_dir_name(rows[0])}/' in page(site, old)


def test_closed_pages_expire(site):
    rows = [row(n) for n in range(3)]
    site(rows)
    m = site(rows[1:])
    d0 = g.job_dir_name(rows[0])
    m[d0]["since"] = (g.TODAY - timedelta(days=g.CLOSED_KEEP_DAYS + 1)).isoformat()
    g.MANIFEST.write_text(json.dumps(m))
    m = site(rows[1:])
    assert d0 not in m and not (site.dir / "jobs" / d0).exists()


def test_job_posting_data(site):
    rows = [row(0), row(1, deadline="", deadline_note="Open until filled", salary="HK$50,000 - 60,000 per month",
                        apply_url="javascript:alert(1)", title="<b>Bold</b> job")]
    site(rows)
    ld0 = json_ld(page(site, g.job_dir_name(rows[0])))
    posting = next(x for x in ld0 if x["@type"] == "JobPosting")
    assert posting["validThrough"].endswith("T23:59:59+08:00")
    assert posting["hiringOrganization"]["sameAs"] == "https://www.hku.hk"
    assert "applicantLocationRequirements" not in posting and "baseSalary" not in posting
    assert any(x["@type"] == "BreadcrumbList" for x in ld0)
    html1 = page(site, g.job_dir_name(rows[1]))
    posting1 = next(x for x in json_ld(html1) if x["@type"] == "JobPosting")
    assert "validThrough" not in posting1
    assert posting1["baseSalary"]["value"] == {"@type": "QuantitativeValue", "unitText": "MONTH",
                                               "minValue": 50000, "maxValue": 60000}
    assert "Open until filled" in html1
    assert "javascript:" not in html1 and "<b>Bold</b>" not in html1


def test_homepage_block_and_lite_csv(site):
    site([row(n) for n in range(60)])
    index = (site.dir / "index.html").read_text()
    assert index.count("<li>") == g.LATEST_COUNT and index.count("LATEST-JOBS:START") == 1
    with open(site.dir / "jobs-lite.csv", newline="", encoding="utf-8") as f:
        lite = list(csv.DictReader(f))
    assert len(lite) == 60 and "description" not in lite[0]


@pytest.mark.parametrize("text, value", [
    ("HK$28,380 – HK$36,530 per month", {"minValue": 28380, "maxValue": 36530, "unitText": "MONTH"}),
    ("HKD 45,000 monthly", {"value": 45000, "unitText": "MONTH"}),
    ("HK$1,000,000 per annum", {"value": 1000000, "unitText": "YEAR"}),
    ("Competitive, commensurate with experience", None),
    ("HK$50,000", None),                                               # no pay period
    ("HK$30,000 per month (Lecturer) or HK$40,000 per month", None),   # ambiguous
])
def test_parse_salary(text, value):
    got = g.parse_salary(text)
    assert (got and {k: v for k, v in got["value"].items() if k != "@type"}) == value


def test_related_jobs_are_stable():
    rows = [row(n, department="Physics" if n % 2 else "Chemistry") for n in range(40)]
    by_uni = {"HKU": rows}
    first = g.related_jobs("HKU-3", "HKU", "Physics", by_uni)
    assert len(first) == g.RELATED_COUNT and all(r["department"] == "Physics" for r in first)
    # A new job elsewhere in the list rarely changes an existing page's links
    by_uni["HKU"] = rows + [row(99, department="Chemistry")]
    assert g.related_jobs("HKU-3", "HKU", "Physics", by_uni) == first
