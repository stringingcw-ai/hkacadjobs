# HKAcadJobs

> Every university opening in Hong Kong, in one place.

A static job board aggregating academic and university positions from 17 Hong Kong institutions, updated daily via GitHub Actions. No login required, no paywalls — just a fast, searchable list of open positions pulled straight from official university career portals.

**Live site:** https://www.hkacadjobs.org/

---

## Institutions covered

| Code | Institution |
|------|-----------|
| HKU | University of Hong Kong |
| CUHK | Chinese University of Hong Kong |
| HKUST | HK University of Science & Technology |
| PolyU | Hong Kong Polytechnic University |
| CityU | City University of Hong Kong |
| HKBU | Hong Kong Baptist University |
| LU | Lingnan University |
| EdUHK | Education University of Hong Kong |
| HKMU | Hong Kong Metropolitan University |
| HSU | Hang Seng University of Hong Kong |
| SFU | Saint Francis University |
| HKSYU | Hong Kong Shue Yan University |
| VTC | Vocational Training Council |
| HKUSPACE | HKU School of Professional and Continuing Education |
| CPCE | HKCC / SPEED — College of Professional and Continuing Education (PolyU) |
| HKCHC | Hong Kong Chu Hai College |
| THEI | Technological and Higher Education Institute of Hong Kong |

---

## Features

- **Daily refresh** — scraper runs at about 01:40 HKT every day via GitHub Actions
- **New badge** — positions flagged as NEW on the day they first appear; a job that briefly drops off a portal and comes back is not NEW again (see *Job registry* below). The count matches the "New Today" header stat exactly
- **Job alerts** — signed-in users can turn on email alerts for a saved filter; alerts link to each job's page and never repeat a job
- **Smart sort** — new jobs float to the top; results then sorted by academic area (Medicine & Health → Engineering → CS & AI → Science → Business → Arts → Social Sciences → Education → Law → Architecture → Administration), then by institution and date
- **Search & filter** — keyword search plus multi-select institution and rank filters, role type toggle (Academic / Non-Academic), and cascading area → department group chips
- **Rank filter sync** — selecting Academic hides Non-Academic from the rank list; selecting Non-Academic locks rank to Non-Academic automatically
- **Active filter chips** — dismissible pills show every active filter; inline ★ Save filter button appears after the last chip; filters reflected in the URL for shareable links
- **Save filter** — apply any combination of filters and click the star icon to name and bookmark that search; saved filters appear as cards in the Saved tab
- **Share saved filter** — each saved filter card has a Share button; uses native share sheet on mobile, copies URL to clipboard on desktop
- **Saved tab** — dedicated view showing saved positions and saved filter cards; search and filter bar hidden for a cleaner browse experience
- **Action toasts** — brief confirmation toast shown when saving or removing a position or filter, and when applying a saved filter
- **Sortable deadline column** — click the Deadline header to sort; N/A deadlines sorted last
- **Detail panel** — click any row for full job info and a dynamic apply link (e.g. "Apply on PolyU")
- **Results banner** — shows the number of positions matching current filters
- **Deadline tracker** — colour-coded reminder badge: yellow for upcoming deadlines, red for closed
- **University logos** — each listing shows the university favicon for quick identification
- **Mobile responsive** — card layout on small screens; collapsing filter bar collapses on scroll with GPU-accelerated animation
- **Animated hero stats** — Open Positions and New Today count up on page load with ease-out deceleration
- **New institution toast** — one-time dismissible toast notifies users when a new institution is added
- **AI summaries with labelled key dates** — each job summary extracts and labels all dates found on the detail page (closing date, review date, start date etc.)

---

## Deadline coverage

`deadline` only ever holds a date (`YYYY-MM-DD`). Wording such as "open until filled", "ongoing recruitment" or
"applications reviewed from 15 Oct" goes to `deadline_note`, which the site shows instead of a date. A review or
screening start date is never treated as a closing date. When a listing has no date, the closing date that the AI
summary finds on the job page fills the gap; when both exist, the listing wins and the summary is corrected.

| University | Deadline source |
|---|---|
| PolyU, CityU, HKMU, HKSYU, HKU SPACE, VTC | Listing page |
| HKU | Listing page (most jobs) |
| HKBU, Lingnan | The careers site's own job API |
| CUHK | Taleo detail pages; known deadlines are reused and missing ones re-checked weekly |
| HKUST, HSU, Chu Hai, THEi | Detail pages (partial) |
| EdUHK | PDF job ads (partial) |
| SFU | The *Deadline* line of each posting (a date or "until filled") |
| CPCE | Detail pages: the listed "screening date" is when review starts, so it becomes a note |

