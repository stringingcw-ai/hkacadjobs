"""
AI job summaries (Claude Haiku 4.5, structured output). Uses the Message
Batches API (half price) when there are enough jobs, else direct calls.
"""

import json
import os
import time

from core import clean, ISO_DATE


# ── AI summaries (Claude Haiku 4.5, structured output)
SUMMARY_MODEL   = "claude-haiku-4-5-20251001"
SUMMARY_PRICES  = (1.00, 5.00)   # US$ per million input / output tokens; batches cost half
BATCH_MIN_JOBS  = 10             # use the Batches API from this many summaries up
BATCH_MAX_WAIT  = 20 * 60        # seconds; unfinished batch items are then summarised directly

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "duties":       {"type": "array", "items": {"type": "string"}},
        "requirements": {"type": "array", "items": {"type": "string"}},
        "appointment":  {"type": "string"},
        "key_dates":    {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string"}, "date": {"type": "string"}},
            "required": ["label", "date"],
            "additionalProperties": False,
        }},
        "salary":       {"type": "string"},
        "start_date":   {"type": "string"},
        "closing_date": {"type": "string"},
    },
    "required": ["duties", "requirements", "appointment", "key_dates", "salary", "start_date", "closing_date"],
    "additionalProperties": False,
}


def _summary_request(raw_text, title, dept):
    return {
        "model": SUMMARY_MODEL,
        "max_tokens": 1500,
        "output_config": {"format": {"type": "json_schema", "schema": _SUMMARY_SCHEMA}},
        "messages": [{
            "role": "user",
            "content": (
                "Summarise this academic job advertisement for a job board. Be concise: every list "
                "item is one short sentence. Do not mention the university's name or reference numbers.\n"
                "- duties: the main duties and responsibilities (2-6 items)\n"
                "- requirements: required and preferred qualifications and experience (2-6 items)\n"
                "- appointment: the terms in one line, e.g. 'Full-time, 2-year contract (renewable)'; "
                "'Not specified' if not stated\n"
                "- key_dates: every date mentioned, each with a clear label such as 'Closing date', "
                "'Review date', 'Interview date', 'Start date' or 'Posted date'; empty if none\n"
                "- salary: the salary, salary range or grade exactly as stated "
                "(e.g. 'HK$50,000 - 65,000 per month'); empty string if not stated\n"
                "- start_date: the expected start date as stated; empty string if not stated\n"
                "- closing_date: the application closing date as YYYY-MM-DD, only if a specific date "
                "is stated; otherwise empty string\n\n"
                f"Job title: {title}\nDepartment: {dept}\n\nAdvertisement:\n{raw_text[:12000]}"
            ),
        }],
    }


def _render_summary(data):
    """The structured summary in the site's display format (**Header** + • bullets)."""
    def bullets(items):
        items = [clean(i) for i in items if clean(i)]
        return "\n".join(f"• {i}" for i in items) if items else "• Not specified"
    dates = [f"{clean(d.get('label'))}: {clean(d.get('date'))}" for d in data.get("key_dates") or []
             if clean(d.get("label")) and clean(d.get("date"))]
    return (
        "**Duties & Responsibilities**\n" + bullets(data.get("duties") or []) + "\n\n"
        "**Requirements & Qualifications**\n" + bullets(data.get("requirements") or []) + "\n\n"
        "**Appointment**\n" + bullets([data.get("appointment") or "Not specified"]) + "\n\n"
        "**Key Dates**\n" + bullets(dates)
    )


def _parse_summary(message):
    """(summary text, extras) from a structured-output response; raises if unusable."""
    if message.stop_reason == "max_tokens":
        raise ValueError("summary was cut off at max_tokens")
    data = json.loads(next(b.text for b in message.content if b.type == "text"))
    extras = {k: clean(data.get(k) or "") for k in ("salary", "start_date", "closing_date")}
    return _render_summary(data), extras


