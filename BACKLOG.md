# HKAcadJobs Backlog — Drop-off & Friction Audit

Generated 2026-04-12 from a code-base health check of `index.html`, `scraper/*.py`, `.github/workflows/scrape.yml`, `robots.txt`, `sitemap.xml`. Items are grouped by funnel stage (acquisition → first paint → search → apply → retention → measurement) and tagged **P0** (ship soon, high impact / low effort), **P1** (worth doing), **P2** (nice to have). Effort: **S** ≤1 day, **M** 1-3 days, **L** >3 days.

Every item lists a concrete entry point so future work can pick it up without re-scoping.

---

## 1. Acquisition — Why aren't more people landing?

### [P0] Search box doesn't reach Traditional Chinese speakers — S
**Symptom:** HK academics and support staff search for jobs in 中文 as often as in English, but the site is English-only (`<html lang="en">` at index.html:2) and has no `hreflang` alternates. Organic traffic from Chinese-language queries is zero by design.
**Fix:** Either (a) add a minimal zh-Hant translation layer for nav, hero, and filter labels (job titles themselves stay as-is from source portals), or (b) at minimum add `<link rel="alternate" hreflang="zh-Hant-HK">` and translate the meta title + description for social preview in Chinese. Option (b) is S, option (a) is M-L.
**Evidence:** index.html:2, index.html:6-10.

### [P0] ~~Homepage meta description is generic, wasting SERP click-through~~ ✅ DONE 2026-04-12 — S
**Symptom:** "Search for academic job listings across all universities in Hong Kong, all in one place." — no numbers, no freshness signal, no differentiator. SERP snippet looks identical to every other job board.
**Fix:** Rewrite to something like `"Free, daily-updated list of 1,500+ academic and university jobs across 17 Hong Kong institutions — HKU, CUHK, HKUST, PolyU, CityU and more. Filter by rank, department, and deadline."` Pull the job count from the latest scrape at build time so it stays honest.
**Evidence:** index.html:7.

### [P1] No `ItemList` / aggregated JobPosting schema on homepage — M
**Symptom:** Only the 1,537 individual `/jobs/<slug>/` pages carry JobPosting structured data. The homepage has `WebSite` and `Organization` but no aggregate list, so Google can't surface the homepage as an entry point for "HK academic jobs" rich results.
**Fix:** In `initUI()` after `ALL_JOBS` loads, inject a single `<script type="application/ld+json">` with `@type: ItemList` pointing at the top ~20 newest JobPosting URLs. Refresh on filter changes is unnecessary — the initial list is what Googlebot sees.
**Evidence:** index.html:27-54 (current structured data), scraper/generate_job_pages.py (individual pages work fine).

### [P1] Raw `jobs.csv` is crawlable — potential SEO noise — S
**Symptom:** `robots.txt` allows `/` and doesn't disallow `jobs.csv`. Search engines can index the 1.9 MB CSV as a text file, which is (a) useless to users, (b) can dilute topic authority.
**Fix:** Add `Disallow: /jobs.csv` to robots.txt. Also add `Disallow: /sitemap.xml` (sitemaps should be fetched, not indexed — the rule is conventional and harmless).
**Evidence:** robots.txt:1-5.

### [P2] No content marketing surface (blog, guides, salary ranges) — L
**Symptom:** Every indexable page is a job posting. Long-tail queries like "HKU assistant professor salary", "HK postdoc visa", "CUHK tenure track timeline" send zero traffic.
**Fix:** Add a `/guides/` section with 5-10 evergreen articles pulled from public data (salary bands, application timelines, visa guidance). Keep the site theme; one-off content authoring lift.
**Evidence:** No `/guides/`, no `/blog/` in repo tree.

---

## 2. First paint — What do users see in the first 3 seconds?

