"""
patch_hku_descriptions.py
─────────────────────────
Fetches missing descriptions for HKU jobs that still have placeholder text.

Works in batches of 20 (configurable). After each batch it validates every
job and re-queues those that still have poor descriptions.

Usage:
  python patch_hku_descriptions.py             # run one batch (default 20)
  python patch_hku_descriptions.py --batch 20  # explicit batch size
  python patch_hku_descriptions.py --all       # keep going until queue empty
  python patch_hku_descriptions.py --dry-run   # show queue without fetching
"""

import argparse
import csv
import os
import re
import random
import sys
from pathlib import Path

# ── Paths
SCRIPT_DIR  = Path(__file__).parent
CSV_PATH    = SCRIPT_DIR.parent / "jobs.csv"
QUEUE_FILE  = SCRIPT_DIR / ".hku_patch_queue.txt"   # persists between runs

FIELDNAMES = [
    "id", "title", "rank", "university", "university_full",
    "department", "deadline", "is_new", "date_added", "date_posted", "reference",
    "position_type", "salary", "start_date", "apply_url", "description"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PLACEHOLDER_MARKER  = "please visit the application link"
BOT_MARKERS         = ("security check", "not a bot", "verify that you are", "cloudflare", "complete the security")


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_poor(desc: str) -> bool:
    """True if description is empty, placeholder-like, or lacks structure."""
    if not desc or len(desc.strip()) <= 80:
        return True
    d = desc.strip().lower()
    if PLACEHOLDER_MARKER in d:
        return True
    if "please visit" in d and "full details" in d:
        return True
    if any(m in d for m in BOT_MARKERS):
        return True
    return False


def is_good(desc: str) -> bool:
    """True only if description has real structured content (AI summary markers)."""
    if is_poor(desc):
        return False
    # Must have AI summary markers so the main scraper's _has_good_desc recognises it
    return "**" in desc and "•" in desc


def load_csv() -> dict:
    """Return {job_id: row_dict} for all jobs."""
    jobs = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            jobs[row["id"]] = row
    return jobs


def save_csv(jobs: dict):
    """Write all jobs back to CSV preserving column order."""
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(jobs.values())


def build_queue(jobs: dict) -> list:
    """All HKU jobs with poor descriptions, sorted: academic ranks first."""
    RANK_PRIORITY = {
        "Tenure-Track": 0, "Professor": 1, "Associate Professor": 2,
        "Assistant Professor": 3, "Senior Lecturer/Lecturer": 4,
        "Research Assistant/Associate": 5,
    }
    poor = [j for j in jobs.values()
            if j.get("university") == "HKU" and is_poor(j.get("description", ""))]
    poor.sort(key=lambda j: RANK_PRIORITY.get(j.get("rank", ""), 99))
    return poor


def load_persisted_queue(jobs: dict) -> list:
    """Load IDs from queue file, filter to those still poor in current CSV."""
    if not QUEUE_FILE.exists():
        return []
    ids = QUEUE_FILE.read_text().splitlines()
    result = [jobs[i] for i in ids if i in jobs and is_poor(jobs[i].get("description", ""))]
    return result


def save_persisted_queue(remaining: list):
    QUEUE_FILE.write_text("\n".join(j["id"] for j in remaining))


def summarise(raw_text: str, title: str, dept: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return raw_text
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": (
                    "Summarise this academic job description into exactly 4 sections using the format below. "
                    "Each section must have a bold header followed by concise bullet points. "
                    "Be brief — each bullet point should be one short sentence. "
                    "Do not mention the university name or reference numbers.\n\n"
                    "Use this exact format:\n"
                    "**Duties & Responsibilities**\n• [bullet]\n• [bullet]\n\n"
                    "**Requirements & Qualifications**\n• [bullet]\n• [bullet]\n\n"
                    "**Appointment**\n• [Full-time / Part-time / Contract — include contract duration if mentioned, or 'Not specified']\n\n"
                    "**Key Dates**\n"
                    "Extract ALL dates mentioned in the description and label each one clearly. "
                    "Use one bullet per date. Format each bullet as: '• [Label]: [Date]'. "
                    "If no dates are mentioned, write: '• Not specified'\n\n"
                    f"Job title: {title}\nDepartment: {dept}\n\nDescription:\n{raw_text[:3000]}"
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"  ⚠️  Summarisation failed for '{title}': {e}")
        return raw_text


# ── Main fetch logic ──────────────────────────────────────────────────────────

def fetch_batch(batch: list, jobs: dict) -> tuple[int, int]:
    """
    Fetch detail pages for jobs in `batch`. Updates `jobs` in-place.
    Returns (fetched_ok, still_poor).
    """
    from playwright.sync_api import sync_playwright

    fetched_ok   = 0
    still_poor   = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = ctx.new_page()

        for idx, job in enumerate(batch, 1):
            url = job.get("apply_url", "")
            if not url:
                print(f"  [{idx}/{len(batch)}] SKIP (no apply_url): {job['title'][:60]}")
                still_poor += 1
                continue

            try:
                print(f"  [{idx}/{len(batch)}] Fetching: {job['title'][:55]}")
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(random.randint(2500, 4000))
                text = page.inner_text("body")

                if any(m in text.lower() for m in BOT_MARKERS):
                    print(f"    ⚠️  WAF/bot-check detected — skipping")
                    still_poor += 1
                    continue

                lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 60]
                raw = "\n\n".join(lines[:20])[:3000] if lines else ""

                if is_poor(raw):
                    print(f"    ✗  Detail page returned poor content ({len(raw)}c)")
                    still_poor += 1
                    continue

                # Summarise via Claude Haiku
                summary = summarise(raw, job["title"], job.get("department", ""))

                if is_good(summary):
                    jobs[job["id"]]["description"] = summary
                    fetched_ok += 1
                    print(f"    ✓  Good description ({len(summary)}c)")
                else:
                    # Keep raw if summarisation produced nothing useful
                    jobs[job["id"]]["description"] = raw
                    if is_good(raw):
                        fetched_ok += 1
                        print(f"    ✓  Raw description saved ({len(raw)}c)")
                    else:
                        still_poor += 1
                        print(f"    ✗  Still poor after summarisation ({len(summary)}c)")

            except Exception as e:
                print(f"    ✗  Error: {e}")
                still_poor += 1

        page.close()
        ctx.close()
        browser.close()

    return fetched_ok, still_poor


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Patch HKU placeholder descriptions")
    parser.add_argument("--batch", type=int, default=20, help="Jobs per batch (default 20)")
    parser.add_argument("--all",   action="store_true",  help="Run all batches until queue empty")
    parser.add_argument("--dry-run", action="store_true", help="Show queue without fetching")
    parser.add_argument("--reset-queue", action="store_true", help="Rebuild queue from scratch ignoring saved state")
    args = parser.parse_args()

    print("── HKU Description Patch ──────────────────────────────")
    jobs = load_csv()
    print(f"Loaded {len(jobs)} jobs from CSV")

    # Build or restore queue
    if args.reset_queue or not QUEUE_FILE.exists():
        queue = build_queue(jobs)
        print(f"Built fresh queue: {len(queue)} HKU jobs with poor descriptions")
    else:
        queue = load_persisted_queue(jobs)
        if not queue:
            # Queue file exists but all entries are now good — rebuild
            queue = build_queue(jobs)
            print(f"Queue cleared — rebuilt: {len(queue)} remaining")
        else:
            print(f"Restored queue: {len(queue)} jobs remaining from last run")

    if not queue:
        print("✅ No HKU jobs with poor descriptions found — nothing to do.")
        QUEUE_FILE.unlink(missing_ok=True)
        return

    if args.dry_run:
        print(f"\nDRY RUN — would process {len(queue)} jobs in batches of {args.batch}:")
        for i, j in enumerate(queue[:40], 1):
            print(f"  {i:>3}. [{j.get('rank','?'):25}] {j['title'][:60]}")
        if len(queue) > 40:
            print(f"  ... and {len(queue)-40} more")
        return

    batch_num   = 0
    total_fixed = 0

    while queue:
        batch_num += 1
        batch = queue[:args.batch]
        print(f"\n── Batch {batch_num} ({len(batch)} jobs) ──────────────────────────")

        fetched_ok, still_poor = fetch_batch(batch, jobs)
        total_fixed += fetched_ok

        print(f"\n  Batch {batch_num} result: {fetched_ok} improved, {still_poor} still poor")

        # Save CSV after each batch
        save_csv(jobs)
        print(f"  ✅ CSV saved ({total_fixed} total descriptions improved so far)")

        # Re-validate entire queue against updated CSV
        processed_ids = {j["id"] for j in batch}
        still_poor_jobs = [j for j in batch if is_poor(jobs[j["id"]].get("description", ""))]
        remaining_queue = queue[args.batch:] + still_poor_jobs  # unprocessed + re-queued failures

        print(f"  Queue: {len(queue[args.batch:])} unprocessed + {len(still_poor_jobs)} re-queued = {len(remaining_queue)} remaining")
        save_persisted_queue(remaining_queue)
        queue = remaining_queue

        if not args.all:
            print(f"\n  Stopping after 1 batch (run with --all to continue, or run again for next batch)")
            break

    print(f"\n── Summary ──────────────────────────────────────────")
    print(f"  Batches run  : {batch_num}")
    print(f"  Total fixed  : {total_fixed}")
    remaining = build_queue(jobs)
    print(f"  Still poor   : {len(remaining)}")
    if remaining:
        print(f"  (run again to process next batch of {args.batch})")


if __name__ == "__main__":
    main()