Jobs with a known deadline are retained for up to **14 days after expiry**, then dropped on the next scrape.

---|---|
| PolyU | Listed on search results page |
| CityU | Listed on search results page |
| HKU | Listed on search results page (most jobs) |
| EdUHK | Partial — varies by posting |
| HKUST | Partial — fetched from detail pages |
| HKBU | Partial — fetched from detail pages via Playwright |
| CUHK | Partial — fetched from Taleo detail pages via Playwright |
| HKMU | Listed on search results page |
| HSU | Partial — fetched from detail pages |
| SFU | Listed in accordion content |
| HKSYU | Listed on vacancy page |
| LU | Not published |

Jobs with a known deadline are retained for up to **14 days after expiry**, then dropped on the next scrape.

---

## Project structure

```
├── index.html          # Single-page frontend (HTML + CSS + JS, no build step)
├── cv-match.js         # "Find jobs that fit your CV": the site's side of CV matching, loaded on first use
├── cv-match.css        # …and its styles
├── vendor/             # pdf.js and mammoth, which read PDF and Word CVs in the browser (see vendor/README.md)
├── jobs.csv            # Job data — regenerated daily by the scraper (gitignored; force-added by workflow)
├── jobs-lite.csv       # jobs.csv without descriptions, for a fast first paint
├── jobs/               # One static page per job (/jobs/<slug>-<id>/), for search engines and alert links
├── sitemap.xml         # Homepage + open job pages, with each page's real last-changed date
├── robots.txt          # Allows crawlers (except the CSVs); points to the sitemap
├── favicon.svg
├── CNAME               # Custom domain configuration (www.hkacadjobs.org)
├── CHANGELOG.md        # Full update history by date
├── CV_MATCH_PLAN.md    # How CV matching was planned and built
├── CV_MATCH_LAUNCH.md  # CV matching: local review, and the owner's steps before launch
├── scraper/
│   ├── scraper.py      # Entry point: runs every institution, then NEW flags, deadlines, summaries → jobs.csv
│   ├── core.py         # Shared helpers: text cleanup, ranks, dates and deadlines, page fetching
│   ├── summaries.py    # AI summaries (Claude Haiku 4.5, structured output, Batches API)
│   ├── sites/          # One module per institution (hku.py, cuhk.py, …)
│   ├── generate_job_pages.py  # Job pages, closed-job pages, sitemap, jobs-lite.csv, homepage links
│   ├── notify.py       # Job alert emails (Supabase subscriptions → Resend)
│   ├── match_alerts.py # "Jobs that fit you" emails for saved CV profiles (run by notify.py)
│   ├── health.py       # Fails the daily run when a scraper under-delivers or alerts fail
│   ├── check_links.py  # Weekly check that every Apply link still opens
│   ├── wait_for_deploy.py     # Holds alert emails until GitHub Pages serves the new job pages
│   ├── patch_hku_descriptions.py  # Fills HKU descriptions the listing pages lack
│   ├── bootstrap_registry.py      # Rebuilds job_registry.json from git history (one-off)
│   ├── job_registry.json   # First/last day each job id was scraped (written by scraper.py)
│   ├── scrape_health.json  # Per-institution results of recent runs (written by scraper.py)
│   ├── pages_manifest.json # Each job page's status and last-changed date (written by generate_job_pages.py)
│   ├── alert_log.json      # Jobs already emailed to each subscription, keyed by a hash of its token
│   ├── requirements.txt    # Pinned Python dependencies
│   └── tests/          # pytest suite (python -m pytest scraper/tests)
├── supabase/           # One-off SQL to run in the Supabase SQL editor, and the Edge Functions
│   └── functions/match-jobs/  # CV matching service (Deno/TypeScript; see "CV matching" below)
└── .github/workflows/
    ├── scrape.yml      # Daily: scrape → pages → publish → wait for deploy → alerts → health check
    ├── check-links.yml # Weekly Apply-link check
    ├── tests.yml       # Lint + tests on every change to the scraper, site or functions
    ├── deploy-functions.yml  # Deploys supabase/functions when they change on main
    └── cv-match-eval.yml     # Manual: runs the test CVs through CV matching (Claude, ~US$0.45)
```

---

## Data format

