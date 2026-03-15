# Changelog

All notable changes to HKAcadJobs are recorded here, grouped by date.

---

## 2026-03-15

### New Institutions
- Added **HKU SPACE** (HKU School of Professional and Continuing Education) — scrapes career listings page with Playwright
- Added **CPCE / HKCC / SPEED** (College of Professional and Continuing Education, PolyU) — scrapes listing page; deadline format `DD-Mon-YYYY` normalised to `YYYY-MM-DD`; uses PolyU logo
- Added **HKCHC** (Hong Kong Chu Hai College) — renamed from previous `CHUHAI` code throughout scraper, CSV, and frontend
- Added **THEi** (Technological and Higher Education Institute of Hong Kong) — Playwright scraper handles two Elementor Loop Grid sections (infinite scroll + click-to-load); fetches detail pages for reference numbers

### UI — Filters
- **Multi-select for Institutions and Ranks** — replaced single-select dropdowns with custom checkbox panels; button label updates to show selected count ("3 selected") or single name; each panel has a sticky Reset button
- **Rank / Role type sync** — selecting Academic hides Non-Academic from the rank panel; selecting Non-Academic locks rank to Non-Academic and disables the dropdown; switching back to All Types restores full panel and clears auto-selected rank
- **Academic / Non-Academic filter** — dropdown (All Types / Academic / Non-Academic) with active chip and `?role=` URL param
- **Removed department filter** — department dropdown removed from filter bar
- **Clear all** — "Clear all" text link appears in the active chips bar whenever any filter is active
- Multi-select state reflected in shareable URL: `?uni=PolyU,CityU&rank=Professor,Lecturer`

### UI — Saved tab
- **Save filter** — 🔖 Save filter button replaces "Copy filter" in the active chips bar; clicking opens a named-save popover (pre-filled auto-label, Enter to save); popover uses `position: fixed` so it renders correctly on mobile
- **Saved filters section** — saved filter cards appear at the top of the Saved tab showing name, criteria tags, Apply and Delete actions
- **Saved tab layout** — search and filter bar hidden on saved page; "Saved Filters" and "Saved Positions" section titles added; empty state shows correct message
- **Header count** — Saved nav button count now reflects saved positions + saved filters combined

### Bug fixes
- Fixed expired jobs incorrectly showing NEW badge — scraper now checks `is_active()` before setting `is_new = TRUE` on newly scraped jobs
- Fixed "New today" header count diverging from NEW badge count — removed localStorage caching; both now derive from `date_added === latestScrapeDate`
- Fixed CPCE dates stored as `DD-Mon-YYYY` bypassing `is_active()` — added `%d-%b-%Y` / `%d-%B-%Y` to `parse_date_text()` formats and normalised 31 affected rows in CSV
- Fixed institution dropdown still showing "Chu Hai" after HKCHC rename — removed stale `UNI_DISPLAY` override so it falls back to the code

---

## 2026-03-10

### UI
- Results list now sorted by academic area after new jobs (Medicine & Health → Engineering → Computer Science & AI → Science & Mathematics → Business → Arts & Humanities → Social Sciences → Education → Law → Architecture & Design → Administration → Other), then by institution, then by date added

### Scraper — AI Summary
- Improved Key Dates extraction: model now identifies and labels all dates found on the detail page (closing date, review date, start date, interview date etc.) with format `Label: Date` per bullet, instead of a single unlabelled deadline
- Increased summarisation max_tokens to 600 to accommodate multiple date bullets
- Added `--force-resummary` flag to scraper to re-run AI summaries for all jobs ignoring cached summaries; used for one-time re-summarisation on 2026-03-11
- Scheduled one-time GitHub Actions workflow to remove `--force-resummary` flag on 2026-03-12

### Scraper — Description coverage fixes
- **CityU**: switched detail page fetching from `requests` to Playwright to bypass Incapsula bot protection — coverage improved from 13% to 100%
- **HKBU**: strip HTML tags from Oracle HCM API description field; extend Playwright detail visit to extract descriptions (not just closing dates); add caching — coverage improved from 0% to 99.5%
- **HKSYU**: extract text from PDF job ads using `pypdf` for AI summarisation — coverage improved from 0% to 100%
- **HKU**: use fresh browser context every 20 requests with randomised 2.5–4.5s delay to reduce session-based rate limiting
- **HKUST**: revert detail fetch to Interfolio-only — PeopleSoft URLs are HKUST-internal and always timeout, wasting ~44min per scrape run
- **HKU/HKBU/HKSYU**: restore cached descriptions on bot detection instead of silently leaving placeholder
- Added `pypdf` to workflow pip install

### Infrastructure
- Fixed daily scraper push rejection when `deploy-lecturer-rename` workflow commits concurrently: added `git pull --rebase` before push

---

## 2026-03-09 (updated)

### Scraper
- Added VTC (Vocational Training Council) as 13th institution — covers full-time (tab1) and part-time (tab2) listings from vtc.edu.hk; parses title, division, department, deadline, reference, and detail page description

### UI — Terminology
- Renamed "University" to "Institution" throughout: filter dropdown, table header, and active filter chip label

### UI — Filter bar polish
- Removed "Groups:" and "Filtered by:" prefix labels; show pill values only
- Removed border separators between filter bar, group chips, and filtered-by rows
- Added persistent bottom border to sticky controls as separator when no filters are applied
- Filtered-by row now stays visible on mobile when filter bar is collapsed
- Aligned group chip and filter chip font size to match dropdowns (0.84rem)
- Tightened padding between filter bar sections; reduced gap between search bar and filtered-by row in collapsed state

### UI — Mobile fixes
- Fixed filter dropdowns being clipped: increased `filter-expandable` max-height to 220px
- Fixed filter dropdowns overflowing screen width on mobile: selects now flex to 50% width with `min-width: 0`

### UI — Announcement toast
- Added dismissible toast notification (bottom-right on desktop, full-width on mobile) announcing VTC as a new institution
- Toast self-gates: only appears once VTC jobs are present in loaded data; silently inactive until scraper adds VTC
- One-time per user via localStorage; auto-dismisses after 7s; styled in brand accent colour

### Infrastructure
- Scheduled one-time GitHub Actions workflow to rename "Lecturer" → "Senior Lecturer/Lecturer" in filter dropdown at 09:58 HKT (2 minutes before daily scrape)

---

## 2026-03-08

### UI — Mobile
- Added collapsing filter bar for mobile: scrolling down from any position collapses the filter dropdowns to a single search bar + "Filters ▼" pill; scrolling back to the top auto-expands
- Active filter count badge on pill turns orange when filters are applied
- Tapping the pill manually expands filters; stays expanded until next downward scroll
- Filter collapse uses GPU-accelerated `max-height` + `translateY` + `opacity` animation (cubic-bezier easing) for smooth performance on iOS Safari
- Fixed filter dropdown reflow: removed `flex-wrap: nowrap` on collapse to prevent selects shifting sideways before animating
- Fixed white gap when "Filtered by" row collapses: padding now animates to zero alongside height
- Removed top border on job table wrap on mobile (was showing a thin line above the first result card)

### UI — Hero stats
- Open Positions and New Today counters now animate on page load with a fade + slide-up entrance
- Count-up animation uses 2s ease-out cubic deceleration (exponent 3) — rushes through early numbers then dramatically slows to the final value
- Stats staggered: Open Positions starts at 100ms, New Today at 300ms

### Scraper
- `detect_rank()`: Teaching Consultant and academic-context consultant titles (language, academic, education, learning) now classified as Lecturer instead of Non-Academic

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