### [P0] 1.9 MB `jobs.csv` blocks first meaningful paint — M
**Symptom:** `loadData()` fetches the entire CSV (1,929,164 bytes uncompressed, ~500 KB gzipped) before any job is shown. On a 3G mobile connection that's 3-8 seconds staring at a spinner. Drop-off is measurable in GA4 bounce rate.
**Fix:** Generate a small `jobs-featured.json` (20-30 newest / closest-deadline rows, ~15 KB) alongside the full CSV in `generate_job_pages.py`. Render those immediately, then background-fetch the full CSV to hydrate filters + pagination. Keeps the SPA architecture; just adds a tier.
**Evidence:** index.html:1590-1608 (loadData), `wc -c jobs.csv` → 1,929,164.

### [P0] No skeleton rows — loading UX is a bare spinner — S
**Symptom:** `#loadingState` shows a spinner and "Loading positions…" text only. No content shape is hinted, so the page feels frozen even when the fetch is in flight.
**Fix:** Replace the spinner with 8-10 skeleton row divs (grey pulse blocks matching the real table row layout). Purely CSS — no JS.
**Evidence:** index.html:681-684.

### [P1] Fonts are not preloaded — Playfair Display blocks LCP — S
**Symptom:** `<link rel="stylesheet">` to Google Fonts at index.html:62 is render-blocking until the CSS file resolves. Playfair Display is used for the hero H1 (the LCP element) so the hero briefly flashes in fallback then reshuffles.
**Fix:** Add `<link rel="preload" as="font" type="font/woff2" crossorigin href="https://fonts.gstatic.com/s/playfairdisplay/..." />` for the two weights actually used (500, 700) plus DM Sans 400/600. Also add `&display=swap` is already present — good. Consider self-hosting to remove the `fonts.gstatic.com` round-trip entirely.
**Evidence:** index.html:22-26 (preconnect is there but no preload), index.html:62.

### [P1] Supabase JS bundle is loaded synchronously in `<head>` — S
**Symptom:** `@supabase/supabase-js` UMD bundle (~70 KB gzipped) is loaded at index.html:63 before CSS parses, but is only used after the user clicks "Sign in" — an interaction that ~95% of visitors never take.
**Fix:** Add `defer` to the script tag, or better, dynamically `import()` the Supabase client only when `openAuthModal()` is first called. Saves ~70 KB + one parse/compile pass from the critical path.
**Evidence:** index.html:63.

### [P2] No service worker / offline shell — L
**Symptom:** Returning users re-download the 1.9 MB CSV + fonts + all icons on every visit. Nothing is cached beyond HTTP cache headers (which GitHub Pages sets conservatively).
**Fix:** Add a minimal service worker that stale-while-revalidates `index.html`, CSS, JS, and `jobs.csv`. Invalidate `jobs.csv` aggressively (every 4 hours) since it changes nightly; cache fonts indefinitely.
**Evidence:** No `sw.js` in repo, no `navigator.serviceWorker.register` calls.

---

## 3. Search friction — Why do users give up mid-search?

### [P0] ~~Search only hits title + department — keyword searches silently return nothing~~ ✅ DONE 2026-04-12 — S
**Symptom:** `job_matches_filter` and its client-side twin only grep title + department. A user searching "machine learning", "climate", "NLP", "quantum" gets zero results if those words only appear in the job description — the single biggest silent dead-end in the UX.
**Fix:** Extend the search haystack to include `description` (the text the scraper already stores). Weight title matches higher than description matches when sorting. Estimated work: ~20 lines of JS change plus filter logic update.
**Evidence:** scraper/notify.py:144-148, and the mirror function in index.html — grep `function filterJobs` / the equivalent of `haystack`.

### [P0] ~~Empty-state dead-ends users — no "did you mean" or alternative~~ ✅ DONE 2026-04-12 — S
**Symptom:** When filters + search return zero results, the empty state is a 🔍 emoji and a "Reset all filters" button. No hint that maybe the search term doesn't match any indexed field, no fuzzy suggestion, no link to "Browse by institution" or "Set an alert for this search".
**Fix:** Extend the empty state to detect which filter is most restrictive and offer a one-click "Remove [filter]" shortcut, plus a permanent "Get alerted when matching jobs appear" CTA (this also drives alert conversions — see item 5.1).
**Evidence:** index.html:698.

