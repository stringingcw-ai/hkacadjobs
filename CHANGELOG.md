# Changelog

All notable changes to HKAcadJobs are recorded here, grouped by date.

---

## 2026-03-07

### UI
- Replaced bookmark icons (🔖/🔲) with filled/unfilled SVG star icons throughout (list rows, detail panel, nav button, empty saved state)
- Star icons styled in brand yellow (`--bookmark`); unfilled star has thicker stroke (2.2) and 0.6 opacity
- Saved nav button now toggles between saved and all results view; shows yellow outline highlight when in saved view
- Results banner: repurposed from "N new positions added today" to "N positions found" — updates dynamically on every filter change
- Results banner hidden when in saved view or when no results match the active filters
- Department tag contrast improved: `#3d3a34` text on `#e8e4dc` background across both list and detail panel
- Header title updated: "Every university opening in Hong Kong, in one place."

### Scraper
- Added `infer_dept_from_title()` utility: extracts department from job title via three regex patterns ("Role in Dept", "Head of Dept", "Role (Dept)")
- Applied to HKBU API path, HKBU Playwright fallback, and EdUHK scraper — fixes ~59 of 74 blank-department jobs
- HKBU Playwright fallback now falls back to university name instead of leaving department blank

---

## 2026-03-06

### UI
- New badge extended to show for jobs added in the last 2 days (today and yesterday); `statNew` counter in header still reflects today-only count
- Removed "All Positions / Saved" tab switcher from filter bar; saved positions now accessible via nav button only
- Fixed loading text: removed stale "from Google Sheets" reference
- Added 15-second fetch timeout with user-facing error message on abort
- Removed result count from filter bar; count now shown exclusively in the green banner below filters

### SEO & Infrastructure
- Custom domain configured: www.hkacadjobs.org (CNAME added, GitHub Pages verified)
- Canonical URL and Open Graph URLs updated from GitHub Pages URL to www.hkacadjobs.org
- Google Analytics (GA4) and Google Search Console verification already present in index.html

---

## 2026-03-05

### Scraper — Rank classification
- Moved Tenure-Track check to top of `detect_rank()` to prevent slippage into Professor/Assistant Professor ranks
- Added new ranks: `Tenure-Track`, `Postdoctoral` (merged Doctoral/PhD Fellow), `Research Assistant/Associate`, `Teaching Assistant`, `Senior Management`
- Removed `Deans/Heads` and `General` ranks
- Added optional `description` parameter to `detect_rank()` for richer classification
- Added re-ranking pass in `main()` after all jobs and descriptions are collected
- Removed "scientist" from `NON_ACADEMIC_KEYWORDS` (was incorrectly catching Research Engineer/Scientist)

### Scraper — Description fixes
- HKU: added bot-check detection guard (skips pages containing Cloudflare/security-check markers)
- HKUST: fixed Interfolio URL mapping — JS TreeWalker now stops before containers with more than one Job ID, preventing wrong apply_url assignment
- HKUST: added cache invalidation when `apply_url` changes so stale descriptions are re-fetched
- Cleared 129 stale HKUST descriptions from jobs.csv

### Scraper — Area classification
- Expanded `AREA_GROUPS` keyword lists across all 11 areas to reduce "Other" from ~15% to ~9.5%
- Added keywords covering: aviation, logistics, maritime, geo-informatics, IoT, cybersecurity, wellness, ageing, suicide studies, machine creativity, and more

### UI — Bug fixes
- Fixed endless loading: `updateBkUI()` was calling `getElementById('tabBkCount')` on a removed element, throwing TypeError before `loadData()` ran
- Fixed `switchTab()` crash caused by references to removed `tabAll`/`tabSaved` elements

---

## 2026-03-04

### Initial features (baseline)

- Daily scraper covering 12 HK universities via GitHub Actions
- Static GitHub Pages site with CSV-based data loading
- Search and filter by keyword, university, department, area, and rank
- Cascading area → department group chip filters
- Sortable deadline column
- Detail side panel with AI summary (Claude Haiku), apply link, and save button
- New badge and highlighted rows for jobs added today
- Colour-coded deadline tracker (urgent / soon / ok)
- University logos in list and panel
- Mobile-responsive card layout
- Bookmark/save positions with localStorage persistence
- Google Analytics (GA4) and Google Search Console integration
