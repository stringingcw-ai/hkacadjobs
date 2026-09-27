# HKAcadJobs Backlog — Drop-off & Friction Audit

Generated 2026-04-12 from a code-base health check of `index.html`, `scraper/*.py`, `.github/workflows/scrape.yml`, `robots.txt`, `sitemap.xml`. Items are grouped by funnel stage (acquisition → first paint → search → apply → retention → measurement) and tagged **P0** (ship soon, high impact / low effort), **P1** (worth doing), **P2** (nice to have). Effort: **S** ≤1 day, **M** 1-3 days, **L** >3 days.

Every item lists a concrete entry point so future work can pick it up without re-scoping.

**Updated 2026-09-28** after the September health check (`HEALTH_CHECK_2026-09.md`): items that work finished are
marked ✅, and the report's growth recommendations (its §8) are added to the funnel sections below, tagged
*(Health check §8…)*. Scraper reliability, alerts, data accuracy and job-page SEO were fixed by that work and are
tracked in the report, not here. New operations items are in §9.

---

## 1. Acquisition — Why aren't more people landing?

### [P0] Search box doesn't reach Traditional Chinese speakers — S
**Symptom:** HK academics and support staff search for jobs in 中文 as often as in English, but the site is English-only (`<html lang="en">` at index.html:2) and has no `hreflang` alternates. Organic traffic from Chinese-language queries is zero by design.
**Fix:** Either (a) add a minimal zh-Hant translation layer for nav, hero, and filter labels (job titles themselves stay as-is from source portals), or (b) at minimum add `<link rel="alternate" hreflang="zh-Hant-HK">` and translate the meta title + description for social preview in Chinese. Option (b) is S, option (a) is M-L. *(Health check §8.1.3)* Also consider Simplified Chinese for mainland PhD and postdoc candidates, a large applicant pool; the programmatic landing pages (below) and AI summaries can be translated by Claude at build time.
**Evidence:** index.html:2, index.html:6-10.

### [P0] ~~Homepage meta description is generic, wasting SERP click-through~~ ✅ DONE 2026-04-12 — S
**Symptom:** "Search for academic job listings across all universities in Hong Kong, all in one place." — no numbers, no freshness signal, no differentiator. SERP snippet looks identical to every other job board.
**Fix:** Rewrite to something like `"Free, daily-updated list of 1,500+ academic and university jobs across 17 Hong Kong institutions — HKU, CUHK, HKUST, PolyU, CityU and more. Filter by rank, department, and deadline."` Pull the job count from the latest scrape at build time so it stays honest.
**Evidence:** index.html:7.

### [P1] No `ItemList` / aggregated JobPosting schema on homepage — M
**Symptom:** Only the 1,537 individual `/jobs/<slug>/` pages carry JobPosting structured data. The homepage has `WebSite` and `Organization` but no aggregate list, so Google can't surface the homepage as an entry point for "HK academic jobs" rich results.
**Fix:** `generate_job_pages.py` already writes the newest 50 jobs into `index.html` between the `LATEST-JOBS` markers (Sep 2026). Emit an `ItemList` JSON-LD block for the same jobs in that step, so it is in the static HTML rather than added by JS.
**Evidence:** index.html:27-54 (current structured data), `build_latest_block()` in scraper/generate_job_pages.py.

### [P1] ~~Raw `jobs.csv` is crawlable — potential SEO noise — S~~ ✅ DONE
**Symptom:** `robots.txt` allows `/` and doesn't disallow `jobs.csv`. Search engines can index the 1.9 MB CSV as a text file, which is (a) useless to users, (b) can dilute topic authority.
**Fix:** Add `Disallow: /jobs.csv` to robots.txt. Also add `Disallow: /sitemap.xml` (sitemaps should be fetched, not indexed — the rule is conventional and harmless).
**Evidence:** robots.txt:1-5.

### [P2] No content marketing surface (blog, guides, salary ranges) — L
**Symptom:** Every indexable page is a job posting. Long-tail queries like "HKU assistant professor salary", "HK postdoc visa", "CUHK tenure track timeline" send zero traffic.
**Fix:** Add a `/guides/` section with 5-10 evergreen articles pulled from public data (salary bands, application timelines, visa guidance). Keep the site theme; one-off content authoring lift. *(Health check §8.1.6)* Suggested topics: HK university salary scales, how hiring works at each university, visas (GEP / IANG), tenure-track timelines, an RGC funding calendar. Draft with Claude, review by hand.
**Evidence:** No `/guides/`, no `/blog/` in repo tree.

