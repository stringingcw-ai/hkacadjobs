# HKAcadJobs — Repository Health Check (27 Sep 2026)

The last code change was on 13 May 2026. Since then only the daily bot commits have landed. This audit covers
the eight areas requested. It is based on evidence from the repository and its history, not on reading the code alone.

**Evidence base**

- Code at `e0da2dc` (scraper, notify, page generator, `index.html`, workflows).
- **253 historical snapshots of `jobs.csv`** from git history (1 Apr → 26 Sep 2026), diffed day by day.
- **100 GitHub Actions run records** for `Daily Scraper` (19 Jun → 26 Sep), plus **full logs for 6 runs**
  (14 Aug, 18 Sep, 21 Sep, 22 Sep, 26 Sep).
- The 1,378 generated `/jobs/*/index.html` pages and `sitemap.xml`.

**Not verifiable from here:**
- The sandbox's network policy blocks university career sites and hkacadjobs.org, so apply links could not be
  bulk-checked live. The HKUST PeopleSoft host was reachable through an external fetch, and it refused the connection.
- Supabase, GA4 and Search Console data are not accessible. The SQL / GA4 checks to run are listed below.

> **Status (28 Sep): all Top-10 items and the non-growth recommendations are implemented, tested and live.**
> The manual Supabase step is done. What remains is listed at the end of this block.
>
> | # | Fix | Status |
> |---|---|---|
> | 1 | Alerts reach subscribers | ✅ UI saves `alert_enabled` when alerts are turned on; existing rows backfilled |
> | 2 | Unsubscribe | ✅ `?unsubscribe=` page restored; `List-Unsubscribe` header added |
> | 3 | False "NEW" flags | ✅ Persistent job registry (first/last seen, 60-day reappear window); on partial failures the previous rows are kept (up to 14 days); 797 reset `date_added` values repaired |
> | 4 | HKU "More Jobs" loop | ✅ Every row in one request (371 jobs) |
> | 5 | Scrape health gate | ✅ Per-institution counts vs a 7-run median; the run fails and emails the owner; also fails on malformed `jobs.csv` rows |
> | 6 | Alert matching + sent log | ✅ Mirrors the site's filters; no job emailed twice; links to the job page with UTM tags; sent only after the pages are live |
> | 7 | HKUST | ✅ Cached summaries are reused (no daily re-summarising). PeopleSoft links are kept: they work (see the correction in §5) |
> | 8 | Deadlines / CPCE / `validThrough` | ✅ `deadline` holds dates only (0 free-text values, was 216); wording moves to `deadline_note`; CPCE lists 29 jobs (was 6); `validThrough` only from real dates |
> | 9 | Homepage content for crawlers | ✅ Newest 50 jobs pre-rendered into `index.html`; static canonical; the CSVs stay blocked in `robots.txt` |
> | 10 | THEi | ✅ All 25 current jobs scraped |
>
> Beyond the Top 10:
> - §1 and §2: CUHK retries; HKBU and Lingnan use their careers sites' own APIs; SFU and Chu Hai deep-link to each job.
>   A full scrape now takes about 10 minutes (was 25–110). Summaries use structured output and the Batches API (half
>   price), with a longer input. Each job is summarised once. Summary dates are reconciled with the listing, and
>   salary and start date are filled from the summary. Token use and cost are logged. HKUST's 102 PeopleSoft-only
>   jobs, which showed a placeholder, now read their job ad from the page's public content view.
> - §4: HTML escaping, HKT dates, pagination, and a non-zero exit when most alerts are skipped.
> - §5: closed `?job=` links explain the job has closed. Closed jobs keep a `noindex` page for 60 days. A weekly
>   Apply-link check runs on GitHub's runners.
> - §6: stable job pages (rewritten only when a job changes) with real sitemap `lastmod` values. JobPosting data is
>   fixed (`sameAs`, salary, no `applicantLocationRequirements`); BreadcrumbList, related jobs, a tracked Apply
>   button on job pages, a favicon, UTM tags on emails, and the expired welcome modal removed.
> - §7: the scraper is split into `core.py`, `summaries.py` and `sites/<institution>.py`, with 71 tests and a CI
>   workflow. Also: XSS escaping, a `jobs-lite.csv` first paint, the Supabase SDK pinned with SRI, pinned
>   dependencies with caching, `-X theirs`, a timeout, concurrency control, HKT everywhere, the README updated and
>   the dead workflow deleted.
>
> Verified by a full live run on GitHub's runners (27 Sep):
> - 16 of 17 institutions returned their usual counts. HSU was flagged "partial" because it removed 7 jobs; their
>   links now return 404.
> - Only genuinely new jobs were flagged NEW.
> - A second page build wrote 0 files, and all JSON-LD parses.
> - Real Claude calls (direct and batch) returned structured summaries.
> - Every Apply link opened, except HSU's 7 removed jobs.
>
> **Still open (not growth):**
> - Summaries are reused per job id. They aren't refreshed when an ad is edited, although the listing's deadline
>   always wins. A job that vanishes while its portal is healthy is re-summarised when it returns. The §2.3 content-hash
>   store would cover both.
> - `date_posted` is still empty for several portals, and JSON-LD has no organisation `logo`.
> - §7 performance ideas (a shared Playwright browser, condition waits everywhere, concurrent scraping) are less
>   urgent now that a run takes ~10 minutes. Deploying `/jobs` with `actions/deploy-pages` instead of committing HTML
>   is optional, since pages now change only when jobs do.
> - Outside the code: mark `apply_click`, `alert_subscribed` and `sign_up` as GA4 key events and build the funnel.
>   In Search Console, resubmit the sitemap and watch the Job Posting report as pages are re-crawled.
> - §8 growth items, apart from Google for Jobs eligibility and related-jobs links, which are done.
---

