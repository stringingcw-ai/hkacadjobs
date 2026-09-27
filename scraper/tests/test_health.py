import csv
from datetime import datetime, timedelta, timezone

import health

NOW = datetime(2026, 9, 27, 18, 30, tzinfo=timezone.utc)


def run(**results):
    return {"run_at": (NOW - timedelta(minutes=30)).isoformat(),
            "results": {k: {"university": k.upper(), "status": s, "scraped": 5, "expected": 20,
                            "kept_from_previous": 10} for k, s in results.items()}}


def test_all_ok():
    assert health.find_problems(run(hku="ok", cuhk="ok"), "success", NOW) == []


def test_partial_and_crashed_are_reported():
    problems = health.find_problems(run(hku="partial", cuhk="crashed", thei="ok"), "success", NOW)
    assert len(problems) == 2 and any("HKU" in p for p in problems)


def test_missing_or_stale_record():
    assert health.find_problems(None, "", NOW)
    stale = run(hku="ok")
    stale["run_at"] = (NOW - timedelta(days=1)).isoformat()
    assert health.find_problems(stale, "success", NOW)


def test_notify_failure_is_reported():
    assert health.find_problems(run(hku="ok"), "failure", NOW)
    assert health.find_problems(run(hku="ok"), "skipped", NOW) == []


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "deadline"])
        w.writeheader()
        w.writerows(rows)


def test_csv_check(tmp_path):
    good = tmp_path / "good.csv"
    write_csv(good, [{"id": "A-1", "title": "Job", "deadline": "2026-10-01"}, {"id": "A-2", "title": "Job", "deadline": ""}])
    assert health.check_csv(good) == []
    bad = tmp_path / "bad.csv"
    write_csv(bad, [{"id": "A-1", "title": "Job", "deadline": "Open until filled"},
                    {"id": "A-1", "title": "", "deadline": ""}])
    problems = health.check_csv(bad)
    assert len(problems) == 3