def apply_summary_extras(job, extras):
    """Fill fields the listing didn't provide from the summary's structured fields."""
    if extras.get("salary") and not job.get("salary"):
        job["salary"] = extras["salary"][:120]
    if extras.get("start_date") and not job.get("start_date"):
        job["start_date"] = extras["start_date"][:80]
    closing = extras.get("closing_date", "")
    if ISO_DATE.match(closing) and not job.get("deadline") and not job.get("deadline_note"):
        job["deadline"] = closing


def summarise_job(raw_text, title, dept, client=None):
    """One job → (summary, extras). Falls back to (raw_text, {}) on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return raw_text, {}
    try:
        import anthropic
        client = client or anthropic.Anthropic(api_key=api_key)
        return _parse_summary(client.messages.create(**_summary_request(raw_text, title, dept)))
    except Exception as e:
        print(f"  ⚠️  Summarisation failed for '{title}': {e}")
        return raw_text, {}


def summarise_description(raw_text, title, dept):
    """Summary text only (kept for callers that don't use the extras)."""
    return summarise_job(raw_text, title, dept)[0]


def summarise_jobs(jobs):
    """Summarise jobs in place (description, plus salary / start date / deadline
    when the listing lacked them). Uses the Message Batches API (half price)
    for larger runs; anything it doesn't finish in time is done directly."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not jobs:
        return
    if not api_key:
        print(f"  ℹ️  ANTHROPIC_API_KEY not set — {len(jobs)} descriptions left as raw text")
        return
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    pending = {str(i): j for i, j in enumerate(jobs)}
    tokens = {"direct": [0, 0], "batch": [0, 0]}

    def done(key, message, kind):
        summary, extras = _parse_summary(message)
        job = pending.pop(key)
        job["description"] = summary
        apply_summary_extras(job, extras)
        tokens[kind][0] += message.usage.input_tokens
        tokens[kind][1] += message.usage.output_tokens

    print(f"\n🤖 Summarising {len(jobs)} descriptions via Claude Haiku...")
    if len(jobs) >= BATCH_MIN_JOBS:
        try:
            batch = client.messages.batches.create(requests=[
                {"custom_id": key, "params": _summary_request(j["description"], j["title"], j.get("department", ""))}
                for key, j in pending.items()
            ])
            print(f"  ↳ Batch {batch.id} submitted ({len(pending)} requests)")
            give_up = time.time() + BATCH_MAX_WAIT
            while batch.processing_status != "ended" and time.time() < give_up:
                time.sleep(15)
                batch = client.messages.batches.retrieve(batch.id)
            if batch.processing_status != "ended":
                print(f"  ⚠️  Batch unfinished after {BATCH_MAX_WAIT // 60} min — cancelling, finishing directly")
                client.messages.batches.cancel(batch.id)
                for _ in range(12):          # cancellation keeps finished results
                    time.sleep(10)
                    batch = client.messages.batches.retrieve(batch.id)
                    if batch.processing_status == "ended":
                        break
            if batch.processing_status == "ended":
                for res in client.messages.batches.results(batch.id):
                    if res.result.type == "succeeded" and res.custom_id in pending:
                        try:
                            done(res.custom_id, res.result.message, "batch")
                        except Exception as e:
                            print(f"  ⚠️  Unusable batch result for '{pending[res.custom_id]['title']}': {e}")
        except Exception as e:
            print(f"  ⚠️  Batch summarisation failed ({e}); summarising directly")

    for key, job in list(pending.items()):   # small runs, and anything the batch missed
        try:
            done(key, client.messages.create(**_summary_request(job["description"], job["title"],
                                                                 job.get("department", ""))), "direct")
        except Exception as e:
            print(f"  ⚠️  Summarisation failed for '{job['title']}': {e}")

    (d_in, d_out), (b_in, b_out) = tokens["direct"], tokens["batch"]
    cost = ((d_in + b_in / 2) * SUMMARY_PRICES[0] + (d_out + b_out / 2) * SUMMARY_PRICES[1]) / 1e6
    print(f"  ✅ Summarised {len(jobs) - len(pending)}/{len(jobs)} "
          f"(batch {tokens['batch'][0] and 'yes' or 'no'}; tokens in {d_in + b_in:,}, out {d_out + b_out:,}; ≈ US${cost:.3f})")