## Scorecard

| # | Area | Status | Headline |
|---|------|:-----:|----------|
| 1 | Daily scraping & failure alerting | 🔴 | All 100 recent runs show ✅, yet **48 of 170 days had ≥1 institution silently under-scraped**. THEi has failed on **every run since ~7 Aug**. Nothing alerts. |
| 2 | Claude summaries & caching | 🟠 | Summary quality is generally good, but caching leaks: **62% of 13,870 summaries since April were regenerations** of jobs that already had one (one HKUST job was summarised 171 times). |
| 3 | CSV field accuracy | 🟠 | No posting-date-as-deadline swaps found. However: **216 deadlines are free text**; CPCE's *screening* date is treated as a deadline (23 of 29 live posts dropped); `salary`/`start_date` are empty on 100% of rows. |
| 4 | Email alerts | 🔴 | **28 of 29 subscriptions are skipped on every run** (a bug since 13 May). The *Area* filter can never match. **The Unsubscribe link does nothing.** 48% of "new" jobs are not new. |
| 5 | Deep links to universities | 🟠 | **106 of 159 HKUST apply links point to an internal PeopleSoft host that refuses public connections.** SFU and Chu Hai link to shared listing pages. |
| 6 | Analytics & SEO | 🟠 | `robots.txt` blocks the CSV the homepage renders from, so Google sees an empty homepage. **33% of JobPosting pages have invalid or expired `validThrough`.** No landing pages or Chinese version. |
| 7 | Codebase | 🟡 | A 3,109-line single-file scraper with no tests and unpinned dependencies. One dead daily workflow. The repo pack is 276 MB because every commit rewrites ~1,400 pages. |
| 8 | Growth | — | See §8. The top lever is making alerts and "NEW" trustworthy, then Google for Jobs and programmatic landing pages. |

---

## Top 10 fixes (ranked by impact ÷ effort)