`jobs.csv` columns:

| Column | Description |
|--------|-------------|
| `id` | Stable unique ID (e.g. `POLYU-260213012`) |
| `title` | Job title |
| `rank` | Detected rank: Senior Management / Professor / Associate Professor / Assistant Professor / Tenure-Track / Postdoctoral / Lecturer / Research Assistant/Associate / Teaching Assistant / Non-Academic / Other |
| `university` | Short code (e.g. `HKU`) |
| `university_full` | Full university name |
| `department` | Department or faculty |
| `deadline` | Application deadline (`YYYY-MM-DD`), or empty |
| `deadline_note` | Deadline wording when there is no date, e.g. `Open until filled` |
| `is_new` | `TRUE` on the day the job first appears; the site shows the New badge that day |
| `date_added` | Date the job was first scraped (`YYYY-MM-DD`, Hong Kong time) |
| `date_posted` | Date the institution posted it, where published |
| `reference` | University's internal reference number |
| `position_type` | Full-time / Part-time / Fixed-term |
| `salary` | Salary or grade (where available) |
| `start_date` | Expected start date (where available) |
| `apply_url` | Direct link to the application page |
| `description` | AI summary (`**Section**` + `•` bullets), or raw text until one is made |

---

## Running the scraper locally

```bash
# Install dependencies
pip install -r scraper/requirements.txt
playwright install chromium

# Scrape all universities
python scraper/scraper.py

# Re-scrape a single university (other institutions' rows are kept)
python scraper/scraper.py --uni hku

# Available university keys
# polyu, eduhk, lingnan, hku, hkust, cityu, hkbu, cuhk, hkmu, hsu, sfu, hksyu, vtc, hkuspace, cpce, chuhai, thei

# Build the job pages, sitemap and jobs-lite.csv
python scraper/generate_job_pages.py

# Run the tests
pip install pytest && python -m pytest scraper/tests
```

Set `ANTHROPIC_API_KEY` to generate AI summaries; without it, descriptions stay as raw text.

**Job registry:** `scraper/job_registry.json` records the first and last day each job id was scraped. A job that
drops off a portal and returns within 60 days keeps its original `date_added` and is not flagged NEW (or
re-alerted); one that returns after longer is treated as a new posting. Summaries are reused for known jobs, so
each job is summarised once.

---

## Deployment

The site is hosted on GitHub Pages from the `main` branch root under the custom domain **www.hkacadjobs.org**. No build step — `index.html` reads `jobs.csv` directly via `fetch()`.

The GitHub Actions workflow (`.github/workflows/scrape.yml`) runs the scraper daily, builds the job pages, commits the data and pages, and pushes — triggering an automatic Pages redeploy. It then waits for the new pages to go live, sends job alerts, and commits `scraper/alert_log.json` so nobody gets the same job twice. You can also trigger it manually from the Actions tab.

**Link check:** `.github/workflows/check-links.yml` opens every job's Apply link from GitHub's runners each Monday and fails (emailing you) when an institution has many broken links; the run page lists them.

