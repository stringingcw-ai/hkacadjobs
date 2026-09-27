"""Alert matching mirrors the site's filters; emails are escaped and link to
the job pages; the sent log stops repeat emails."""
import pytest

import notify

TAXONOMY = notify.load_site_taxonomy()   # read from index.html, like the site


def job(**kw):
    j = {"id": "HKU-1", "title": "Assistant Professor in Computer Science", "rank": "Assistant Professor",
         "university": "HKU", "university_full": "University of Hong Kong",
         "department": "Department of Computer Science", "description": "Machine learning research",
         "deadline": "2026-11-30", "deadline_note": ""}
    j.update(kw)
    return j


def test_taxonomy_is_read_from_the_site():
    assert TAXONOMY["areas"] and TAXONOMY["groups"]
    assert notify._classify("Department of Computer Science", TAXONOMY["areas"], "area") == "Computer Science & AI"


@pytest.mark.parametrize("state, expected", [
    ({}, True),
    ({"role": "academic"}, True),
    ({"role": "non-academic"}, False),
    ({"unis": ["HKU", "CUHK"]}, True),
    ({"unis": ["CUHK"]}, False),
    ({"ranks": ["Assistant Professor"]}, True),
    ({"ranks": ["Professor"]}, False),
    ({"area": "Computer Science & AI"}, True),
    ({"area": "Medicine & Health"}, False),
    ({"search": "machine learning"}, True),       # matches the description, as on the site
    ({"search": "learning machine"}, False),      # whole phrase, not separate words
    ({"search": "  COMPUTER science "}, True),
])
def test_job_matches_filter(state, expected):
    assert notify.job_matches_filter(job(), state, TAXONOMY) is expected


def test_disabled_filters_are_skipped_but_legacy_subscriptions_kept():
    subs = [{"user_id": "u1", "filter_label": "A"}, {"user_id": "u1", "filter_label": "B"}, {"email": "x@y.z"}]
    kept, dropped = notify.filter_active_subscriptions(subs, {("u1", "A")})
    assert [s.get("filter_label") for s in kept] == ["A", None] and dropped == 1


def test_email_is_escaped_and_links_to_job_page():
    evil = job(title='<script>alert(1)</script> & "Professor"', deadline="", deadline_note="Open until filled")
    html, text = notify.render_email({"filter_label": "<b>My</b> filter", "token": "tok,en2"}, [evil])
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>My</b>" not in html
    assert "/jobs/script-alert-1-script-professor-hku-1/?utm_source=job_alert" in html
    assert "Open until filled" in html
    assert "?unsubscribe=tok,en2" in html


def test_deadline_text():
    assert notify.deadline_text(job()) == "30 Nov 2026"
    assert notify.deadline_text(job(deadline="", deadline_note="Ongoing recruitment")) == "Ongoing recruitment"


def test_alert_log_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "ALERT_LOG", tmp_path / "log.json")
    key = notify._sub_key({"token": "secret-token"})
    assert "secret" not in key and len(key) == 16
    notify.save_alert_log({key: {"HKU-1": "2026-09-27", "HKU-0": "2020-01-01"}, "empty": {}})
    assert notify.load_alert_log() == {key: {"HKU-1": "2026-09-27"}}   # old entries pruned
