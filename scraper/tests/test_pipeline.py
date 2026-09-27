"""End-to-end runs of scraper.main() with fake institution scrapers, over
several simulated days: NEW flags, date_added, fallbacks on failures, the job
registry, deadline normalisation and summary caching."""
import csv
import json
import sys
from datetime import date, timedelta

import pytest

import core
import scraper

DAY1 = date(2026, 9, 1)
LONG_TEXT = "Duties include teaching and research. " * 20
SUMMARY = ("**Duties & Responsibilities**\n• Teach undergraduate courses\n\n"
           "**Requirements & Qualifications**\n• A PhD in a relevant field\n\n"
           "**Appointment**\n• Full-time\n\n**Key Dates**\n• Not specified")


def job(uni, n, **kw):
    j = {"id": f"{uni}-{n}", "title": f"Assistant Professor {n}", "rank": "", "university": uni,
         "university_full": uni, "department": "Department of Physics", "deadline": "2026-12-31",
         "date_posted": "", "reference": str(n), "position_type": "Full-time", "salary": "",
         "start_date": "", "apply_url": f"https://example.org/{uni}/{n}", "description": LONG_TEXT}
    j.update(kw)
    return j


def hku(*ns, **kw):
    return [job("HKU", n, **kw) for n in ns]


@pytest.fixture
def run(tmp_path, monkeypatch):
    out = tmp_path / "jobs.csv"
    monkeypatch.setattr(scraper, "OUTPUT_FILE", out)
    monkeypatch.setattr(scraper, "REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(scraper, "HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    summarised = []

    def fake_summarise(jobs):
        for j in jobs:
            summarised.append(j["id"])
            j["description"] = SUMMARY

    monkeypatch.setattr(scraper, "summarise_jobs", fake_summarise)

    def _run(day, results, argv=()):
        d = DAY1 + timedelta(days=day - 1)
        monkeypatch.setattr(scraper, "TODAY", d)
        monkeypatch.setattr(core, "TODAY", d)

        def make(name):
            def scrape():
                r = results[name]
                if isinstance(r, Exception):
                    raise r
                return [dict(x) for x in r]
            return scrape

        monkeypatch.setattr(scraper, "SCRAPERS", {n: make(n) for n in results})
        monkeypatch.setattr(sys, "argv", ["scraper.py", *argv])
        summarised.clear()
        scraper.main()
        with open(out, newline="", encoding="utf-8") as f:
            rows = {r["id"]: r for r in csv.DictReader(f)}
        health = {}
        if (tmp_path / "health.json").exists():
            health = json.loads((tmp_path / "health.json").read_text())["runs"][-1]["results"]
        return rows, health, list(summarised)

    return _run


def new_ids(rows):
    return {i for i, r in rows.items() if r["is_new"] == "TRUE"}


def test_new_flags_and_dates(run):
    rows, health, _ = run(1, {"hku": hku(*range(12))})
    assert len(new_ids(rows)) == 12 and health["hku"]["status"] == "ok"
    rows, _, _ = run(2, {"hku": hku(*range(13))})
    assert new_ids(rows) == {"HKU-12"}
    assert rows["HKU-0"]["date_added"] == "2026-09-01"
    assert rows["HKU-12"]["date_added"] == "2026-09-02"


def test_partial_failure_keeps_previous_rows(run):
    run(1, {"hku": hku(*range(12))})
    rows, health, _ = run(2, {"hku": hku(0, 1, 2)})
    assert health["hku"]["status"] == "partial"
    assert health["hku"]["kept_from_previous"] == 9
    assert len(rows) == 12 and not new_ids(rows)


def test_crash_keeps_previous_rows_and_recovery_is_not_new(run):
    run(1, {"hku": hku(*range(12))})
    rows, health, _ = run(2, {"hku": RuntimeError("portal down")})
    assert health["hku"]["status"] == "crashed" and "portal down" in health["hku"]["error"]
    assert len(rows) == 12
    rows, _, _ = run(3, {"hku": hku(*range(12))})
    assert not new_ids(rows)
    assert {r["date_added"] for r in rows.values()} == {"2026-09-01"}


def test_short_absence_is_not_new_long_absence_is(run):
    base = list(range(1, 12))
    run(1, {"hku": hku(0, *base)})
    run(2, {"hku": hku(*base)})                      # job 0 gone (portal fine)
    rows, _, _ = run(10, {"hku": hku(0, *base)})     # back within 60 days
    assert "HKU-0" not in new_ids(rows)
    assert rows["HKU-0"]["date_added"] == "2026-09-01"
    run(11, {"hku": hku(*base)})                     # gone again...
    rows, _, _ = run(80, {"hku": hku(0, *base)})     # ...for 70 days: a new posting
    assert "HKU-0" in new_ids(rows)
    assert rows["HKU-0"]["date_added"] == (DAY1 + timedelta(days=79)).isoformat()


def test_long_outage_stops_showing_stale_jobs(run):
    run(1, {"hku": hku(*range(12))})
    rows, health, _ = run(10, {"hku": RuntimeError("down")})
    assert len(rows) == 12
    rows, health, _ = run(17, {"hku": RuntimeError("down")})
    assert rows == {} and health["hku"]["kept_from_previous"] == 0


def test_deadline_wording_moves_to_note_and_expired_jobs_drop(run):
    rows, _, _ = run(1, {"hku": hku(0, deadline="Open until the position is filled")
                                + hku(1, deadline="2026-06-01")
                                + hku(*range(2, 12))})
    assert rows["HKU-0"]["deadline"] == "" and rows["HKU-0"]["deadline_note"] == "Open until filled"
    assert "HKU-1" not in rows


def test_summaries_are_generated_once(run):
    _, _, summarised = run(1, {"hku": hku(*range(12))})
    assert len(summarised) == 12
    rows, _, summarised = run(2, {"hku": hku(*range(13))})
    assert summarised == ["HKU-12"]
    assert rows["HKU-0"]["description"] == SUMMARY


def test_single_institution_run_keeps_other_rows(run):
    run(1, {"hku": hku(*range(12)), "cuhk": [job("CUHK", n) for n in range(5)]})
    rows, _, _ = run(2, {"hku": hku(*range(12)), "cuhk": []}, argv=["--uni", "hku"])
    assert sum(r["university"] == "CUHK" for r in rows.values()) == 5
