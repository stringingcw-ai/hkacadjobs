"""Emails for saved CV profiles ("jobs that fit you"): profiles are matched
against today's new jobs through the match-jobs function, fits are emailed
once, and failures are reported."""
import io
import json
import urllib.error
from datetime import datetime, timezone

import pytest

import match_alerts
import notify


def job(i, **kw):
    j = {"id": f"HKU-{i}", "title": f"Lecturer in Nursing {i}", "rank": "Senior Lecturer/Lecturer",
         "university": "HKU", "department": "School of Nursing", "deadline": "2026-11-30",
         "deadline_note": "", "is_new": "TRUE"}
    j.update(kw)
    return j


ROW = {"user_id": "u1", "email": "nurse@example.com", "token": "tok-0123456789abcdef",
       "profile": {"headline": "Registered nurse and clinical nurse educator", "role_type": "academic"}}


@pytest.fixture
def world(monkeypatch):
    """Fake Supabase, match-jobs and Resend; records what was asked and sent."""
    state = {"profiles": [ROW], "fits": {}, "calls": [], "sent": [], "fail_for": set()}

    monkeypatch.setattr(notify, "_get_all", lambda path: state["profiles"])

    def fetch(profile, job_ids, prefs=None, timeout=90):
        state["calls"].append(job_ids)
        state["prefs"] = prefs
        if "error" in state["fits"]:
            raise state["fits"]["error"]
        return [f for f in state["fits"].get("list", []) if f["job_id"] in job_ids]
    monkeypatch.setattr(match_alerts, "fetch_matches", fetch)

    def send(to, subject, html, text, unsub_url=None):
        if to in state["fail_for"]:
            raise RuntimeError("Resend error 500")
        state["sent"].append({"to": to, "subject": subject, "html": html, "text": text, "unsub": unsub_url})
        return {"id": "email-1"}
    monkeypatch.setattr(notify, "send_email", send)
    monkeypatch.setattr(match_alerts.time, "sleep", lambda s: None)
    return state


def fit(i, score=88, why="Your clinical teaching matches this post.", gaps=()):
    return {"job_id": f"HKU-{i}", "score": score, "fit": "strong", "why": why, "gaps": list(gaps)}


def test_no_new_jobs_means_no_calls(world):
    assert match_alerts.run([], {}) == 0
    assert world["calls"] == [] and world["sent"] == []


def test_fits_are_emailed_once_and_logged(world):
    world["fits"]["list"] = [fit(1, gaps=["A PhD in nursing"]), fit(2, score=72)]
    log = {}
    assert match_alerts.run([job(1), job(2), job(3)], log) == 0
    assert world["calls"] == [["HKU-1", "HKU-2", "HKU-3"]]
    (email,) = world["sent"]
    assert email["to"] == "nurse@example.com"
    assert email["subject"] == "HKAcadJobs: 2 new jobs that fit your profile"
    assert "Your clinical teaching matches this post." in email["html"]
    assert "Worth checking: A PhD in nursing" in email["html"]
    assert "Registered nurse and clinical nurse educator" in email["html"]
    assert "/jobs/lecturer-in-nursing-1-hku-1/?utm_source=job_alert&amp;utm_medium=email&amp;utm_campaign=cv_match" in email["html"]
    assert email["unsub"].endswith("?unsubscribe=tok-0123456789abcdef")
    key = notify._sub_key(ROW)
    assert set(log[key]) == {"HKU-1", "HKU-2"}

    # Next run: jobs already sent aren't offered again
    world["sent"].clear()
    world["calls"].clear()
    assert match_alerts.run([job(1), job(2), job(3)], log) == 0
    assert world["calls"] == [["HKU-3"]]
    assert world["sent"] == []


def test_nothing_fresh_means_no_call(world):
    log = {notify._sub_key(ROW): {"HKU-1": "2026-09-29"}}
    assert match_alerts.run([job(1)], log) == 0
    assert world["calls"] == []


def test_no_fits_no_email(world):
    world["fits"]["list"] = []
    assert match_alerts.run([job(1)], {}) == 0
    assert world["sent"] == []