| # | Fix | Where | Effort |
|---|-----|-------|:-----:|
| 1 | Make alert emails reach subscribers again (set `alert_enabled` when alerts are turned on at save time, and backfill existing rows) | `index.html:1429-1436, 2805, 2925`; Supabase | S |
| 2 | Restore the `?unsubscribe=<token>` handler and add a `List-Unsubscribe` header | `index.html`, `notify.py:216` | S |
| 3 | Stop false "NEW" flags: keep a persistent `first_seen` registry, and fall back to yesterday's rows on *partial* failures, not just zero | `scraper.py:3000, 3032-3045` | M |
| 4 | Fix the HKU "More Jobs" loop (wait for the row count to grow and validate against the button's own count) | `scraper.py:981-1024` | S |
| 5 | Add a scrape health gate: compare per-institution counts to a 7-day median, then fail the run or open an issue or email the owner | new `scraper/health.py`, `scrape.yml` | S |
| 6 | Make alert matching mirror the site (area → academic area, dept groups, phrase search) and add a "sent" log so nobody is emailed twice | `notify.py:155-186` | S |
| 7 | HKUST: fix the cache-invalidation bug ~~and stop publishing PeopleSoft links~~ (the links work; see §5) | `scraper.py:1207-1212` | S |
| 8 | Normalise deadlines (no free text in `deadline`), fix CPCE screening date, fix JSON-LD `validThrough` | `scraper.py:186, 2383`; `generate_job_pages.py:163-175` | S |
| 9 | Pre-render the latest jobs into `index.html` at build time, or unblock `/jobs.csv` for Googlebot | `generate_job_pages.py`, `robots.txt:3` | S–M |
| 10 | Repair the THEi scraper (broken ~7 weeks, serving 25 stale jobs) | `scrape_thei()` | M |

---

## 1. Daily scraping: accuracy and unalerted failures

### 1.1 What the data shows

Each institution's count on each day was compared with its median over the previous 7 days. A drop below 70% was
counted as an **under-scrape**:

| Institution | Days under-scraped (1 Apr → 26 Sep) | Worst day |
|---|:--:|---|
| HKU | 15 | 8 Jun: **18** jobs vs median 399 |
| HKU SPACE | 11 | 26 Apr: 9 vs 29 |
| CUHK | 6 (plus a 2-week half-outage) | 13 Aug: 24 vs 168. From 30 Jul to 13 Aug it served ~120 of ~250 jobs. |
| VTC | 4 | 23 May: 25 vs 42 |
| Chu Hai | 4 | 20 Aug: 7 vs 11 |
| HKMU | 2 | 21 Jul: 40 vs 65 |
| THEi | *masked* | Scraper crashes daily; the fallback has served the same 25 rows since ~7 Aug |

**48 of 170 scrape-days (28%) had at least one institution under-scraped.** Yet **all 100 workflow runs show "success"**,
because the scraper never exits non-zero and the notify step has `continue-on-error: true`.

The latest run (26 Sep) is one of these days: HKU loaded 199 of ~370 jobs. Unless a job genuinely closed, expect
roughly 170 HKU jobs to return as false "NEW" on the next good run.

### 1.2 Root causes (verified in logs)

- **HKU: the "More Jobs" loop quits early** (`scraper.py:984`, `1021`). After each click it waits a fixed 1.5 s and
  stops as soon as the row count hasn't grown. From the 21 Sep log:
  ```
  ↳ Found button: 'More Jobs 362' (~362 jobs remaining to load)
  ↳ No new rows after click 1 (still 42), stopping
  ✅ HKU: 20 jobs found
  ```
  The button reports how many jobs remain, but that number is never used to check completeness. On good days the
  loop instead runs 262–501 clicks (hitting the 500 cap on 14 Aug, with 9,561 rows), which costs 10–17 minutes.
- **The fallback only triggers when a scraper returns exactly 0 jobs** (`scraper.py:3000`). A partial result (20 of
  380) is accepted as truth.
- **CUHK** (`scraper.py:1659-1664`): if one of the two Taleo sections times out, it is skipped and the other section's
  jobs are returned. That is the cause of the 2-week half-outage.
- **THEi**: every sampled log since 14 Aug shows
  `THEi scraper failed: Page.evaluate: TypeError: Cannot read properties of null (reading 'click')`
  (or a `Page.goto` timeout). The fallback keeps 25 old rows with no deadlines, some first seen in **March**. They
  stay live on the site, in the sitemap and in Google for Jobs indefinitely.
- **HKBU**: `Direct API failed (400 Client Error …recruitingCEJobRequisitions…)` on every run. The Playwright fallback
  still works, but it is slower and fragile.
- **Other fixed 1.5 s waits** are used by Lingnan (`scraper.py:876`), which has 49% false-NEW, and THEi (`:2776`).

### 1.3 Knock-on effects of partial failures

The NEW flag has only one day of memory: a job is "new" if its ID wasn't in *yesterday's* CSV
(`scraper.py:3032-3045`). Whenever a job drops out and returns, it is:

- re-flagged **NEW**, with `date_added` reset to today. That breaks the NEW badge, the "Posted within" chips and the
  "Newest" sort (`index.html:1655-1660, 2050-2056`);
- **emailed to subscribers again** (see §4);
- **re-summarised by Claude**, because its cached summary left with the row (see §2);
- **deleted from `/jobs/` and the sitemap and then recreated**, which creates 404 churn for Google (see §6).

**Since 1 April, 10,006 NEW flags were issued and 4,808 (48%) were jobs the site had already listed.** By institution:
HKU 72%, HKU SPACE 62%, CUHK 61%, Lingnan 49%, THEi 35%. The biggest days were 24 Jul (383 of 456), 21 Jun (383 of 384),
13 Jun (366 of 367) and 22 Sep (333 of 350).

### 1.4 Schedule and workflow

- The cron is `0 18 * * *` (02:00 HKT), but **runs usually start between 18:27 and 22:33 UTC**, 0.5–4.5 hours late.
  Three ran 6–8 hours late (6 Aug 23:58, 29 Aug 01:28, 28 Aug 02:03 UTC). The site therefore usually refreshes around
  04:30–07:00 HKT, not 02:00. Scheduled jobs set on the hour are the most delayed on GitHub. Use an off-peak minute such
  as `17 17 * * *`.
- `git rebase -X ours origin/main` (`scrape.yml:66`): during a rebase, *ours* means the upstream side. On a conflict
  this **discards the bot's fresh data**. It should be `-X theirs`.
- There is no `timeout-minutes` and no `concurrency:` group. A manual dispatch can race the scheduled run.
- `deploy-lecturer-rename.yml` is a one-time job for **9 March** that still runs every day. Delete it.
- `pip install` has no pinned versions. A breaking Playwright or Anthropic release would fail silently, as above.

### 1.5 Recommendations

1. **A health gate after scraping** (`scraper/health.py`). For each institution, compute `count / median(last 7 days)`
   and also check HKU's own "More Jobs N" total. Write `scrape_health.json`. If any ratio is below 0.7 or a scraper
   raised an exception: fall back to yesterday's rows *for that institution*, keep going, then make the workflow **fail
   at the end** (GitHub emails you) or open or update a GitHub issue. Optionally send yourself a Resend email with the
   table.
2. **A persistent job registry** (`data/seen_jobs.json`: `id → first_seen, last_seen, summary_hash`). A job is NEW only
   if it has never been seen, and a job absent for fewer than 14 days keeps its `date_added`. This single change fixes
   false NEW flags, false alerts, summary regeneration and page churn.
3. **HKU**: replace the loop with `page.wait_for_function("n => document.querySelectorAll('tr').length > n", prev, timeout=15000)`
   and retry twice before stopping. Stop when parsed jobs ≥ the button's announced total. Also check whether PageUp's
   listing RSS or JSON endpoint (`/en/listing/rss`) can replace clicking entirely.
4. **CUHK**: retry a timed-out section once. If a section still fails, treat the whole institution as failed so the
   fallback applies.
5. **THEi**: fix the selector that returns `null`, and add a max-age (e.g. 30 days) for rows served by the fallback.

---

## 2. Claude summaries: accuracy and caching

**Model**: `claude-haiku-4-5-20251001` is still active; pricing is $1 input / $5 output per million tokens.

### 2.1 Accuracy (spot-check of all 1,338 current AI summaries)

- The format is consistently followed. Only about **2% of summaries** (24) are all "Not specified", 4 say
  "Not specified in the provided description", and 5 mention the university name against the prompt's instruction.
- **HKMU: 22% of summaries have an empty Requirements section.** The input is truncated before the requirements.
  Scrapers keep only the first 15–20 lines longer than 60 characters, capped at 2,000–3,000 characters
  (`scraper.py:332` and each scraper), while Haiku accepts 200K tokens.
- **60% of summaries (798) show `Key Dates: Not specified`**, because the closing date is on the listing page, not in
  the text Claude sees. The detail panel then shows "Not specified" next to a real deadline.
- **Summaries are never refreshed.** When a university extends a deadline or edits an ad, the cached summary keeps the
  old dates. For VTC, **10 of 19 rows** where both exist show a different closing date in the summary than in the
  deadline column (e.g. `VTC-01b5bfa72a`: column 31 Oct, summary 30 Jul).

### 2.2 Caching: three leaks

| Leak | Evidence | Fix |
|---|---|---|
| **HKUST: cache wiped on every run.** The Interfolio URL is compared with the PeopleSoft URL scraped seconds earlier, not with yesterday's stored URL, so they always differ and `_existing_descriptions.pop()` fires (`scraper.py:1207-1212`). | **4,008 of 4,088** HKUST summaries were regenerations; one job was summarised **171 times**. | Compare with `existing[id]['apply_url']` from the previous CSV. |
| **Flapping jobs lose their summary** because the cache is "yesterday's CSV" | HKU: 3,405 regenerations. The 22 Sep recovery run re-summarised 328 HKU jobs and took 90 min. | Persistent summary store keyed by `(id, sha256(raw_text))`, independent of the CSV |
| **VTC is summarised twice.** The scraper summarises inline (`:2314`), then `main()` sees a long, uncached description and summarises the summary again (`:3072`). | Every new VTC job | Mark rows summarised in the scraper, or remove the inline call |

**Totals since 1 April: 13,870 summaries generated, of which 8,664 (62%) were regenerations.** At roughly 1,100 input
and 260 output tokens per call, that is about $30–35 of Haiku spend over 6 months, with ~$20 wasted. The money is small.
The real costs are run time (recovery days take 83–110 min) and summaries that drift from the source.

### 2.3 Recommendations

1. Keep the summary cache in `data/summaries.json` keyed by content hash. It then survives drop-outs and refreshes
   automatically when the ad changes.
2. Switch to **structured outputs** (a JSON schema) that return `duties[]`, `requirements[]`, `contract`, `salary`,
   `start_date`, `closing_date`, `phd_required`, `rank_hint`. That fills the empty `salary` and `start_date` columns,
   backfills missing deadlines (e.g. HSU's 2 rows) and lets you render Key Dates from real fields.
3. Pass the known deadline into the prompt, or drop "Key Dates" from the free text, so the two can't disagree.
4. Use the **Message Batches API** (50% cheaper). Nothing about this job is latency-sensitive. Also log `usage` tokens
   per run.
5. Raise the input cap (e.g. 12k characters) and extract the content region rather than "first N long lines".

---

## 3. CSV field accuracy

### 3.1 Posting date vs deadline: no swap found ✅

**0 rows** have `deadline < date_posted` or `deadline == date_posted`, and no deadlines fall after mid-2027. The
example you raised (posting date used as deadline) does not occur. Related misalignments do, though:

### 3.2 Issues found

| Issue | Rows | Cause |
|---|---|---|
| Free text in `deadline` | **216**: CityU 174 ("Applications will be considered until the position(s) is/are filled"), EdUHK 24 (`"N"`), HKU SPACE 18 ("on-going recruitment") | `parse_date_text()` returns the raw text when it can't parse (`scraper.py:186`). This breaks deadline sort and produces invalid JSON-LD (§6). |
| **CPCE "Initial screening date" treated as deadline** | CPCE finds **29** posts on 26 Sep but keeps **6** | `scraper.py:2383`. Screening dates pass while the post stays open, so the 14-day retention drops live jobs. |
| CPCE `position_type` = portal section ("Academic", "General", "Research") instead of Full/Part-time | all CPCE | `scraper.py:2400` |
| Summary closing date ≠ deadline column | VTC 10/19, HKU 2, PolyU 1, HKUST 1, CUHK 1 | Stale cached summaries (§2) |
| Closing date in summary but column empty | HSU 2, Lingnan 1, HKBU 1, HKUST 1 | Not backfilled from the summary |
| `salary`, `start_date` empty | **100% of 1,454 rows** | Never extracted. The README says "where available". |
| `date_posted` only filled for PolyU and EdUHK | 1,204 rows empty | Other portals do show a posting date |
| `date_added` unreliable | see §1.3 | Reset by flapping |
| Rank `"Lecturer"` (4 rows) can't be filtered | 4 | The UI option was renamed to "Senior Lecturer/Lecturer", but `detect_rank()` still returns "Lecturer" for teaching-track / faculty cases (`scraper.py:111-112`) |
| HKU detail-fetch priority uses outdated rank labels | — | `RANK_PRIORITY` lists "Senior Lecturer", "Lecturer", "Instructor" (`scraper.py:1035-1038`) |

**Deadline coverage has regressed against the README**: SFU is documented as "listed in accordion" but is now at
**0%**; HKSYU is documented as "listed on vacancy page" but is at **3%**; CUHK is 10%, HKUST 7%, HKBU 0%, Lingnan 0%.

### 3.3 Recommendations

- Change `parse_date_text()` to return `""` when it can't parse, and store the text in a new `deadline_note` column.
  Show "Until filled" in the UI.
- CPCE: store the screening date as `review_date` and keep jobs until they leave the portal.
- Backfill `deadline`, `salary` and `start_date` from the structured Claude extraction (§2.3).
- Add a CSV schema test in CI that checks ISO dates, the allowed `position_type` values and the allowed ranks.

---

## 4. Email notifications for logged-in users

### 4.1 Alerts effectively stopped on 13 May 🔴

Every sampled run that had new jobs (14 Aug, 18 Sep, 21 Sep, 22 Sep) logs:
```
Subscriptions: 29
Skipped 28 subscription(s) with alerts toggled off
Subscribers with matches: 1   →  ✅ Sent to <owner> (…)
```

The chain of causes:

1. The main flow, *Save filter with 🔔 alerts on* (`confirmSaveFilter`, `index.html:1429-1436`), calls
   `saveFilter()` and then immediately `toggleFilterAlert()`. At that moment the new filter has no `dbId` yet.
2. `toggleFilterAlert()` inserts the `subscriptions` row, but only updates `saved_filters.alert_enabled` when there is
   a `dbId` (`index.html:2925`), so it skips the update.
3. The background sync upserts the filter with `alert_enabled: false` and `ignoreDuplicates: true`
   (`index.html:2805`), so later syncs never correct it.
4. On reload the UI still shows alerts **on**, inferred from the `subscriptions` row (`index.html:2871-2874`).
5. Since the 13 May fix (commit `3768032`), `notify.py` treats `saved_filters.alert_enabled` as the source of truth
   and drops these subscriptions (`notify.py:108-121`).

So subscribers see alerts enabled but receive nothing. Turning alerts *off* deletes the subscription row, which means
the 28 remaining rows are almost certainly users who want alerts. Confirm in Supabase:
```sql
select s.email, s.filter_label, f.alert_enabled, f.filter_state->>'_alertEnabled' as embedded
from subscriptions s
left join saved_filters f on f.user_id = s.user_id and f.label = s.filter_label;
```

The embedded `filter_state._alertEnabled` is written as `false` by the same background sync, so it can't be used as a
fallback signal. The fix:

1. **One-off backfill** (restores alerts immediately):
   ```sql
   update saved_filters f
   set alert_enabled = true,
       filter_state  = f.filter_state || '{"_alertEnabled": true}'::jsonb
   from subscriptions s
   where s.user_id = f.user_id and s.filter_label = f.label;
   ```
2. **Correct the write path** in the UI. When alerts are toggled, update `saved_filters` by `(user_id, local_id)` when
   there is no `dbId` yet, rather than skipping. Or `await` the filter upsert, take its id, then toggle.
3. In `notify.py`, print the number of skipped subscriptions *per reason* and warn loudly when more than half are
   skipped, so this failure can't hide again.

### 4.2 Other alert defects

| Defect | Where | Impact |
|---|---|---|
| **The Unsubscribe link does nothing.** `?unsubscribe=` handling was removed in the 29 Mar revert and never restored. Legacy email-only subscribers have *no* way out. | `notify.py:216`; no handler in `index.html` | Compliance risk (HK UEMO; Gmail/Yahoo bulk-sender rules). Recipients will mark mail as spam, which hurts deliverability. |
| **The Area filter never matches.** The UI stores an academic area ("Medicine & Health", from `classifyArea(department)`), but `notify.py` compares it with `position_type` ("Full-time"). BACKLOG item 3.3 wrongly describes this dropdown as `position_type`, which is likely where the mismatch came from. | `notify.py:175-176` vs `index.html:1932` | Every alert with an area set gets zero emails |
| Department-group chips ignored | `notify.py` | Alerts over-match |
| Different search semantics: the site matches the whole phrase plus university names; `notify.py` matches all words and ignores university fields | `index.html:1928` vs `notify.py:183` | "HKU" or "machine learning" alerts behave differently from the site |
| 48% of "new" jobs aren't new (§1.3) | — | 22 Sep: 350 "new" jobs, of which 333 were old |
| No per-recipient sent log | — | The same job can be emailed repeatedly as it flaps |
| Job titles link to the homepage, not the job; no UTM tags | `notify.py:230` | Lost deep-link conversions; email traffic can't be attributed in GA4 |
| HTML not escaped (`{j['title']}`, filter label) | `notify.py:230` | Broken emails on `&`/`<` |
| The date uses the runner's UTC date, not HKT | `notify.py:217` | The email is dated "yesterday" |
| Runs before job pages are generated and pushed | `scrape.yml` | Links can 404 for a few minutes |
| `continue-on-error: true` and per-email failures only printed | `scrape.yml:40` | Failures are invisible |
| `subscriptions?select=*` with no pagination | `notify.py:90` | Silently capped at 1,000 rows |

---

## 5. Deep links to university job details

| Institution | Link type | Assessment |
|---|---|---|
| PolyU, HKU, CUHK, HKMU, LU, HKBU, VTC, CPCE, HKU SPACE, HSU, THEi | Per-job detail page | ✅ Correct pattern |
| **HKUST** | 53 Interfolio ✅ / 106 `hrmsxprod.psft.ust.hk:8044` PeopleSoft | ✅ **Correction (27 Sep):** these are the links HKUST's own careers page uses. From GitHub's runners they return HTTP 200, and the weekly link check found all 158 HKUST links working. The earlier connection refusal came from the network this audit ran from, not from HKUST. |
| SFU | 30 jobs → 3 listing pages | 🟠 Not a deep link |
| Chu Hai | 4 of 5 jobs share one URL | 🟠 |
| CityU | Listing page + `?ref=` | 🟡 Check that the ref anchors or opens the job |
| EdUHK, HKSYU | PDF job ads | 🟡 Works, but there is no application link |
| CUHK | 1 job falls back to the careers home page | 🟡 |

**On-site links:**
- The `?job=<id>` deep link silently does nothing if the job is gone (`index.html:1833-1843`). Show "This position has
  closed" with similar jobs instead.
- `/jobs/<slug>-<id>/` pages are **deleted** when a job leaves the CSV (`generate_job_pages.py:504`). Every shared link,
  bookmark and Google result for a closed or flapping job then becomes a 404. Keep a "closed" version with `noindex`
  for about 60 days.

**Recommendation:** add a weekly link-checker workflow that sends a HEAD or GET to every `apply_url` from GitHub's
runners and writes broken links to the health report. For HKUST, use the public careers page URL with the Job ID
when there is no Interfolio link.

---

## 6. Analytics and SEO

### 6.1 Working well ✅

- GA4 with 12 custom events: `apply_click` in the table and panel, `search`, `search_no_results`, `filter_*`,
  `job_detail_viewed`, `alert_subscribed` and more.
- Per-job static pages with a canonical URL, OG/Twitter tags and JobPosting JSON-LD.
- Sitemap, Search Console verification, and a good meta description.

### 6.2 Gaps

| Gap | Evidence | Fix |
|---|---|---|
| **Googlebot sees an empty homepage.** `robots.txt` has `Disallow: /jobs.csv`, and the homepage renders every job from that file with JS. Google honours robots.txt for resources fetched while rendering. | `robots.txt:3`, `index.html:610` | Pre-render the newest ~50 jobs (links to `/jobs/…`) into `index.html` at build time. Or remove the disallow; a CSV rarely ranks. |
| **459 of 1,378 job pages (33%) are ineligible for Google for Jobs**: 216 have `validThrough` like `"Applications will be…T23:59:59+08:00"`, and 243 have a 90-day fallback already in the past | `generate_job_pages.py:163-175` | Only emit valid ISO dates. For "until filled", roll `validThrough` forward (e.g. today + 30) each day. |
| `hiringOrganization.sameAs` points to hkacadjobs.org; no `logo` | `:152` | Use each university's site and logo |
| `applicantLocationRequirements` is meant for remote jobs; `baseSalary` shape is non-standard | `:180-191` | Remove, or fill correctly from structured salary |
| **Every page changes every day.** The footer says "data as of {TODAY}", every sitemap `lastmod` is today, and the folder is rebuilt from scratch | `:470, 484-491, 504` | Stable pages; real `lastmod` from `date_added` or content hash; write only changed files |
| 109 pages have thin placeholder descriptions | — | Improve extraction (§2) |
| No static `<link rel="canonical">` on the homepage (JS-only); **no favicon** at all | `index.html` head | Add both |
| **No landing pages** for institutions, ranks, disciplines or "closing this week" | — | See §8. This is the biggest organic lever. |
| No related-jobs links or `BreadcrumbList` schema on job pages | — | Adds internal links and crawl depth |
| English only; no `hreflang` (BACKLOG 1.1 still open) | — | Traditional Chinese, plus Simplified for mainland PhDs |
| **Static job pages don't track Apply clicks.** Most organic visitors land there | `generate_job_pages.py` template | Add the `apply_click` event (`source: static_page`) |
| Email traffic has no UTM tags and is untracked | `notify.py` | `?utm_source=alert&utm_medium=email` |
| No GA4 key-event or funnel defined (BACKLOG 6.x) | — | Mark `apply_click`, `alert_subscribed` and `sign_up` as key events |
| Welcome modal expired 10 Apr (dead code) | `index.html:2716` | Remove |

---

## 7. Codebase optimisation

**Reliability and maintainability**
- `scraper.py` is 3,109 lines holding 17 scrapers. Split it into `scraper/sites/<uni>.py` with a shared `BaseScraper`
  (fetch, retry, wait-until, parse, validate) and a shared Playwright browser. Currently `get_js_soup()` launches a new
  browser per URL, and most scrapers launch their own.
- Replace fixed `wait_for_timeout()` sleeps with condition waits (`wait_for_function` / `wait_for_selector`).
- **Unnecessary detail-page fetches every day**: CUHK (`:1742`) and HKBU (`:1584`) fetch *every* job's detail page on
  every run because the listing has no deadline and the previously found deadline isn't reused. Cache deadlines from
  the previous CSV.
- Scrape institutions concurrently (thread pool or asyncio). Runs take 25–110 min today, and serial Playwright is the
  bottleneck.
- `python scraper.py --uni hku` (as the README suggests) **overwrites `jobs.csv` with HKU only** (`:2984`). Merge with
  the existing rows, or write to a separate file.
- No tests exist. Add fixture-based parser tests per institution (saved HTML), plus a parity test that runs the same
  filter cases through `index.html`'s logic and `notify.py`, or move matching to one shared spec.
- Pin dependencies in `requirements.txt`, and cache pip and Playwright browsers in Actions.

**Frontend**
- **XSS hardening:** scraped `title`, `department`, `apply_url` and descriptions are placed into `innerHTML` unescaped
  (e.g. `index.html:2181`, `2303-2327`) on a page holding a signed-in Supabase session. Add an `esc()` helper, and allow
  only `http(s):` apply URLs.
- `jobs.csv` is 1.8 MB (≈330 KB gzipped), and **77% of it is descriptions**. Ship a slim `jobs-index.json` and
  lazy-load descriptions per job (BACKLOG 2.1).
- The Supabase SDK is render-blocking and pinned only to `@2` (`index.html:63`). Add `defer`, pin an exact version and
  add SRI, or lazy-load it on sign-in (BACKLOG 2.x).

**Repository hygiene**
- The git pack is **276 MB after ~6 months**. Each daily commit rewrites ~1,400 pages (about 60–100k line deletions)
  only because of the footer date. Removing that date and writing only changed files cuts growth dramatically. Longer
  term, deploy `/jobs` via `actions/deploy-pages` instead of committing generated HTML.
- Delete `deploy-lecturer-rename.yml`. Change `-X ours` to `-X theirs`. Add `timeout-minutes` and `concurrency`.
- Use one timezone everywhere: `notify.py` and `generate_job_pages.py` use UTC `date.today()`, while the scraper
  uses HKT.
- Update the README: the deadline coverage table, the "New badge for 2 days" claim, and the `jobs.csv` gitignore note.

---

## 8. Growth: more job-seekers, more returning users

**Fix trust first.** The retention loop (alerts) has been silently broken for four months, and half of all "NEW"
badges are wrong. Anyone who tried alerts has likely churned. Items 1–6 in the Top 10 are growth work.

### 8.1 Acquisition

1. **Google for Jobs eligibility** (fix §6 JSON-LD). This is free, high-intent traffic, and HK university postings
   compete poorly there because universities rarely publish good schema.
2. **Programmatic landing pages**, generated nightly by `generate_job_pages.py`:
   - `/hku/`, `/cuhk/` … (one per institution)
   - `/postdoc-jobs-hong-kong/`, `/assistant-professor-jobs-hong-kong/`, `/research-assistant-jobs-hong-kong/`
   - `/computer-science-jobs-hong-kong/` and other disciplines (the site already has `AREA_GROUPS`)
   - `/closing-this-week/`, `/new-this-week/`

   Each gets a unique intro, live counts, `ItemList` schema, and links to job pages. These match how people actually
   search.
3. **Chinese-language versions** (Traditional for local staff, Simplified for mainland PhD and postdoc candidates, a
   large applicant pool). Job titles stay as posted; UI, landing pages and summaries can be translated by Claude at
   build time.
4. **Automated social distribution**: a daily post of "N new academic jobs in HK today" (top 5 by rank) to a LinkedIn
   page, X/Threads/Bluesky and a **Telegram/WhatsApp channel**, plus RSS/Atom feeds per institution and discipline.
   It's cheap to add to the existing workflow.
5. **Partnerships and backlinks**: postdoc associations at each university, the HKPFS community, research offices,
   graduate schools, EURAXESS, and subreddits such as r/AskAcademia and r/PhD. Offer an embeddable "latest jobs at
   <dept>" widget that departments can put on their sites.
6. **Evergreen content** (BACKLOG 1.x): HK university salary scales, how hiring works at each university, visas
   (GEP/IANG), tenure-track timelines, and an RGC funding calendar. Draft with Claude and review by hand.

### 8.2 Engagement and retention

7. **One-field "email me all new jobs" signup** with double opt-in and no account needed (BACKLOG 5.1, reverted in
   April). Put it back once alerts work.
8. **Weekly digest**: every Monday, send the top matches for each saved filter, including weeks with no daily match.
9. **"Closing soon" reminders** for saved jobs (3 days and 1 day before the deadline).
10. **Change tracking**: "Deadline extended" and "Re-advertised" badges, a natural result of the registry in §1.5.
11. **Richer filters** from structured extraction: salary band, contract length, PhD required, start date, "open until
    filled".
12. **Similar jobs** in the panel and on static pages, plus a per-job share button (BACKLOG 4.x).
13. **PWA with web push notifications** as an alternative to email.

### 8.3 Measurement

- A weekly owner email (from the workflow) with visitors, apply clicks, new subscribers, emails sent, per-institution
  scrape health and broken links.
- A GA4 funnel: landing → search/filter → `job_detail_viewed` → `apply_click` → `alert_subscribed`.
- Check in Search Console: pages indexed vs submitted, Job Posting enhancement errors (expect ~459), and queries by page.

### 8.4 Suggested sequencing

| Window | Focus |
|---|---|
| **Week 1** | Top-10 items 1, 2, 4, 5, 6, 7, 8 (mostly S). Delete the dead workflow. Backfill `alert_enabled`. |
| **Weeks 2–4** | Job registry and summary cache (items 3 and §2.3), THEi and CUHK robustness, JSON-LD fixes, stable pages and sitemap, pre-rendered homepage. |
| **Month 2** | Landing pages, social auto-posting and RSS, the "all new jobs" signup, weekly digest, UTM and GA4 key events. |
| **Month 3** | Chinese versions, structured fields and new filters, closing-soon reminders, scraper refactor with tests. |
