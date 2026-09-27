"""
HKAcadJobs Scraper
Scrapes academic job listings from 17 Hong Kong institutions (one module per
institution in sites/) and writes jobs.csv in the format the website expects.

Usage (from the repo root):
  python scraper/scraper.py              # scrape all institutions
  python scraper/scraper.py --uni polyu  # re-scrape one; other rows are kept

Requirements:
  pip install -r scraper/requirements.txt
  playwright install chromium    # for JS-rendered sites
"""

import argparse
import csv
import json
import re
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import (
    detect_rank, FIELDNAMES, is_active, is_within_retention, normalise_deadline,
    PLACEHOLDER_MARKER, reconcile_summary_deadline, TODAY, _existing_descriptions,
    _has_good_desc, _previous_rows,
)
from sites.chuhai import scrape_chuhai
from sites.cityu import scrape_cityu
from sites.cpce import scrape_cpce
from sites.cuhk import scrape_cuhk
from sites.eduhk import scrape_eduhk
from sites.hkbu import scrape_hkbu
from sites.hkmu import scrape_hkmu
from sites.hksyu import scrape_hksyu
from sites.hku import scrape_hku
from sites.hkuspace import scrape_hkuspace
from sites.hkust import scrape_hkust
from sites.hsu import scrape_hsu
from sites.lingnan import scrape_lingnan
from sites.polyu import scrape_polyu, scrape_polyu_detail
from sites.sfu import scrape_sfu
from sites.thei import scrape_thei
from sites.vtc import scrape_vtc
from summaries import summarise_jobs


# ── Output file path (same directory as this script)
OUTPUT_FILE = Path(__file__).parent.parent / "jobs.csv"

SCRAPERS = {
    "polyu":  scrape_polyu,
    "eduhk":  scrape_eduhk,
    "lingnan": scrape_lingnan,
    "hku":    scrape_hku,
    "hkust":  scrape_hkust,
    "cityu":  scrape_cityu,
    "hkbu":   scrape_hkbu,
    "cuhk":   scrape_cuhk,
    "hkmu":   scrape_hkmu,
    "hsu":    scrape_hsu,
    "sfu":    scrape_sfu,
    "hksyu":    scrape_hksyu,
    "vtc":      scrape_vtc,
    "hkuspace": scrape_hkuspace,
    "cpce":     scrape_cpce,
    "chuhai":   scrape_chuhai,
    "thei":     scrape_thei,
}

# Scraper name → university code(s) used in the CSV. Used to fall back to the
# previous run's rows when a scraper crashes or under-delivers.
SCRAPER_UNI_CODES = {
    "polyu": ["PolyU"], "eduhk": ["EdUHK"], "lingnan": ["LU"],
    "hku": ["HKU"], "hkust": ["HKUST"], "cityu": ["CityU"],
    "hkbu": ["HKBU"], "cuhk": ["CUHK"], "hkmu": ["HKMU"],
    "hsu": ["HSU"], "sfu": ["SFU"], "hksyu": ["HKSYU"],
    "vtc": ["VTC"], "hkuspace": ["HKUSPACE"], "cpce": ["CPCE"],
    "chuhai": ["HKCHC"], "thei": ["THEI"],
}

# ── Scrape health: every full run appends per-scraper results to this file;
#    scraper/health.py reads it after publishing and fails the workflow if any
#    institution crashed, came back empty, or came back well short of usual.
HEALTH_FILE          = Path(__file__).parent / "scrape_health.json"
HEALTH_KEEP_RUNS     = 30    # runs kept in the file
PARTIAL_RATIO        = 0.7   # fewer than this share of the usual count = partial failure
PARTIAL_MIN_BASELINE = 10    # small portals swing naturally; only an empty result counts there


def load_health_runs():
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8")).get("runs", [])
    except (OSError, ValueError):
        return []