### [P0] Programmatic landing pages — M-L *(Health check §8.1.2)*
**Symptom:** The only indexable pages are the homepage and individual job pages. Nothing ranks for how people actually search: "HKU jobs", "postdoc jobs Hong Kong", "computer science jobs Hong Kong", "academic jobs closing this week". The health check calls this the biggest organic lever.
**Fix:** Have `generate_job_pages.py` also build one page per institution (`/hku/`, `/cuhk/` …), per rank (`/postdoc-jobs-hong-kong/`, `/assistant-professor-jobs-hong-kong/` …), per discipline (reuse `AREA_GROUPS` from index.html; `notify.load_site_taxonomy()` already parses it), plus `/closing-this-week/` and `/new-this-week/`. Each gets a unique intro, live counts, `ItemList` JSON-LD and links to the job pages, and goes in the sitemap. Reuse the job pages' template, manifest and write-only-if-changed logic.
**Evidence:** scraper/generate_job_pages.py (page shell, manifest, sitemap); index.html `AREA_GROUPS`.

### [P1] Automated social distribution and feeds — M *(Health check §8.1.4)*
**Symptom:** New jobs only reach people who visit the site or have alerts on.
**Fix:** After each daily run, post "N new academic jobs in HK today" (top 5 by rank, linking to job pages with UTM tags) to a LinkedIn page, X / Threads / Bluesky and a Telegram or WhatsApp channel. Also publish RSS/Atom feeds per institution and discipline from `generate_job_pages.py`. It fits the existing workflow; start with a Telegram channel and RSS, which need no approval process.
**Evidence:** `.github/workflows/scrape.yml` (add a step after alerts); scraper/generate_job_pages.py.

### [P1] Partnerships, backlinks and an embeddable widget — M *(Health check §8.1.5)*
**Symptom:** Few external links point to the site, which limits both referral traffic and search ranking.
**Fix:** Outreach (owner task) to postdoc associations at each university, the HKPFS community, research offices, graduate schools, EURAXESS, and communities such as r/AskAcademia and r/PhD. Code side: an embeddable "latest jobs at <department>" widget (a small script or iframe reading `jobs-lite.csv`) that departments can put on their sites, linking back to job pages.
**Evidence:** — (new).

---

## 2. First paint — What do users see in the first 3 seconds?

### [P0] ~~1.9 MB `jobs.csv` blocks first meaningful paint — M~~ ✅ DONE 2026-09-27
**Done:** the table now paints from `jobs-lite.csv` (every column except descriptions, written by `generate_job_pages.py`), then descriptions load from `jobs.csv` in the background. It falls back to `jobs.csv` alone if the lite file is missing.

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

### [P1] ~~Supabase JS bundle is loaded synchronously in `<head>` — S~~ ✅ DONE 2026-09-27 (partly)
**Done:** moved out of `<head>` to just before the script that uses it, and pinned to an exact version (2.117.2) with an integrity hash. Loading it only on the first sign-in click would still save the download for most visitors.

**Symptom:** `@supabase/supabase-js` UMD bundle (~70 KB gzipped) is loaded at index.html:63 before CSS parses, but is only used after the user clicks "Sign in" — an interaction that ~95% of visitors never take.
**Fix:** Add `defer` to the script tag, or better, dynamically `import()` the Supabase client only when `openAuthModal()` is first called. Saves ~70 KB + one parse/compile pass from the critical path.
**Evidence:** index.html:63.

### [P2] No service worker / offline shell — L
**Symptom:** Returning users re-download the 1.9 MB CSV + fonts + all icons on every visit. Nothing is cached beyond HTTP cache headers (which GitHub Pages sets conservatively).
**Fix:** Add a minimal service worker that stale-while-revalidates `index.html`, CSS, JS, and `jobs.csv`. Invalidate `jobs.csv` aggressively (every 4 hours) since it changes nightly; cache fonts indefinitely. *(Health check §8.2.13)* The same service worker enables a PWA install and web push notifications as an alternative to email alerts.
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

### [P1] ~~No sort by date-added — users can't find "what's new this week" — S~~ ✅ DONE
**Done:** the site has a "Recently posted" sort and "Posted within" chips (24h / 7 days / 30 days).

