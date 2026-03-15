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

- **Daily refresh** — scraper runs at 02:00 HKT every day via GitHub Actions
- **New badge** — positions flagged as NEW on the day they first appear; count matches the "New Today" header stat exactly
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

Closing dates are sourced directly where available, and fetched from individual job detail pages for universities that embed them there:

| University | Deadline source |
|---|---|
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
├── CNAME               # Custom domain configuration (www.hkacadjobs.org)
├── robots.txt          # Allows all crawlers; points to sitemap
├── sitemap.xml         # Sitemap for search engine indexing
├── HKBU.png            # HKBU logo (local asset)
├── CHANGELOG.md        # Full update history by date
├── scraper/
│   └── scraper.py      # Python scraper for all 17 institutions
└── .github/
    └── workflows/
        └── scrape.yml  # GitHub Actions workflow (daily + manual trigger)
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
| `deadline` | Application deadline (`YYYY-MM-DD`) |
| `is_new` | `TRUE` on the day the job first appears; frontend shows New badge for 2 days |
| `date_added` | Date the job was first scraped (`YYYY-MM-DD`) |
| `reference` | University's internal reference number |
| `position_type` | Full-time / Part-time / Fixed-term |
| `salary` | Salary or grade (where available) |
| `start_date` | Expected start date (where available) |
| `apply_url` | Direct link to the application page |
| `description` | Brief description or excerpt |

---

## Running the scraper locally

```bash
# Install dependencies
pip install requests beautifulsoup4 playwright
playwright install chromium

# Scrape all universities
python scraper/scraper.py

# Scrape a single university
python scraper/scraper.py --uni hku

# Available university keys
# polyu, eduhk, lingnan, hku, hkust, cityu, hkbu, cuhk, hkmu, hsu, sfu, hksyu, vtc, hkuspace, cpce, hkchc, thei
```

The scraper compares each run against the previous `jobs.csv` to determine which jobs are new (`is_new = TRUE`) and to preserve each job's original `date_added`.

---

## Deployment

The site is hosted on GitHub Pages from the `main` branch root under the custom domain **www.hkacadjobs.org**. No build step — `index.html` reads `jobs.csv` directly via `fetch()`.

The GitHub Actions workflow (`.github/workflows/scrape.yml`) runs the scraper daily, commits the updated `jobs.csv`, and pushes — triggering an automatic Pages redeploy. You can also trigger it manually from the Actions tab.

---

## SEO

The site includes meta description, Open Graph tags, Twitter Card tags, a canonical URL, `robots.txt`, a `sitemap.xml` submitted to Google Search Console, and Google Analytics (GA4).

---

*Not affiliated with any Hong Kong university. Data sourced from official public career portals.*
