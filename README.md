# HKAcadJobs

> Every academic opening in Hong Kong, in one place.

A static job board aggregating academic positions from all 8 major Hong Kong universities, updated daily via GitHub Actions. No login required, no paywalls — just a fast, searchable list of open positions pulled straight from official university career portals.

**Live site:** https://stringingcw-ai.github.io/hkacadjobs/

---

## Universities covered

| Code | University |
|------|-----------|
| HKU | University of Hong Kong |
| CUHK | Chinese University of Hong Kong |
| HKUST | HK University of Science & Technology |
| PolyU | Hong Kong Polytechnic University |
| CityU | City University of Hong Kong |
| HKBU | Hong Kong Baptist University |
| LU | Lingnan University |
| EdUHK | Education University of Hong Kong |

---

## Features

- **Daily refresh** — scraper runs at 10:00 HKT every day via GitHub Actions
- **New badge** — positions are flagged as NEW only on the day they first appear
- **Search & filter** — by keyword, university, department, and rank
- **Sortable table** — click any column header to sort
- **Detail panel** — click any row for full job info and a direct apply link
- **Save for later** — bookmark positions locally (persisted in browser storage)
- **Deadline tracker** — colour-coded days-remaining indicator on every listing

---

## Project structure

```
├── index.html          # Single-page frontend (HTML + CSS + JS, no build step)
├── jobs.csv            # Job data — regenerated daily by the scraper
├── scraper/
│   └── scraper.py      # Python scraper for all 8 universities
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
| `rank` | Detected rank: Professor / Associate Professor / Assistant Professor / Postdoc / Lecturer / Other |
| `university` | Short code (e.g. `HKU`) |
| `university_full` | Full university name |
| `department` | Department or faculty |
| `deadline` | Application deadline (`YYYY-MM-DD`) |
| `is_new` | `TRUE` only on the day the job first appears |
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
# polyu, eduhk, lingnan, hku, hkust, cityu, hkbu, cuhk
```

The scraper compares each run against the previous `jobs.csv` to determine which jobs are new (`is_new = TRUE`) and to preserve each job's original `date_added`.

---

## Deployment

The site is hosted on GitHub Pages from the `main` branch root. No build step — `index.html` reads `jobs.csv` directly via `fetch()`.

The GitHub Actions workflow (`.github/workflows/scrape.yml`) runs the scraper daily, commits the updated `jobs.csv`, and pushes — triggering an automatic Pages redeploy. You can also trigger it manually from the Actions tab.

---

*Not affiliated with any Hong Kong university. Data sourced from official public career portals.*