**Symptom:** Only deadline sort exists. The NEW badge is visible but there's no way to list jobs in posting-date order. Returning users have to manually scan for the badge.
**Fix:** Add "Newest" as the default sort (with "Deadline" as a second option). Use the existing `date_added` column.
**Evidence:** index.html:692 (only deadline is sortable).

### [P1] No saved-filter prompt after applying filters — alert signup is undiscoverable — S
**Symptom:** The 🔖 "Save filter" button sits in the filter bar but is silent — users don't learn about it. Alert subscription only happens if a user first saves, then notices the alert toggle on the saved card.
**Fix:** After a user applies 2+ filters and stays on the results for >15 seconds, show a non-blocking toast: "Save this search and get daily alerts for matching jobs → [Save & Subscribe]". One-shot per session via localStorage.
**Evidence:** trackEvent('filter_applied') at index.html:1314 — we know when it happens, just don't prompt.

### [P1] ~~Zero-result searches are not tracked as a distinct event — S~~ ✅ DONE
**Symptom:** `trackEvent('search', ...)` fires on every keystroke ≥2 chars with a `result_count`, but there's no filter on `result_count === 0`. We can't easily see in GA4 which searches are dead-ending users.
**Fix:** Fire a separate `search_no_results` event with `search_term` when results drop to 0 for ≥1.5 seconds (debounced, not on every keystroke). Build a weekly GA4 explore to guide the "new filter fields" decision.
**Evidence:** index.html:1088.

### [P1] Richer filters from the structured summaries — M *(Health check §8.2.11)*
**Symptom:** Filters cover institution, rank, category and keyword only. Candidates also decide on pay, contract length and start date.
**Fix:** The AI summaries now extract salary and start date into their own columns (since Sep 2026), and `deadline_note` marks "Open until filled" jobs. Add filters for salary band, start date and "open until filled". Contract length and "PhD required" need two more fields in the summary schema (`_SUMMARY_SCHEMA` in scraper/summaries.py). Mirror any new filter in `notify.py`'s `job_matches_filter` so alerts match the site.
**Evidence:** scraper/summaries.py, index.html `filterJobs()`, scraper/notify.py.

### [P2] No recent-searches / autocomplete — S-M
**Symptom:** Users repeating the same search have to retype it every visit.
**Fix:** Store last 5 searches in localStorage, show as chips below the search input when focused and empty. Optional: fuzzy-suggest keywords pulled from existing job descriptions.

### [P2] Multiselect filter dropdowns aren't keyboard-navigable — S
**Symptom:** `.ms-wrap` custom multiselects (institutions, ranks) rely on click handlers with no arrow-key / Enter / Escape support. Screen-reader and keyboard users are locked out.
**Fix:** Add arrow-key navigation + Enter-to-toggle + Esc-to-close to `ms-panel`. Add `role="listbox"` / `role="option"`.
**Evidence:** index.html:161-175.

---

## 4. Detail → Apply conversion — Are the jobs actually getting clicked?

### [P0] ~~Apply button outbound click is NOT tracked — blind funnel — S~~ ✅ DONE
**Symptom:** `trackEvent('job_detail_viewed', ...)` fires when the detail panel opens (index.html:2088), but there is no event on the actual "Apply on [University]" click. The single most important conversion on the site is invisible in GA4. We literally don't know if the site delivers value.
**Fix:** Add `onclick="trackEvent('apply_click', {job_id: ..., university: ..., rank: ...})"` to the `#panelApplyLink` anchor. Also mirror it on the table-row apply button. Five-line change.
**Evidence:** index.html:919-920, 1997-1998, 2144-2145.

### [P1] No "you might also like" section in the detail panel — S
**Symptom:** Once the panel opens, the only next action is "Apply" or close. A user deciding this job isn't for them has no path forward except scrolling back to the results.
**Fix:** At the bottom of the detail panel, render 3 related jobs (same department group OR same institution + same rank). Uses existing classification helpers. *(Health check §8.2.12)* The static job pages already list 5 related jobs (`related_jobs()` in scraper/generate_job_pages.py, Sep 2026); the panel could use the same selection.
**Evidence:** index.html panel structure around line 919.