**Scrape health:** each institution's result is compared with its usual job count (median of recent runs). If a scraper crashes, returns nothing, or returns under 70% of usual, the previous run's jobs for that institution are kept (so they don't reappear as "new" and get re-alerted), and the final *Check scrape health* step fails the run so GitHub emails you. Add a `HEALTH_ALERT_EMAIL` repository secret to also receive a Resend email with the details.

---

## CV matching

"Find jobs that fit your CV" is for signed-in users, and is the site's main reason to create an account. A user adds
a CV (PDF, Word or text, pasted text, or a link to a personal or academic web page), checks the profile Claude makes
of it, and sees the open positions that fit them best, each with a short reason. They can save the profile to get an
email when a new job fits. `CV_MATCH_PLAN.md` has the design; `CV_MATCH_LAUNCH.md` has the steps before launch.

- **On the site:** `cv-match.js` and `cv-match.css`, loaded the first time someone uses the feature (or when their
  browser already holds matches). Files are read in the browser with `vendor/`, and email addresses, phone numbers,
  ID numbers and details such as date of birth are removed before any text is sent. The latest profile and matches
  stay in the browser (`hkaj_match`) until sign-out. Bump `CV_MATCH_VERSION` in `index.html` whenever either file
  changes, so browsers fetch the new copy.
- **Who sees it:** everyone, while `CV_MATCH_PUBLIC = true` in `index.html`. Setting it to `false` hides it again;
  it then appears only after visiting with `?beta=match` (remembered in that browser; `?beta=off` forgets it).
- **The service:** `supabase/functions/match-jobs`, a Supabase Edge Function that accepts only signed-in users. It
  reads the CV or web page with Claude Sonnet 5.5 and builds a profile: field, specialisms, level, qualifications and
  languages. It then shortlists the 40 open jobs in `jobs.csv` whose wording best fits that profile, and asks Claude
  to rank them, with a reason and any gaps for each. `{"action": "profile", "text" | "url"}` returns the profile,
  and `{"action": "match", "profile", "prefs"}` returns up to 12 matches. The CV is never stored.
- **Match alerts:** after the filter alerts, `notify.py` runs `scraper/match_alerts.py`. It asks the function which
  of the day's new jobs fit each saved profile (`match_profiles`, only the institutions the user chose), and emails up
  to five, sharing the filter alerts' sent log and unsubscribe link. It also deletes usage records older than 90 days,
  as the privacy notice says.

**Setup (once):**
1. Run `supabase/2026-10-cv-match.sql` in Supabase → SQL Editor.
2. In Supabase → Edge Functions → Secrets, add `ANTHROPIC_API_KEY`. A key of its own makes the spend easy to follow.
3. Add the repository secrets `SUPABASE_ACCESS_TOKEN` (Supabase → Account → Access Tokens) and
   `SUPABASE_PROJECT_REF` (`xdlarqwycodfoahmkvha`), then run *Deploy functions* in the Actions tab. After that it
   deploys by itself whenever the function changes on `main`.
4. Set a monthly spend limit in the Anthropic Console as a hard stop.
5. Because the feature brings sign-ups, send Supabase's sign-in emails through your own SMTP server (Supabase →
   Authentication → Emails → SMTP settings; Resend works) and raise the email rate limit.

**Trying it locally:** run `python3 -m http.server 8000` in the repository and open
`http://localhost:8000`. It uses the live Supabase project, so the sign-in link must be allowed to come
back to your computer: add `http://localhost:8000/**` in Supabase → Authentication → URL Configuration → Redirect URLs.
Open it as `localhost`: the function turns away network addresses such as `192.168.…`.

**Limits and settings** (optional Edge Function secrets; days follow Hong Kong time):

| Secret | Default | Meaning |
|---|---|---|
| `USER_PROFILE_PER_DAY` | 3 | CV analyses per account per day |
| `USER_MATCH_PER_DAY` | 10 | Match runs per account per day |
| `DAILY_BUDGET_USD` | 10 | Site-wide Claude spend per day; matching pauses when it is reached |
| `ALERT_DAILY_BUDGET_USD` | 3 | Claude spend per day for match alerts |
| `MATCH_MODEL` | `claude-sonnet-5-5` | The Claude model |
| `MATCH_ENABLED` | `true` | `false` pauses matching |

**Cost:** about US$0.05 for a CV's profile and matches on Claude Sonnet 5.5 (measured 30 Sep), a little more from a web page link, and about US$0.02 a
day per saved profile for match alerts, only on days when new jobs could fit it. The query at the end of the SQL file
shows use and spend per day.

**Tests:** `cd supabase/functions/match-jobs && deno task check` formats, lints, type-checks and runs the tests, which
use a fake Claude. `ANTHROPIC_API_KEY=… deno task eval` runs the eight test CVs in `testdata/personas.json` through the
real pipeline (about US$0.45) and prints the matches for review. The *CV match quality check* workflow (Actions
tab → Run workflow) does the same on GitHub with the repository's `ANTHROPIC_API_KEY` secret and shows the matches
on the run page. The match-alert emails are covered by `scraper/tests/test_match_alerts.py`.

---

## SEO

The site includes meta description, Open Graph tags, Twitter Card tags, a canonical URL, `robots.txt`, a `sitemap.xml` submitted to Google Search Console, and Google Analytics (GA4).

Each open job has a static page with JobPosting and BreadcrumbList structured data for Google for Jobs (`validThrough` only from a real closing date), related jobs, and a tracked Apply button (`apply_click`, `source: static_page`). Pages are rewritten only when a job changes. When a job closes, its page becomes a `noindex` "no longer open" page for 60 days. The newest 50 jobs are written into `index.html` as plain links, so crawlers see content without fetching the CSV.

---

*Not affiliated with any Hong Kong university. Data sourced from official public career portals.*