def test_email_text_is_escaped(world):
    world["fits"]["list"] = [fit(1, why='<b>Great</b> & "strong"')]
    match_alerts.run([job(1, title="<script>alert(1)</script> Lecturer")], {})
    html = world["sent"][0]["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>Great</b>" not in html and "&lt;b&gt;Great&lt;/b&gt;" in html


def test_failures_are_counted_and_nothing_is_logged(world):
    world["fits"]["error"] = RuntimeError("match-jobs HTTP 500")
    log = {}
    assert match_alerts.run([job(1)], log) == 1
    assert log == {}

    world["fits"] = {"list": [fit(1)]}
    world["fail_for"].add("nurse@example.com")
    assert match_alerts.run([job(1)], log) == 1
    assert log == {}


def test_budget_reached_pauses_without_failing(world, capsys):
    world["fits"]["error"] = match_alerts.BudgetReached("budget_reached")
    assert match_alerts.run([job(1)], {}) == 0
    assert "ALERT_DAILY_BUDGET_USD" in capsys.readouterr().out


def test_dry_run_sends_and_logs_nothing(world):
    world["fits"]["list"] = [fit(1)]
    log = {}
    assert match_alerts.run([job(1)], log, dry_run=True) == 0
    assert world["sent"] == [] and log == {}


def test_logs_never_show_full_email_addresses(world, capsys):
    world["fits"]["list"] = [fit(1)]
    match_alerts.run([job(1)], {})
    out = capsys.readouterr().out
    assert "nurse@example.com" not in out and "n***@example.com" in out


def test_request_to_match_jobs(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None, context=None):
        seen.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data), timeout=timeout)
        return Resp(json.dumps({"ok": True, "matches": [fit(1)]}).encode())

    monkeypatch.setattr(notify, "SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.setattr(notify, "SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(match_alerts.urllib.request, "urlopen", urlopen)
    assert match_alerts.fetch_matches({"headline": "x"}, ["HKU-1"], {"unis": ["HKU", "CUHK"]}) == [fit(1)]
    assert seen["url"] == "https://p.supabase.co/functions/v1/match-jobs"
    assert seen["headers"]["Authorization"] == "Bearer service-key"
    assert seen["body"] == {"action": "match", "profile": {"headline": "x"}, "only_ids": ["HKU-1"],
                            "prefs": {"unis": ["HKU", "CUHK"]}, "limit": 5, "min_score": 65}
    # No saved institutions: all of them
    match_alerts.fetch_matches({"headline": "x"}, ["HKU-1"], None)
    assert seen["body"]["prefs"] == {"unis": []}

    def budget(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {},
                                     io.BytesIO(b'{"ok":false,"error":"budget_reached"}'))
    monkeypatch.setattr(match_alerts.urllib.request, "urlopen", budget)
    with pytest.raises(match_alerts.BudgetReached):
        match_alerts.fetch_matches({}, ["HKU-1"])


def test_notify_runs_match_alerts_even_without_filter_subscribers(monkeypatch, tmp_path):
    ran = {}
    monkeypatch.setattr(notify, "ALERT_LOG", tmp_path / "log.json")
    monkeypatch.setattr(notify, "SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(notify, "load_new_jobs", lambda: [job(1)])
    monkeypatch.setattr(notify, "get_subscriptions", lambda: [])
    monkeypatch.setattr(match_alerts, "run", lambda jobs, log, dry_run=False: ran.update(jobs=jobs) or 1)
    monkeypatch.setattr(match_alerts, "purge_usage_log", lambda dry_run=False: ran.update(purged=True))
    monkeypatch.setattr("sys.argv", ["notify.py"])
    with pytest.raises(SystemExit) as exit_:
        notify.main()
    assert exit_.value.code == 1          # a match-alert failure fails the run
    assert ran["jobs"] == [job(1)]
    assert ran["purged"]
    assert (tmp_path / "log.json").exists()


def test_saved_institutions_are_passed_on(world):
    world["profiles"] = [dict(ROW, prefs={"unis": ["HKU"]})]
    world["fits"]["list"] = [fit(1)]
    match_alerts.run([job(1)], {})
    assert world["prefs"] == {"unis": ["HKU"]}


def test_usage_records_older_than_90_days_are_deleted(monkeypatch, capsys):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None, context=None):
        seen.update(url=req.full_url, method=req.get_method(), headers=dict(req.header_items()))
        return Resp(b"")

    monkeypatch.setattr(notify, "SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.setattr(notify, "SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setattr(match_alerts.urllib.request, "urlopen", urlopen)
    assert match_alerts.purge_usage_log() is True
    assert seen["method"] == "DELETE"
    assert seen["url"].startswith("https://p.supabase.co/rest/v1/match_usage?created_at=lt.")
    cutoff = seen["url"].split("lt.", 1)[1]
    age = datetime.now(timezone.utc) - datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert 89.9 < age.total_seconds() / 86400 < 90.1
    assert seen["headers"]["Authorization"] == "Bearer service-key"

    def down(req, timeout=None, context=None):
        raise urllib.error.URLError("unreachable")
    monkeypatch.setattr(match_alerts.urllib.request, "urlopen", down)
    assert match_alerts.purge_usage_log() is False      # a warning, not a failed run
    assert "::warning::" in capsys.readouterr().out
    assert match_alerts.purge_usage_log(dry_run=True) is True