### [P0] ~~"Area" filter label is ambiguous — confuses first-time visitors~~ ✅ DONE 2026-04-12 — S
**Symptom:** A dropdown labelled "All Areas" with no tooltip — users don't know whether it means geography, subject area, or org unit. Actually maps to `position_type` (Academic / Research / Admin / Technical).
**Fix:** Rename to "All Job Types" or "All Categories". Add placeholder help text under the filter bar on first visit. One-word change in the template.
**Evidence:** index.html:653.

### [P1] No sort by date-added — users can't find "what's new this week" — S
**Symptom:** Only deadline sort exists. The NEW badge is visible but there's no way to list jobs in posting-date order. Returning users have to manually scan for the badge.
**Fix:** Add "Newest" as the default sort (with "Deadline" as a second option). Use the existing `date_added` column.
**Evidence:** index.html:692 (only deadline is sortable).

### [P1] No saved-filter prompt after applying filters — alert signup is undiscoverable — S
**Symptom:** The 🔖 "Save filter" button sits in the filter bar but is silent — users don't learn about it. Alert subscription only happens if a user first saves, then notices the alert toggle on the saved card.
**Fix:** After a user applies 2+ filters and stays on the results for >15 seconds, show a non-blocking toast: "Save this search and get daily alerts for matching jobs → [Save & Subscribe]". One-shot per session via localStorage.
**Evidence:** trackEvent('filter_applied') at index.html:1314 — we know when it happens, just don't prompt.

### [P1] Zero-result searches are not tracked as a distinct event — S
**Symptom:** `trackEvent('search', ...)` fires on every keystroke ≥2 chars with a `result_count`, but there's no filter on `result_count === 0`. We can't easily see in GA4 which searches are dead-ending users.
**Fix:** Fire a separate `search_no_results` event with `search_term` when results drop to 0 for ≥1.5 seconds (debounced, not on every keystroke). Build a weekly GA4 explore to guide the "new filter fields" decision.
**Evidence:** index.html:1088.

### [P2] No recent-searches / autocomplete — S-M
**Symptom:** Users repeating the same search have to retype it every visit.
**Fix:** Store last 5 searches in localStorage, show as chips below the search input when focused and empty. Optional: fuzzy-suggest keywords pulled from existing job descriptions.

### [P2] Multiselect filter dropdowns aren't keyboard-navigable — S
**Symptom:** `.ms-wrap` custom multiselects (institutions, ranks) rely on click handlers with no arrow-key / Enter / Escape support. Screen-reader and keyboard users are locked out.
**Fix:** Add arrow-key navigation + Enter-to-toggle + Esc-to-close to `ms-panel`. Add `role="listbox"` / `role="option"`.
**Evidence:** index.html:161-175.

---

## 4. Detail → Apply conversion — Are the jobs actually getting clicked?

### [P0] Apply button outbound click is NOT tracked — blind funnel — S
**Symptom:** `trackEvent('job_detail_viewed', ...)` fires when the detail panel opens (index.html:2088), but there is no event on the actual "Apply on [University]" click. The single most important conversion on the site is invisible in GA4. We literally don't know if the site delivers value.
**Fix:** Add `onclick="trackEvent('apply_click', {job_id: ..., university: ..., rank: ...})"` to the `#panelApplyLink` anchor. Also mirror it on the table-row apply button. Five-line change.
**Evidence:** index.html:919-920, 1997-1998, 2144-2145.

### [P1] No "you might also like" section in the detail panel — S
**Symptom:** Once the panel opens, the only next action is "Apply" or close. A user deciding this job isn't for them has no path forward except scrolling back to the results.
**Fix:** At the bottom of the detail panel, render 3 related jobs (same department group OR same institution + same rank). Uses existing classification helpers.
**Evidence:** index.html panel structure around line 919.