def expected_count(runs, name, previous_count):
    """A scraper's usual job count: the median of its last 7 recorded runs plus
    the previous CSV's count, so it works from the first run and settles within
    a few days if a portal genuinely shrinks."""
    samples = [r["results"][name]["scraped"] for r in runs[-7:] if name in r.get("results", {})]
    samples.append(previous_count)
    return statistics.median(samples)


# ── Job registry: the first and last day each job id was actually scraped.
#    Unlike the previous CSV, it remembers jobs through portal outages, so a
#    job that drops out and comes back keeps its original date_added and isn't
#    re-flagged NEW (or re-alerted to subscribers).
REGISTRY_FILE        = Path(__file__).parent / "job_registry.json"
REAPPEAR_WINDOW_DAYS = 60    # absent longer than this → treated as a new posting
REGISTRY_KEEP_DAYS   = 180   # forget ids not scraped for this long
FALLBACK_MAX_DAYS    = 14    # stop showing a failing portal's old jobs after this


def load_registry():
    """{job id: [first_seen, last_seen]} as ISO dates (HKT)."""
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8")).get("jobs", {})
    except (OSError, ValueError):
        return {}


def save_registry(registry):
    cutoff = (TODAY - timedelta(days=REGISTRY_KEEP_DAYS)).isoformat()
    lines = [f"{json.dumps(k, ensure_ascii=False)}:{json.dumps(v)}"
             for k, v in sorted(registry.items()) if v[1] >= cutoff]
    # One job per line keeps daily diffs small and readable
    REGISTRY_FILE.write_text('{"version":1,"jobs":{\n' + ",\n".join(lines) + "\n}}\n", encoding="utf-8")


def days_since(date_str):
    try:
        return (TODAY - date.fromisoformat(date_str)).days
    except (TypeError, ValueError):
        return 10 ** 6


def deduplicate(jobs):
    """Remove duplicate jobs by id."""
    seen = set()
    unique = []
    for j in jobs:
        if j["id"] not in seen:
            seen.add(j["id"])
            unique.append(j)
    return unique