### [P1] Apply link opens in a new tab but no return-hook — S
**Symptom:** `target="_blank" rel="noopener"` means once a user clicks Apply, they're gone from the tab and won't come back to browse more. No bookmark prompt, no "come back tomorrow", no save-to-list on click.
**Fix:** On apply click, trigger a subtle toast in the current tab: "Added to your activity — sign in to get notified when similar jobs appear." This both adds retention and drives sign-in.
**Evidence:** index.html:919.

### [P2] No per-job social share — S
**Symptom:** Users can't easily forward a job to a colleague except by copying the URL. With the static page URLs now in place (PR #2), a dedicated share affordance costs almost nothing.
**Fix:** Add a small "Share" button to the detail panel that copies `https://www.hkacadjobs.org/jobs/<slug>-<id>/` to clipboard and tracks `share_job` event. *(Health check §8.2.12)*

---

## 5. Retention — Are users coming back?

### [P0] Email alert CTA is buried — no hero-level prompt — M
**Symptom:** The only entry point to email alerts is via "Save filter" → notice alert toggle → opt in. The hero has no visible "Get weekly alerts" CTA. For an aggregator whose *retention loop is email*, this is the biggest lever we're not pulling.
**Fix:** Add a single-line signup under the hero stats row: `"Get new HK academic jobs in your inbox daily — [email field] [Subscribe]"`. This creates a low-friction subscription for "all new jobs" (no filter) in addition to the existing filter-specific alerts. Requires a new `filter_state: {}` row type in Supabase (which `notify.py` already handles correctly — empty filter = match everything). *(Health check §8.2.7)* Use double opt-in (a confirmation email before the first alert). Alerts are now reliable (fixed Sep 2026: delivery, matching, sent log, unsubscribe), so this is safe to promote. A no-account version was reverted in April; this would bring it back.
**Evidence:** index.html hero (~line 620-630), notify.py `job_matches_filter` (empty filter matches).

### [P1] No weekly digest separate from filter-alerts — M
**Symptom:** `notify.py` only sends alerts when subscribers' saved filters match `is_new=TRUE` rows. A user with a filter that doesn't match today gets silence — eventually unsubscribes or forgets the site exists.
**Fix:** Add a "weekly roundup" email sent every Monday to every confirmed subscriber, showing top 10 matching jobs regardless of `is_new`. Also sends a fallback digest to users whose filters had zero matches that week.
**Evidence:** scraper/notify.py `load_new_jobs` (only reads `is_new=TRUE`). *(Health check §8.2.8)*

### [P1] No visible social proof — S
**Symptom:** No "Join 500+ Hong Kong researchers" or "1,537 open positions tracked daily" in the hero or footer. Trust signals are absent.
**Fix:** Pull subscriber count from Supabase at build time (or periodically), render as a small pill near the hero or in the footer. Requires a nightly write of the count into a static JSON file since we don't want live DB reads from every visitor.

### [P2] Show how many people viewed a job — M
**Symptom:** Nothing tells a visitor that a job is attracting interest, a simple form of social proof and urgency.
**Fix:** Show "👀 50+ people viewed this job" in the detail panel and on the job's own page, and a small "Popular" badge in the listing for the week's most-viewed jobs. Only from 20 unique viewers in the last 30 days, shown in rounded tiers (20+, 50+, 100+, 250+): small numbers look like low interest, and tiers avoid false precision. Tune the threshold once real numbers are in (e.g. so about half the jobs show it). Source the counts from GA4, which already records `job_detail_viewed` with `job_id` and page views of `/jobs/…` pages: a nightly workflow step reads each job's unique viewers via the GA4 Data API and publishes a small `views.json` that the site and job pages read in the browser. That means no per-visit database writes, no public counter anyone could inflate, bot filtering by GA4, and the job pages stay unchanged. Counts update daily and miss visitors who block analytics, which is fine for social proof.
**Setup (owner):** a Google Cloud service account with Viewer access to the GA4 property, its key and the property ID as GitHub secrets, and `job_id` registered as a GA4 custom dimension.
**Evidence:** index.html `trackEvent('job_detail_viewed', …)`; scraper/generate_job_pages.py (job pages).

### [P1] "Closing soon" reminders for saved jobs — M *(Health check §8.2.9)*
**Symptom:** Users bookmark jobs, then miss the deadline.
**Fix:** For signed-in users with saved positions, email a reminder 3 days and 1 day before each saved job's deadline (only jobs with a real `deadline` date). Needs saved positions stored in Supabase (check whether bookmarks sync there today), then a daily pass in `notify.py`.
**Evidence:** index.html bookmarks (`toggleBookmark`), scraper/notify.py.