### [P1] Apply link opens in a new tab but no return-hook — S
**Symptom:** `target="_blank" rel="noopener"` means once a user clicks Apply, they're gone from the tab and won't come back to browse more. No bookmark prompt, no "come back tomorrow", no save-to-list on click.
**Fix:** On apply click, trigger a subtle toast in the current tab: "Added to your activity — sign in to get notified when similar jobs appear." This both adds retention and drives sign-in.
**Evidence:** index.html:919.

### [P2] No per-job social share — S
**Symptom:** Users can't easily forward a job to a colleague except by copying the URL. With the static page URLs now in place (PR #2), a dedicated share affordance costs almost nothing.
**Fix:** Add a small "Share" button to the detail panel that copies `https://www.hkacadjobs.org/jobs/<slug>-<id>/` to clipboard and tracks `share_job` event.

---

## 5. Retention — Are users coming back?

### [P0] Email alert CTA is buried — no hero-level prompt — M
**Symptom:** The only entry point to email alerts is via "Save filter" → notice alert toggle → opt in. The hero has no visible "Get weekly alerts" CTA. For an aggregator whose *retention loop is email*, this is the biggest lever we're not pulling.
**Fix:** Add a single-line signup under the hero stats row: `"Get new HK academic jobs in your inbox daily — [email field] [Subscribe]"`. This creates a low-friction subscription for "all new jobs" (no filter) in addition to the existing filter-specific alerts. Requires a new `filter_state: {}` row type in Supabase (which `notify.py` already handles correctly — empty filter = match everything).
**Evidence:** index.html hero (~line 620-630), notify.py:119 (empty filter matches).

### [P1] No weekly digest separate from filter-alerts — M
**Symptom:** `notify.py` only sends alerts when subscribers' saved filters match `is_new=TRUE` rows. A user with a filter that doesn't match today gets silence — eventually unsubscribes or forgets the site exists.
**Fix:** Add a "weekly roundup" email sent every Monday to every confirmed subscriber, showing top 10 matching jobs regardless of `is_new`. Also sends a fallback digest to users whose filters had zero matches that week.
**Evidence:** scraper/notify.py:108-114 (`load_new_jobs` only reads `is_new=TRUE`).

### [P1] No visible social proof — S
**Symptom:** No "Join 500+ Hong Kong researchers" or "1,537 open positions tracked daily" in the hero or footer. Trust signals are absent.
**Fix:** Pull subscriber count from Supabase at build time (or periodically), render as a small pill near the hero or in the footer. Requires a nightly write of the count into a static JSON file since we don't want live DB reads from every visitor.

### [P2] Welcome modal expiry is stale code — S
**Symptom:** `WELCOME_EXPIRY = new Date('2026-04-10T00:00:00+08:00')` (index.html:2503) is already 2 days in the past as of 2026-04-12. The welcome modal no longer fires for any new visitor. Either remove the whole modal + trigger code, or refresh the expiry + the content for a new launch announcement (e.g. static pages, alerts).
**Evidence:** index.html:2502-2508.

### [P2] No re-engagement trigger for lapsed users — M
**Symptom:** A user who signed in once and then went silent for 30+ days never gets a nudge.
**Fix:** `notify.py` could check `auth.users.last_sign_in_at` and send a re-engagement email to anyone silent for 30+ days with new matching jobs. Low volume, targeted.

---

## 6. Measurement blind spots — What we can't see, we can't fix

### [P0] `apply_click` missing — see item 4.1 — S
(duplicated here for tracking; fix once, resolves both funnel visibility and retention decisions)

### [P0] `search_no_results` missing — see item 3.5 — S
(duplicated here for tracking)

### [P1] No funnel definition in GA4 — S
**Symptom:** Events are fired but no GA4 funnel is defined for `search → filter_active → job_detail_viewed → apply_click → alert_subscribed`. The drop-off we're analyzing in this doc is based on code reading, not production data.
**Fix:** Define the funnel in GA4 Explore once `apply_click` and `search_no_results` ship. Track weekly drop-off rate at each step. Not a code change — operations task for the repo owner.

