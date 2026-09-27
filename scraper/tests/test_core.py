from datetime import date

import pytest

import core


@pytest.mark.parametrize("title, rank", [
    ("Assistant Professor in Physics", "Assistant Professor"),
    ("Post-doctoral Fellow", "Postdoctoral"),
    ("Research Assistant", "Research Assistant/Associate"),
    ("Senior Lecturer", "Senior Lecturer/Lecturer"),
    ("Lecturer (Teaching-track)", "Senior Lecturer/Lecturer"),
    ("Chair Professor", "Professor"),
    ("Clerical Officer", "Non-Academic"),
])
def test_detect_rank(title, rank):
    assert core.detect_rank(title, "") == rank


@pytest.mark.parametrize("raw, deadline, note", [
    ("2026-10-15", "2026-10-15", ""),
    ("15 October 2026", "2026-10-15", ""),
    ("Open until the position is filled", "", "Open until filled"),
    ("Ongoing recruitment", "", "Ongoing recruitment"),
    # A review/screening start date is not a closing date
    ("Review of applications will start on 15 Oct 2026", "", "Applications reviewed from 15 Oct 2026"),
    ("", "", ""),
])
def test_normalise_deadline(raw, deadline, note):
    job = {"deadline": raw}
    core.normalise_deadline(job)
    assert job["deadline"] == deadline
    assert job.get("deadline_note", "") == note


def test_parse_dates():
    assert core.parse_date_text("15 October 2026") == "2026-10-15"
    assert core.parse_date_text("Oct 15, 2026") == "2026-10-15"
    assert core.date_in_text("closing on 3 Nov 2026 at noon") == "2026-11-03"


def test_text_fragment_url():
    url = core.text_fragment_url("https://x.org/jobs#old", "Assistant Professor in Physics - Dept of X")
    assert url == "https://x.org/jobs#:~:text=Assistant%20Professor%20in%20Physics%20%2D%20Dept%20of%20X"


def test_make_id_and_clean():
    assert core.make_id("HKU", "123") == "HKU-123"
    assert core.make_id("THEI", "二級機械工").startswith("THEI-") and core.make_id("THEI", "二級機械工").isascii()
    assert core.clean("  a \n\t b  ") == "a b"


def summary(closing_line):
    return ("**Duties & Responsibilities**\n• Teach\n\n**Requirements & Qualifications**\n• PhD\n\n"
            "**Appointment**\n• Full-time\n\n**Key Dates**\n" + closing_line)


def test_reconcile_fills_blank_deadline_from_summary():
    job = {"deadline": "", "deadline_note": "", "description": summary("• Closing date: 2026-11-30")}
    core.reconcile_summary_deadline(job)
    assert job["deadline"] == "2026-11-30"


def test_reconcile_keeps_listing_deadline_and_fixes_summary():
    job = {"deadline": "2026-12-01", "deadline_note": "", "description": summary("• Closing date: 2026-11-30")}
    core.reconcile_summary_deadline(job)
    assert job["deadline"] == "2026-12-01"
    assert "2026-11-30" not in job["description"]


def test_reconcile_respects_until_filled_note():
    job = {"deadline": "", "deadline_note": "Open until filled", "description": summary("• Closing date: 2026-11-30")}
    core.reconcile_summary_deadline(job)
    assert job["deadline"] == ""


def test_due_for_recheck_is_one_weekday_per_job(monkeypatch):
    days = []
    for d in range(7):
        monkeypatch.setattr(core, "TODAY", date(2026, 9, 21 + d))
        days.append(core.due_for_recheck("CUHK-1234"))
    assert days.count(True) == 1