def main():
    parser = argparse.ArgumentParser(description="HKAcadJobs Scraper")
    parser.add_argument("--uni", help="Scrape one university only (e.g. polyu, hku)")
    parser.add_argument("--output", help="Output CSV path (default: ../jobs.csv)")
    parser.add_argument("--debug-polyu", metavar="REF", help="Debug a single PolyU detail page")
    parser.add_argument("--force-resummary", action="store_true", help="Re-run AI summarisation for all jobs, ignoring cached summaries")
    args = parser.parse_args()

    if args.debug_polyu:
        print(f"🔍 Debugging PolyU detail page for ref: {args.debug_polyu}")
        scrape_polyu_detail(args.debug_polyu, debug=True)
        return


    if args.output:
        global OUTPUT_FILE
        OUTPUT_FILE = Path(args.output)

    print(f"\n🎓 HKAcadJobs Scraper — {TODAY.strftime('%d %B %Y')}")
    print("=" * 50)

    # Load previous run to detect which jobs are genuinely new today
    today_str = TODAY.strftime("%Y-%m-%d")
    existing = {}      # id → full row dict from previous CSV
    existing_rows = {} # university code → list of full rows (for fallback on scraper failure)
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    jid = row.get("id", "")
                    if jid:
                        existing[jid] = dict(row)
                        uni = row.get("university", "")
                        if uni:
                            existing_rows.setdefault(uni, []).append(dict(row))
            print(f"↳ Previous CSV: {len(existing)} jobs loaded")
        except Exception as e:
            print(f"  ⚠️  Could not read previous CSV: {e}")

    # Expose existing descriptions so scrapers can skip re-fetching known jobs.
    # Filled in place: the site modules imported these dicts from core.
    _existing_descriptions.clear()
    _existing_descriptions.update({jid: row.get("description", "") for jid, row in existing.items()})
    _previous_rows.clear()
    _previous_rows.update(existing)

    all_jobs = []
    health_runs, health_results = None, {}
    registry = load_registry()
    scraped_ids = set()   # ids actually returned by a scraper today (not kept from before)

    if args.uni:
        # Scrape single university
        uni = args.uni.lower()
        if uni not in SCRAPERS:
            print(f"Unknown university: {uni}. Options: {', '.join(SCRAPERS.keys())}")
            sys.exit(1)
        all_jobs = SCRAPERS[uni]()
        scraped_ids = {j["id"] for j in all_jobs}
        # Keep every other institution's rows so jobs.csv isn't overwritten
        # with a single university
        own_codes = set(SCRAPER_UNI_CODES.get(uni, []))
        all_jobs += [r for code, rows in existing_rows.items() if code not in own_codes for r in rows]
    else:
        # Scrape all
        health_runs = load_health_runs()
        for name, scraper in SCRAPERS.items():
            previous = [r for code in SCRAPER_UNI_CODES.get(name, []) for r in existing_rows.get(code, [])]
            expected = expected_count(health_runs, name, len(previous))
            error = ""
            try:
                jobs = scraper() or []
            except Exception as e:
                print(f"  ❌ {name} crashed: {e}")
                jobs, error = [], f"{type(e).__name__}: {e}"

            if error:
                status = "crashed"
            elif not jobs:
                status = "empty"
            elif expected >= PARTIAL_MIN_BASELINE and len(jobs) < PARTIAL_RATIO * expected:
                status = "partial"
            else:
                status = "ok"

            # On any failure, keep the previous run's rows for this institution
            # that weren't re-scraped, so they don't vanish today and come back
            # tomorrow as "new" (re-alerted, re-summarised, new date_added).
            # Rows not actually scraped for FALLBACK_MAX_DAYS are dropped, so a
            # portal that stays broken doesn't show stale jobs indefinitely.
            kept = []
            if status != "ok":
                these_ids = {j["id"] for j in jobs}
                candidates = [r for r in previous if r["id"] not in these_ids]
                kept = [r for r in candidates
                        if days_since(registry.get(r["id"], [today_str, today_str])[1]) <= FALLBACK_MAX_DAYS]
                stale = len(candidates) - len(kept)
                print(f"  ⚠️  {name}: {status} — {len(jobs)} scraped vs ~{expected:.0f} usual; "
                      f"keeping {len(kept)} jobs from the previous run"
                      + (f" (dropped {stale} not seen for {FALLBACK_MAX_DAYS}+ days)" if stale else ""))
            all_jobs.extend(jobs)
            all_jobs.extend(kept)
            scraped_ids.update(j["id"] for j in jobs)

            health_results[name] = {
                "university": ",".join(SCRAPER_UNI_CODES.get(name, [])),
                "status": status,
                "scraped": len(jobs),
                "expected": round(expected),
                "kept_from_previous": len(kept),
            }
            if error:
                health_results[name]["error"] = error[:300]
            time.sleep(1)  # polite delay between universities

    all_jobs = deduplicate(all_jobs)
    for j in all_jobs:
        normalise_deadline(j)
    # Keep: active jobs, no-deadline jobs, and jobs closed within the last 14 days
    all_jobs = [j for j in all_jobs if is_within_retention(j.get("deadline", ""))]

    # Re-rank using both title and description now that descriptions are available
    for j in all_jobs:
        j["rank"] = detect_rank(j["title"], j.get("description", ""))

    # Override is_new and set date_added based on previous runs.
    # is_new = TRUE only for job IDs never seen before (or not seen for
    # REAPPEAR_WINDOW_DAYS) — a job that dropped out briefly isn't new.
    for j in all_jobs:
        # Ensure date_posted field exists (scrapers that don't set it leave it blank)
        if "date_posted" not in j:
            j["date_posted"] = ""
        seen = registry.get(j["id"])
        if seen and days_since(seen[1]) > REAPPEAR_WINDOW_DAYS:
            seen = None   # back after a long gap: a new posting, with a fresh history
        if j["id"] in existing:
            j["is_new"] = "FALSE"
            j["date_added"] = existing[j["id"]]["date_added"]
            # Preserve previously captured date_posted if scraper didn't return one this run
            if not j["date_posted"]:
                j["date_posted"] = existing[j["id"]].get("date_posted", "")
        elif seen and days_since(seen[1]) <= REAPPEAR_WINDOW_DAYS:
            # Back after a portal hiccup or partial scrape: keep its original date
            j["is_new"] = "FALSE"
            j["date_added"] = seen[0]
        else:
            # Don't mark as new if the deadline has already passed
            j["is_new"] = "TRUE" if is_active(j.get("deadline", "")) else "FALSE"
            j["date_added"] = today_str
        # Flaps before the registry existed reset some date_added values
        if seen and seen[0] < (j["date_added"] or today_str):
            j["date_added"] = seen[0]
        # Record today's sighting (only for jobs a scraper actually returned)
        if j["id"] in scraped_ids:
            registry[j["id"]] = [j["date_added"] or today_str, today_str]

    # ── AI summarisation via Claude Haiku
    # Reuse existing summaries for known jobs; only call the API for jobs
    # that have real scraped content but no summary yet.
    # _has_good_desc() is the single source of truth: requires **+• markers,
    # no placeholder text, and length > 80. Any job that doesn't meet this
    # standard is treated as needing a fresh fetch + summarisation.
    POOR_PATTERNS = (
        PLACEHOLDER_MARKER.lower(),           # "please visit the application link"
        "see application link",
        "see eduhk website",
        "please visit the application",       # catches redirect stubs specifically
        r"please visit.*for full details",    # "please visit ... for full details"
    )
    def _is_poor_content(desc):
        if not desc or len(desc.strip()) <= 300:
            return True
        d = desc.strip().lower()
        return any(re.search(p, d) for p in POOR_PATTERNS)

    to_summarise = []
    for j in all_jobs:
        prev_desc = existing.get(j["id"], {}).get("description", "")
        if _has_good_desc(j["id"]) and not args.force_resummary:
            j["description"] = prev_desc  # reuse existing AI summary
        elif not _is_poor_content(j.get("description", "")):
            to_summarise.append(j)

    summarise_jobs(to_summarise)

    # Summary closing date ↔ deadline column (fills blanks, fixes stale dates)
    for j in all_jobs:
        reconcile_summary_deadline(j)
        # Raw (unsummarised) text is only kept in full for the next attempt at
        # summarising; cap it so a Claude outage can't bloat jobs.csv
        if "**" not in (j.get("description") or "") and len(j.get("description") or "") > 3000:
            j["description"] = j["description"][:3000]
    all_jobs = [j for j in all_jobs if is_within_retention(j.get("deadline", ""))]

    new_count    = sum(1 for j in all_jobs if j["is_new"] == "TRUE")
    active_count = sum(1 for j in all_jobs if is_active(j.get("deadline", "")))

    print("\n" + "=" * 50)
    print(f"📊 Total jobs scraped : {len(all_jobs)}")
    print(f"📊 Active (open)      : {active_count}")
    print(f"📊 New today          : {new_count}")
    print(f"📊 Closed / expired   : {len(all_jobs) - active_count}")

    # Write CSV
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"✅ Saved to {OUTPUT_FILE}")

    # Record this run for scraper/health.py (full runs only; written after the
    # CSV so a recorded run always means data was published)
    if health_runs is not None:
        save_registry(registry)
        health_runs.append({
            "date": today_str,
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_jobs": len(all_jobs),
            "new_jobs": new_count,
            "results": health_results,
        })
        HEALTH_FILE.write_text(
            json.dumps({"runs": health_runs[-HEALTH_KEEP_RUNS:]}, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        problems = {n: r["status"] for n, r in health_results.items() if r["status"] != "ok"}
        print(f"🩺 Scrape health: {'all institutions OK' if not problems else problems}")

    print("🌐 Your website will update automatically within minutes.\n")


if __name__ == "__main__":
    main()