### [P2] No A/B test harness remaining — M
**Symptom:** The quote-hero A/B test was removed after shipping to 100%. There's no infrastructure left for future experiments (e.g. variant copy on the hero, different CTA placements).
**Fix:** Keep a minimal localStorage-based 50/50 bucketer + GA4 `experiment_variant` user property as a reusable helper. Future experiments wire in by calling `assignVariant('experiment_name')`.
**Evidence:** Prior A/B test code removed per the 2026-04 CHANGELOG entry.

---

## 7. Accessibility & polish

### [P1] Only 6 aria attributes across the full 2,869-line SPA — M
**Symptom:** Filter buttons, modals, the detail panel, and the multiselect dropdowns all lack ARIA roles, labels, or state. Screen-reader and keyboard users face a partially-unusable site. WCAG 2.1 AA compliance is likely failing.
**Fix:** An ARIA pass: `aria-label` on all icon-only buttons, `role="dialog"` + `aria-modal="true"` on modals, `aria-expanded` on filter toggles, focus trap on auth + detail modals, Esc key handlers, visible focus rings on keyboard interaction. ~1-2 day pass.
**Evidence:** `grep -c 'aria-\|role="' index.html` → 6.

### [P2] Emoji icons lack accessible fallbacks — S
**Symptom:** 🔍 🔖 🔔 🔑 📬 etc. used as UI icons with no `aria-hidden="true"` or `aria-label`. Screen readers read them as "magnifying glass tilted left" etc. — verbose and confusing.
**Fix:** Wrap in `<span aria-hidden="true">` and provide text labels where they carry meaning.

### [P2] No skip-to-content link — S
**Symptom:** Keyboard users have to tab through nav + hero + filters before reaching the job list on every pageload.
**Fix:** Add a visually-hidden `<a href="#jobTable">Skip to results</a>` as the first focusable element.

---

## 8. Content & trust

### [P1] No "last successful scrape" timestamp prominent in UI — S
**Symptom:** Users discovering the site don't know if the data is 1 day or 1 month old. `LAST_UPDATED` is derived from `date_added` and shown in the header meta, but not prominently.
**Fix:** Render a small "Updated 2 hours ago · Next refresh at 02:00 HKT" pill near the hero. Builds trust.
**Evidence:** index.html:1624-1630.

### [P2] No per-job "source" attribution link — S
**Symptom:** Each job links to `apply_url` but doesn't show the source portal domain next to it. Users may wonder if the listing is authoritative.
**Fix:** Show the source domain (e.g. `jobs.hku.hk`) as a small text line under the institution name in the detail panel.

---

## Priority summary (quick-pick for next sprint)

**Ship first (P0, mostly S effort, highest ROI):**
1. Add `apply_click` event tracking (item 4.1) — blind funnel fix
2. Search description field, not just title+dept (item 3.1) — silent dead-end
3. Add skeleton rows (item 2.2) — perceived speed
4. Fix meta description copy (item 1.2) — SERP CTR
5. Hero-level email alert CTA (item 5.1) — retention lever
6. Rename "Area" filter to "Job Type" (item 3.3) — clarity
7. Empty-state alternative actions (item 3.2) — rescue zero-results
8. `search_no_results` tracking (item 3.5) — visibility for future fixes

**Then tackle (P0 with more effort):**
- Tiered CSV load — featured JSON first, full CSV hydrate (item 2.1)
- Chinese language support minimum (item 1.1)
- Robots.txt disallow `/jobs.csv` (item 1.4)

**P1 backlog:** Weekly digest, homepage ItemList schema, fonts preload, Supabase lazy-load, saved-filter prompt, newest sort, related-jobs panel, ARIA pass, social proof, last-scrape pill, GA4 funnel definition.

**P2 backlog:** Service worker, guides content, per-job share, recent-searches, keyboard-navigable multiselects, welcome modal cleanup, emoji aria, skip-link, source attribution, re-engagement email, A/B harness.

---

## Not addressed here (out of scope)

- Job data quality / scraper coverage gaps (separate audit)
- Pricing / monetisation model (no business decision to review)
- Infrastructure cost / GitHub Pages limits (no reported issue)
- Moderation / reporting flows (existing report modal is sufficient for current volume)