### [P2] "Deadline extended" and "Re-advertised" badges — S-M *(Health check §8.2.10)*
**Symptom:** When a university extends a deadline or re-posts a job, nothing tells returning users.
**Fix:** The job registry (`scraper/job_registry.json`, first and last day each job was seen) and the previous CSV make both detectable in `scraper.py`: a later deadline than yesterday's is "extended"; a job returning after a gap is "re-advertised". Store a small flag column and show a badge in the table, the panel and alert emails.
**Evidence:** scraper/scraper.py (registry logic in `main()`), scraper/job_registry.json.

### [P2] ~~Welcome modal expiry is stale code — S~~ ✅ DONE 2026-09-27
**Done:** the modal and its trigger code were removed.

**Symptom:** `WELCOME_EXPIRY = new Date('2026-04-10T00:00:00+08:00')` (index.html:2503) is already 2 days in the past as of 2026-04-12. The welcome modal no longer fires for any new visitor. Either remove the whole modal + trigger code, or refresh the expiry + the content for a new launch announcement (e.g. static pages, alerts).
**Evidence:** index.html:2502-2508.

### [P2] No re-engagement trigger for lapsed users — M
**Symptom:** A user who signed in once and then went silent for 30+ days never gets a nudge.
**Fix:** `notify.py` could check `auth.users.last_sign_in_at` and send a re-engagement email to anyone silent for 30+ days with new matching jobs. Low volume, targeted.

---

## 6. Measurement blind spots — What we can't see, we can't fix

### [P0] ~~`apply_click` missing — see item 4.1 — S~~ ✅ DONE
(duplicated here for tracking; fix once, resolves both funnel visibility and retention decisions)

### [P0] ~~`search_no_results` missing — see item 3.5 — S~~ ✅ DONE
(duplicated here for tracking)

### [P1] No funnel definition in GA4 — S
**Symptom:** Events are fired but no GA4 funnel is defined for `search → filter_active → job_detail_viewed → apply_click → alert_subscribed`. The drop-off we're analyzing in this doc is based on code reading, not production data.
**Fix:** Define the funnel in GA4 Explore once `apply_click` and `search_no_results` ship. Track weekly drop-off rate at each step. Not a code change — operations task for the repo owner. *(Health check §8.3)* Also mark `apply_click` and `alert_subscribed` as key events, set event data retention to 14 months, register `university`, `rank`, `source` and `filter_type` as custom dimensions, and link Search Console (step-by-step guide given 2026-09-27). Apply clicks on static job pages arrive with `source: static_page`.

### [P1] Sign-in isn't tracked — S
**Symptom:** No event fires when someone completes the email (magic-link) sign-in, so sign-ups can't be a GA4 key event or a funnel step.
**Fix:** Send GA4's recommended `login` event (`method: 'magic_link'`) from the Supabase `onAuthStateChange` `SIGNED_IN` handler, and `sign_up` when the account is new (e.g. `created_at` within the last minute).
**Evidence:** index.html `_sb.auth.onAuthStateChange`, `sendMagicLink`.

### [P1] Weekly owner report email — M *(Health check §8.3)*
**Symptom:** The owner has to open GA4, Supabase and GitHub separately to see how the site is doing.
**Fix:** A weekly workflow emails a one-page summary: visitors and apply clicks (GA4 Data API), new subscribers and alert emails sent (Supabase, `scraper/alert_log.json`), per-institution scrape health (`scraper/scrape_health.json`) and broken apply links (`scraper/check_links.py`).
**Evidence:** scraper/health.py, scraper/check_links.py, scraper/notify.py (Resend sender).

### [P1] Search Console follow-up — S (owner task) *(Health check §8.3)*
**Symptom:** Job pages were rebuilt in Sep 2026 (valid JobPosting data, closed-job pages, real `lastmod` dates), but Google hasn't re-crawled them yet.
**Fix:** Resubmit `sitemap.xml`, then over the following weeks watch the Job Posting enhancement report (errors should fall towards zero), pages indexed vs submitted, and queries by page.

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

## 9. Operations & monitoring

