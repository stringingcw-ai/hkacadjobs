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
├── jobs.csv            # Job data — regenerated daily by the scraper (gitignored; force-added by workflow)
├── jobs-lite.csv       # jobs.csv without descriptions, for a fast first paint
├── jobs/               # One static page per job (/jobs/<slug>-<id>/), for search engines and alert links
├── sitemap.xml         # Homepage + open job pages, with each page's real last-changed date
├── robots.txt          # Allows crawlers (except the CSVs); points to the sitemap
├── favicon.svg
├── CNAME               # Custom domain configuration (www.hkacadjobs.org)
├── CHANGELOG.md        # Full update history by date
├── scraper/
│   ├── scraper.py      # Entry point: runs every institution, then NEW flags, deadlines, summaries → jobs.csv
│   ├── core.py         # Shared helpers: text cleanup, ranks, dates and deadlines, page fetching
│   ├── summaries.py    # AI summaries (Claude Haiku 4.5, structured output, Batches API)
│   ├── sites/          # One module per institution (hku.py, cuhk.py, …)
│   ├── generate_job_pages.py  # Job pages, closed-job pages, sitemap, jobs-lite.csv, homepage links
│   ├── notify.py       # Job alert emails (Supabase subscriptions → Resend)
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
├── supabase/           # One-off SQL to run in the Supabase SQL editor
└── .github/workflows/
    ├── scrape.yml      # Daily: scrape → pages → publish → wait for deploy → alerts → health check
    ├── check-links.yml # Weekly Apply-link check
    └── tests.yml       # Lint + tests on every change to the scraper or site
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

## SEO

The site includes meta description, Open Graph tags, Twitter Card tags, a canonical URL, `robots.txt`, a `sitemap.xml` submitted to Google Search Console, and Google Analytics (GA4).

Each open job has a static page with JobPosting and BreadcrumbList structured data for Google for Jobs (`validThrough` only from a real closing date), related jobs, and a tracked Apply button (`apply_click`, `source: static_page`). Pages are rewritten only when a job changes. When a job closes, its page becomes a `noindex` "no longer open" page for 60 days. The newest 50 jobs are written into `index.html` as plain links, so crawlers see content without fetching the CSV.

---

*Not affiliated with any Hong Kong university. Data sourced from official public career portals.*
