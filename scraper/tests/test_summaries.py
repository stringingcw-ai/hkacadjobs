"""summarise_jobs() against a fake Anthropic client: direct calls for small
runs, the Batches API for larger ones, and fallbacks when either fails."""
import json
import sys
import types
from types import SimpleNamespace as NS

import pytest

import summaries

PAYLOAD = {
    "duties": ["Teach courses"], "requirements": ["A PhD"], "appointment": "Full-time, 3 years",
    "key_dates": [{"label": "Closing date", "date": "30 Nov 2026"}],
    "salary": "HK$50,000 per month", "start_date": "January 2027", "closing_date": "2026-11-30",
}


def message(payload=PAYLOAD, stop="end_turn"):
    return NS(stop_reason=stop, content=[NS(type="text", text=json.dumps(payload))],
              usage=NS(input_tokens=100, output_tokens=50))


class FakeClient:
    def __init__(self, batch_fails=False, batch_never_ends=False, batch_skip=()):
        self.direct_calls = 0
        self.batch_requests = None
        client = self

        class Messages:
            def create(self, **params):
                client.direct_calls += 1
                assert params["output_config"]["format"]["type"] == "json_schema"
                return message()

            class batches:
                @staticmethod
                def create(requests):
                    if batch_fails:
                        raise RuntimeError("batches unavailable")
                    client.batch_requests = requests
                    return NS(id="b1", processing_status="in_progress")

                @staticmethod
                def retrieve(batch_id):
                    return NS(id=batch_id, processing_status="in_progress" if batch_never_ends else "ended")

                @staticmethod
                def cancel(batch_id):
                    pass

                @staticmethod
                def results(batch_id):
                    for r in client.batch_requests:
                        if r["custom_id"] not in batch_skip:
                            yield NS(custom_id=r["custom_id"],
                                     result=NS(type="succeeded", message=message()))

        self.messages = Messages()


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(**kw):
        client = FakeClient(**kw)
        monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda api_key: client))
        holder["client"] = client
        return client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(summaries.time, "sleep", lambda s: None)
    return install


def jobs(n):
    return [{"id": str(i), "title": f"Job {i}", "department": "Physics", "description": "raw text",
             "deadline": "", "deadline_note": ""} for i in range(n)]


def test_small_run_uses_direct_calls(fake):
    client = fake()
    js = jobs(3)
    summaries.summarise_jobs(js)
    assert client.direct_calls == 3 and client.batch_requests is None
    j = js[0]
    assert j["description"].startswith("**Duties & Responsibilities**\n• Teach courses")
    assert "• Closing date: 30 Nov 2026" in j["description"]
    assert j["salary"] == "HK$50,000 per month" and j["start_date"] == "January 2027"
    assert j["deadline"] == "2026-11-30"


def test_large_run_uses_batches(fake):
    client = fake()
    js = jobs(12)
    summaries.summarise_jobs(js)
    assert len(client.batch_requests) == 12 and client.direct_calls == 0
    assert all(j["description"].startswith("**") for j in js)


def test_batch_gaps_are_filled_directly(fake):
    client = fake(batch_skip={"0", "5"})
    js = jobs(12)
    summaries.summarise_jobs(js)
    assert client.direct_calls == 2
    assert all(j["description"].startswith("**") for j in js)


def test_batch_failure_falls_back_to_direct(fake):
    client = fake(batch_fails=True)
    js = jobs(12)
    summaries.summarise_jobs(js)
    assert client.direct_calls == 12


def test_unfinished_batch_is_cancelled_and_finished_directly(fake, monkeypatch):
    monkeypatch.setattr(summaries, "BATCH_MAX_WAIT", 0)
    client = fake(batch_never_ends=True)
    js = jobs(12)
    summaries.summarise_jobs(js)
    assert client.direct_calls == 12


def test_no_api_key_leaves_raw_text(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    js = jobs(2)
    summaries.summarise_jobs(js)
    assert js[0]["description"] == "raw text"


def test_truncated_output_is_rejected():
    with pytest.raises(ValueError):
        summaries._parse_summary(message(stop="max_tokens"))


def test_extras_never_override_listing_data():
    job = {"salary": "Grade 5", "start_date": "", "deadline": "", "deadline_note": "Open until filled"}
    summaries.apply_summary_extras(job, {"salary": "HK$1", "start_date": "Soon", "closing_date": "2026-11-30"})
    assert job == {"salary": "Grade 5", "start_date": "Soon", "deadline": "", "deadline_note": "Open until filled"}


def test_empty_sections_render_as_not_specified():
    text = summaries._render_summary({"duties": [], "requirements": ["PhD"], "appointment": "", "key_dates": []})
    assert "**Duties & Responsibilities**\n• Not specified" in text
    assert text.endswith("**Key Dates**\n• Not specified")