### [P2] Email scrape-health alerts with details (`HEALTH_ALERT_EMAIL` secret) — S
**Symptom:** When the daily run finds a problem (an institution crashed, came back empty or far below its usual count, alert emails failed, or `jobs.csv` has malformed rows), the *Check scrape health* step fails the run and GitHub sends its generic "run failed" email. The details (which institution, how many jobs, how many were kept from the previous run) are only on the run page.
**Fix:** Add a repository secret `HEALTH_ALERT_EMAIL` (GitHub → Settings → Secrets and variables → Actions → New repository secret) with the address to notify. No code change is needed: `scraper/health.py` and `scraper/check_links.py` already send a Resend email with the per-institution table and the run link whenever it is set.
**Evidence:** `scraper/health.py` (`send_alert`), `scraper/check_links.py`, `.github/workflows/scrape.yml` and `check-links.yml` (`HEALTH_ALERT_EMAIL` env).

### [P2] Refresh a summary when the job ad changes — M
**Symptom:** Each job is summarised once and the summary is reused (Sep 2026). If a university edits the ad, the summary keeps the old text (the listing's deadline always wins over the summary's). A job that disappears for a while and returns is re-summarised, because summaries live only in `jobs.csv`.
**Fix:** A small summary store keyed by job id plus a hash of the raw ad text (the health check's §2.3 idea): reuse on a match, re-summarise on change, keep entries ~60 days after a job leaves.
**Evidence:** scraper/scraper.py (`_has_good_desc`, summary reuse in `main()`), scraper/summaries.py.

### [P2] Fill `date_posted` for more portals; add organisation logos to JobPosting — S-M
**Symptom:** Only PolyU, EdUHK, HKBU and Lingnan provide a posting date; job pages' JobPosting data then falls back to the day the job was first seen, and has no `hiringOrganization.logo`.
**Fix:** Read the posting date where each portal shows one (per `scraper/sites/<institution>.py`), and add a logo URL per institution next to `INSTITUTION_SITES` in scraper/generate_job_pages.py.

### [P2] Scraper speed-ups — M
**Symptom:** None urgent: a full run takes about 20 minutes including summaries (it took 25–110 before Sep 2026).
**Fix:** A shared Playwright browser across institutions, condition waits instead of fixed sleeps, and scraping institutions in parallel.

### [P2] Deploy job pages without committing them — M
**Symptom:** Generated HTML under `/jobs/` is committed daily. Pages are now rewritten only when a job changes, so repository growth has slowed a lot, but it still grows.
**Fix:** Build the pages in the workflow and deploy with `actions/deploy-pages` instead of committing them.

---

## Priority summary (quick-pick for next sprint)

*Updated 2026-09-28.* Most of the April P0s have shipped (✅ above). The September health check fixed alerts,
scraping, data accuracy and job-page SEO, so the retention loop now works and it's worth growing.

**Growth, in suggested order:**
1. Hero "email me all new jobs" signup with double opt-in (§5): alerts are reliable now, so this is the main retention lever.
2. Programmatic landing pages (§1): institutions, ranks, disciplines, "closing this week". The biggest organic lever.
3. Weekly digest and "closing soon" reminders (§5): keep subscribers engaged on quiet weeks.
4. Social distribution and RSS / Telegram (§1): cheap to add to the daily workflow.
5. Traditional and Simplified Chinese (§1).
6. Richer filters from the structured summaries (§3).
7. Partnerships, backlinks and the embeddable widget, and evergreen guides (§1).

**Owner tasks (no code):** GA4 key events, funnel and custom dimensions (§6); Search Console follow-up (§6);
`HEALTH_ALERT_EMAIL` secret (§9); partnership outreach (§1).

**P1 backlog:** Homepage ItemList schema, fonts preload, saved-filter prompt, related jobs in the panel, apply return-hook, social proof, last-scrape pill, ARIA pass, sign-in tracking, weekly owner report.

**P2 backlog:** Job view counts, skeleton rows, service worker / PWA / web push, per-job share, recent searches, keyboard-navigable multiselects, emoji aria, skip link, source attribution, re-engagement email, A/B harness, "extended / re-advertised" badges, summary refresh, `date_posted` and logos, scraper speed-ups, deploy pages without committing.

---

## Not addressed here (out of scope)

- Job data quality / scraper coverage gaps (covered by `HEALTH_CHECK_2026-09.md`)
- Pricing / monetisation model (no business decision to review)
- Infrastructure cost / GitHub Pages limits (no reported issue)
- Moderation / reporting flows (existing report modal is sufficient for current volume)
