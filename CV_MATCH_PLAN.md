# CV matching: implementation plan

**Status (30 Sep 2026):** All three phases are built on the `claude/gallant-mendel-d4hyab` branch. Nothing on the live site has changed.
- **Live Supabase project:** has the database side, applied as the migrations `cv_match_2026_10`, `cv_match_2026_10_policy_select_auth` and `cv_match_2026_10_profile_prefs`. `match-jobs` version 1 is deployed.
- **Before it can match anything:** the function needs the `ANTHROPIC_API_KEY` secret.
- **Owner's steps:** reviewing locally and launching are covered in `CV_MATCH_LAUNCH.md`; the setup is in README.md, "CV matching".
- **Where the build differs from this plan:** each phase ends with an "As built" note.

Decisions made with the owner: sign-in required, no LinkedIn, Claude Sonnet 5.5, and nothing stored unless the user opts in to a saved profile with match alerts.

## Context

HKAcadJobs is a static GitHub Pages site. The whole app is `index.html`, which reads `jobs-lite.csv`/`jobs.csv`, about 1,560 open jobs from 17 institutions. Supabase provides the magic-link sign-in and the saved jobs, saved filters and alert subscriptions. A daily GitHub Actions run scrapes the jobs, summarises each ad with Claude Haiku 4.5 (`scraper/summaries.py`), builds the job pages and emails alerts (`scraper/notify.py` → Resend). Today visitors can only search and filter, and few have a reason to create an account.

The new feature lets **signed-in users** give us their **CV** (PDF, Word or pasted text) or a **personal or academic website link**. Claude reads it and builds a profile: field, specialisms, seniority, qualifications and languages. We compare that profile with every open job and show the best fits, each with a short "why this fits you" and any gaps. Users can **opt in** to save the profile and get emails when new jobs fit it.

Requiring sign-in turns the feature into the main reason to sign up. It gives us a verified email per user, and it replaces IP-based rate limits with simple per-account limits. The site has no server code, and the Claude API key must stay secret, so the analysis runs in a small **Supabase Edge Function**. Supabase is already part of the stack.

**Decisions made with the owner**
- **Sign-in required** (the existing magic link). Signed-out visitors see the feature everywhere and are asked to sign up free to use it.
- **No LinkedIn**: the inputs are CV upload, pasted text and personal or academic website URLs.
- Model: **Claude Sonnet 5.5** (`claude-sonnet-5-5`, $2 / $10 per million tokens). It is set by one secret (`MATCH_MODEL`), so it can be changed later.
- **The CV is never stored.** Users can opt in to save the extracted profile (never the file) and get match alerts.

**Cost estimate (Sonnet 5.5):** about US$0.08 per match, or about US$0.10 from a website link (measured on 30 Sep: about US$0.05 for a CV's profile and matches, US$0.42 for the eight test CVs) (≈18k input and 5k output tokens over two calls). Match alerts cost about US$0.02 per saved profile, and only on days when new jobs are candidates.

## Architecture

```
Browser (index.html hooks + new cv-match.js, loaded only when used)
  0. Signed out: "Find jobs that fit your CV" → short intro → sign up / sign in (magic link);
     intent saved in localStorage so the flow reopens after the link is clicked
  1. PDF/DOCX/text → plain text in the browser (vendored pdf.js / mammoth); emails, phones, HKIDs removed
  2. POST match-jobs {action:"profile", text | url}      → profile (shown to the user, editable)
  3. POST match-jobs {action:"match", profile, prefs}    → up to 12 matches {job_id, score, fit, why, gaps}
  4. "For you" view in the job table + "Why this may suit you" in the detail panel (kept in localStorage)
  5. Opt-in: "Save my profile and email me new jobs that fit it" → match_profiles row (RLS: own row)

Supabase Edge Function  supabase/functions/match-jobs  (Deno/TypeScript, @anthropic-ai/sdk)
  CORS (hkacadjobs.org + localhost) → requires a signed-in user's token (or service_role for alerts)
  → per-user daily quota + site-wide budget (match_usage) → action → log tokens/cost/outcome (never CV text)
  profile: Claude + structured output (+ web_fetch tool for URLs, limited to that site)
  match:   jobs.csv (cached 30 min) → open jobs → keyword shortlist of 40 → Claude re-ranks → validate IDs

Daily workflow (scrape.yml → notify.py → new match_alerts.py)
  for each opted-in profile: POST match-jobs {action:"match", profile, only_ids: today's new jobs} as
  service_role → email the fits via Resend (reuses send_email, alert_log, unsubscribe link)
```

Why this shape:
- **One copy of the matching logic.** It lives only in the function. The alert run calls the function instead of copying the logic into Python.
- **Job text comes from the server.** The function loads `jobs.csv` itself and the client sends only a profile, so our API key can't be used on arbitrary text.
- **Privacy.** The CV is read in the browser and contact details are removed before anything leaves it.
- **Cost.** The text sent is far smaller than a whole PDF.
- **Fetching links is done by Anthropic.** The web fetch tool reads the user's link on Anthropic's servers, so our function never fetches arbitrary URLs, and `allowed_domains` limits it to that one site.

## Phase 1: Matching service (edge function, database, CI and deploy)

**New: `supabase/functions/match-jobs/`**, with a `deno.json` import map pinning `npm:@anthropic-ai/sdk@0.129.0` and `jsr:@std/csv`. The database is reached through plain PostgREST calls, so neither zod nor supabase-js is needed.
- `index.ts`: the request handler.
  - CORS preflight; only `https://www.hkacadjobs.org` and localhost are allowed.
  - Checks the caller's token with Supabase Auth (`/auth/v1/user`) and accepts only a signed-in user, not a Supabase anonymous account (`is_anonymous`). The alert run is recognised by the service key itself.
  - The public anon key alone gets 401 `sign_in_required`, which the site turns into the sign-up prompt.
  - `MATCH_ENABLED=false` is a kill switch that returns 503.
- `jobs.ts`
  - Fetches `JOBS_CSV_URL` (default `https://www.hkacadjobs.org/jobs.csv`) and caches it for 30 minutes in module scope.
  - Refetches with `?v=<now>` if requested `only_ids` are missing, e.g. just after the daily deploy.
  - Keeps open jobs using the same rule as `is_active()` in `scraper/generate_job_pages.py:121`: an empty deadline, or a deadline ≥ today in Hong Kong time.
  - Parses the summary's `**Duties & Responsibilities**`, `**Requirements & Qualifications**` and `**Appointment**` sections, the same `**Section**` + `•` format read by `descriptionHtml()` (index.html:2400) and `render_description_html()` (generate_job_pages.py:217).
  - Descriptions containing the site's BOT_MARKERS are treated as empty.
- `shortlist.ts`: pure code, no LLM.
  - BM25-style score over title ×3, department ×2 and duties + requirements ×1.
  - The query is built from the profile's `search_terms`, `specialisms`, `disciplines` and `skills`. Multi-word terms are matched as phrases, and Chinese text as character pairs.
  - The score is multiplied by a rank factor: 1.0 if the job's rank is in `suitable_ranks`, 0.8 for `Other`, 0.5 otherwise.
  - Hard filters: open jobs only, the chosen role type (academic / non-academic via the `ACADEMIC_RANKS` labels, index.html:1229), and any institutions the user picked.
  - Keeps the top 40. For alerts, keeps at most 10 above a minimum score; with no candidates, no Claude call is made.
- `claude.ts`: prompts, JSON schemas (sent as `output_config.format`; replies are checked in `validate.ts`) and the calls.
  - `thinking` is omitted, so it is adaptive. `effort` is set explicitly: `low` for the profile, `medium` for ranking (Sonnet 5.5 defaults to `high`).
  - `max_tokens` is 4k for the profile and 8k for ranking. Timeout 60 s, `maxRetries: 1`.
  - Server-side refusal fallback is on (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`), as recommended for Sonnet 5.5.
  - `stop_reason` is checked for `refusal` and `max_tokens` before any output is used.
  - **Profile schema** (no name, contact details, age, gender, nationality or photo):
    - Text: `headline`, `summary`.
    - Enums: `career_stage`, `highest_degree`, `role_type`, `looks_like_cv`.
    - Numbers and labels: `years_experience`; `suitable_ranks` is a list of the site's `RANK_OPTIONS` labels (index.html:1233).
    - Lists: `disciplines`, `specialisms`, `skills`, `languages`, and `search_terms` (15–40 terms, including synonyms and Chinese equivalents where useful).
  - **URL input** (as built, two calls): Claude reads the page with `{type:"web_fetch_20260209", name:"web_fetch", max_uses:2, allowed_domains:[host], max_content_tokens:10000}` and writes plain notes of at most 400 words. Contact details are removed from the notes, which then go through the same profile step as a CV. This avoids depending on web fetch and structured output working together.
    - `pause_turn` is resumed at most twice.
    - A failed fetch, or an "UNREADABLE" reply, becomes the message "we couldn't read that page — upload your CV instead".
    - ORCID-specific handling was left out: ORCID pages need JavaScript, so users with only an ORCID link are asked for their CV.
  - **Ranking prompt:** acts as a Hong Kong higher-education recruiter.
    - Weighs discipline fit, seniority against rank, required degree or registration, years of experience and language requirements (Cantonese / Putonghua).
    - Must never use personal characteristics. Leaves out poor fits.
    - Output: `matches[{job_id, score 0–100, fit: strong|good|possible, why (1–2 sentences, "Your …"), gaps[≤2]}]` plus an overall `advice` line.
  - CV and page text are wrapped as data, and the prompt tells the model to ignore any instructions inside them.
- `validate.ts`
  - Request limits: text ≤ 40k characters; URL must be http(s), not linkedin.com, ≤ 500 characters; profile JSON ≤ 8 KB with lists capped and enums checked.
  - A server-side copy of the contact-detail removal, as a backstop.
  - Output clean-up: drop IDs outside the shortlist, remove duplicates, clamp scores, trim text, sort, and cap at `limit` (12 for users, 5 for alerts).
- `usage.ts`: quotas and the budget in the `match_usage` table, accessed with the service key that Supabase provides to the function.
  - Per account: 3 CV analyses and 10 match runs per day.
  - Site-wide `DAILY_BUDGET_USD=10`, which protects against mass sign-ups by bots. Alert budget `ALERT_DAILY_BUDGET_USD=3`.
  - Cost is computed from `usage` tokens × a small price table.
  - Limit responses: 429 with "try again tomorrow", or 503 "matching is paused for today". All limits are environment variables.
- Tests: `*_test.ts` next to each module, with a `testdata/` fixture.
  - Fixture: a ~200-row snapshot of `jobs.csv` plus 8 synthetic persona profiles, one of them in Chinese. Examples: a new PhD in computational biology, an associate professor in finance, an IT systems administrator, a nursing lecturer, an HR officer, a civil-engineering PhD.
  - Expected relevant job IDs are labelled by hand.
  - The handler is tested with an injected fake Anthropic client, in the same pattern as `FakeClient` in `scraper/tests/test_summaries.py`.

**New: `supabase/2026-10-cv-match.sql`**, run once in the SQL editor like `supabase/2026-09-alert-fixes.sql`.
- `match_usage(id, created_at, user_id → auth.users on delete cascade (null for alert runs), action, model, input_tokens, output_tokens, cost_usd, outcome)`.
  - Indexes on `(user_id, created_at)` and `(created_at)`.
  - RLS on with no policies, so only the service role can access it.
  - A commented query for daily spend and sign-ups that used the feature, and a cleanup of rows older than 90 days.
- `match_profiles` and the updated `unsubscribe_alert` function are in the same file (see Phase 3).

**New: `supabase/config.toml`**: `[functions.match-jobs] verify_jwt = true`.
**New: `.github/workflows/deploy-functions.yml`**
- Runs on pushes to `main` that touch `supabase/functions/**`, and on manual dispatch.
- Uses `supabase/setup-cli` → `supabase functions deploy match-jobs --project-ref $SUPABASE_PROJECT_REF`.
- Secrets: `SUPABASE_ACCESS_TOKEN` and `SUPABASE_PROJECT_REF`.

**Edit: `.github/workflows/tests.yml`**
- Adds a `functions` job: `denoland/setup-deno` → `deno fmt --check`, `deno lint`, `deno check`, `deno test`.
- Adds `supabase/functions/**` and `cv-match.js` to the path triggers.

**Edit: `.gitignore`**: add `supabase/.env.local`, `supabase/.temp/` and `supabase/.branches/`.

## Phase 2: Site UI, sign-up funnel and matching (soft launch behind `?beta=match`)

**Sign-up funnel** (`index.html`)
- **Entry points, shown to everyone including signed-out visitors:**
  - a hero call to action under `.stats-row`: "✨ Find jobs that fit your CV — free with an account";
  - a nav button;
  - a link in the empty state (`buildEmptyState()`, index.html:2208);
  - later, a site banner (`BANNER_VERSION`, index.html:2638).
- **Signed-out click:** opens a short intro in the match modal (how it works, 3 steps; "your CV is never stored") with **Sign up free / Sign in**. That button opens the existing auth modal (`openAuthModal()`, index.html:2867) with the feature's own heading and subtext. `openAuthModal(context)` takes an optional copy variant; the default copy is unchanged.
- **Resuming after sign-in:**
  - Before the magic link is sent, `localStorage['hkaj_intent'] = 'cv_match'` is set. The link opens in a new tab.
  - In the `onAuthStateChange` `SIGNED_IN` branch (index.html:3109), if the flag is set, it is cleared first and the match modal opens at the upload step.
  - The DB-sync deferral already in that handler is kept.
- **Analytics:**
  - GA4 `login` / `sign_up` events (`method: 'magic_link'`, `source: 'cv_match'` when the intent flag is set). `sign_up` fires when the user's `created_at` is within the last few minutes. This also completes the BACKLOG item "Sign-in isn't tracked".
  - The funnel: `cv_match_cta_click` → `cv_match_signin_prompt` → `sign_up` → `cv_match_submit {input}` → `cv_match_profile` → `cv_match_results {count, top_score}` → `cv_match_alert_on` → `apply_click {source:'cv_match'}`. Plus `cv_match_error {code}`.
- **Sign-out:** `signOut()` (index.html:2906) also removes `hkaj_match` and `hkaj_intent`, like it clears bookmarks and saved filters, so results aren't left on shared computers.

**New: `cv-match.js`.** A plain script loaded on demand by a small `ensureCvMatch()` loader in index.html, so first paint is unaffected. It uses the page's globals (`ALL_JOBS`, `_sb`, `_currentUser`, `esc`, `trackEvent`, `openPanel`, `renderTable`, `openAuthModal`).
- **Match modal**, built on the existing `.modal-overlay` / `.modal` styles (index.html:455).
  - Step 1: tabs *Upload CV* (PDF, DOCX or TXT, ≤ 5 MB), *Paste text* and *Website link*. A LinkedIn URL gives an inline hint to upload the CV instead. A privacy note and a consent checkbox are required.
  - Step 2: staged progress messages (reading → analysing → comparing with N open positions → ranking).
  - Step 3: profile review. Shows the headline and summary. Editable chips for role type, suitable ranks and key topics; optional institutions (reuses the site's list).
  - Step 3 also has an unticked, opt-in checkbox: **"Save my profile and email me new jobs that fit it"**.
  - Step 3 button: **Find my matches**.
- **File reading.** pdf.js (legacy build, for older iPhones) and mammoth are vendored under `vendor/pdfjs/` and `vendor/mammoth/` with licences, pinned and same-origin, and loaded only when a file is picked.
  - A PDF with no text layer (a scan) asks the user to paste the text.
  - Text over 40k characters is cut with a visible notice, never silently.
  - Emails, phone numbers (+852 and general formats) and HKID numbers are removed before sending.
- **Calls** use `_sb.functions.invoke('match-jobs', {body})`, which sends the user's session token, with a 120 s abort.
  - Errors map to friendly messages: limit, paused, unreadable link, not a CV.
  - A 401 (e.g. the session has expired) sends the user back through sign-in.
- **"For you" view**
  - `currentView = 'matches'` and `body.matches-view`. The filter bar, posted chips and sort bar are hidden, as `.saved-view` does (index.html:152, 600).
  - A header card shows the profile headline, "Matched on <date> · N open positions scanned", and the buttons **Edit profile**, **Start over** and, if not yet opted in, **Email me new jobs like these**.
  - Rows keep score order, with a fit pill (Strong / Good / Worth a look) and a one-line `why`.
  - A "✨ For you" nav button appears when matches exist.
  - State is kept in `localStorage['hkaj_match']` (profile, matches, date), wrapped in try/catch. Jobs no longer in `ALL_JOBS` are dropped.
- **Detail panel**: when the job is a match, a "Why this may suit you" section (why + gaps + an "AI suggestion — check the full ad" note) goes above "About the Role".

**Other edits to `index.html`** (small hooks only)
- `switchTab()` (index.html:2016), `filterJobs()` (index.html:2033: in the matches view, `filtered` = matched jobs in score order and `applySortOrder()` is skipped), `renderTable()` (index.html:2258: fit pill and why line), `openPanel()` (index.html:2424: reasons section), the `popstate` handler (index.html:2497) and `initUI()` (index.html:1916: `?view=matches` is restored like `?view=saved`).
- Auth modal copy (index.html:934), "Sign in to save positions, filters & job alerts", now also mentions CV matching.
- **About modal**:
  - "How it works" no longer says "no backend"; it describes CV matching for account holders.
  - A short **Privacy** section, linked from the footer and written as a collection notice under Hong Kong's privacy law (PDPO): CV text is analysed by Anthropic's Claude API and never stored; opt-in saved profiles; per-account usage logs kept 90 days; processors are Supabase, Anthropic, Resend and Google Analytics; how to delete your profile or account data.
- Launch: after verification, set `CV_MATCH_PUBLIC = true`. Until then the entry points need `?beta=match`. Bump `BANNER_VERSION` with a sign-up-focused announcement.

**As built (30 Sep 2026)**

*Calling the function and sign-in*
- **Calls** use plain `fetch` with the session's access token and the anon key, not `functions.invoke`, so the site gets the function's own error codes. The time limit is 150 s.
- **Sign-up vs sign-in:** a `sign_up` event is sent when the email was confirmed at this sign-in (`email_confirmed_at` equals `last_sign_in_at`). `created_at` can't be used, because the account is created when the link is *requested*.
- **Resuming after the magic link:** only the tab the link opens (with the sign-in tokens in its address) counts the sign-in and reopens the flow, so an older tab doesn't do it too. The intent expires after 3 hours.
- **Extra events:** `cv_match_intro`, `magic_link_sent`, `cv_match_alert_off`, `cv_match_profile_deleted`, and `where` on the funnel events.

*Screens*
- **Fit labels** (Strong fit / Good fit / Worth a look) also show next to matching jobs in the full listing. The reason line shows only in the "Jobs that fit you" view.
- **"For you" nav button:** appears only once there are matches. On phones it's just ✨ and the count, and the account button shows only its icon, so the nav fits.
- **Results header:** has "← All jobs". Back and Forward move between that view and the listing.
- **Reading CVs:**
  - PDFs are read up to 30 pages, and text is cut at 39,000 characters with a notice.
  - "Check the text we'll send" shows exactly what leaves the browser, after contact details are removed.
  - The drop zone folds away once a file is read.
- **Privacy:** a short notice in the modal ("How we handle your CV"), and the full notice in About → Privacy, which the footer links to.
- **Consent tick:** remembered in the browser until sign-out.

*Loading and switching on*
- `cv-match.js` and `cv-match.css` load together, with `?v=CV_MATCH_VERSION` so a new release isn't mixed with a cached copy. They load at startup only when the browser already holds matches.
- **Beta flag:** `?beta=match` is remembered in the browser (`hkaj_beta`); `?beta=off` forgets it.

*Also fixed along the way*
- **Phones:** the sort bar made pages 32 px wider than a 390 px screen, which pushed every pop-up to the right. It now wraps.
- **Escape key:** pressing it with no job open no longer adds a browser history entry.
- **Unsubscribe page:** the wording now covers both kinds of alert.

*Not done yet:* the launch banner (`BANNER_VERSION`), which goes with the launch.

## Phase 3: Opt-in saved profile and "jobs that fit you" alerts

**SQL (same file as Phase 1)**
- `match_profiles(user_id uuid pk → auth.users on delete cascade, email, profile jsonb, alerts_enabled bool, token text unique, created_at, updated_at)`.
- RLS policy: users can only read and write their own row (`auth.uid() = user_id`), and `email` must equal `auth.jwt()->>'email'`.
- `create or replace function public.unsubscribe_alert(p_token)`: keeps the current body unchanged and also sets `match_profiles.alerts_enabled = false` for that token. The site's existing `?unsubscribe=` flow (index.html:2787–2829) then works for match emails with no client change.

**UI** (`cv-match.js`)
- Ticking the opt-in, either at review or through the results button, upserts `match_profiles` with the profile, the session email, `alerts_enabled = true` and a token from `crypto.randomUUID()`, as `toggleFilterAlert()` (index.html:3047) does.
- The account menu (index.html:644) gets **"My CV profile"**: re-run matches from the saved profile with no re-upload, match alerts on/off, and delete the saved profile.

**New: `scraper/match_alerts.py`**, called from `notify.py main()` after the filter alerts.
- `get_match_profiles()` uses the existing `_get_all()`. The function is called with `SUPABASE_URL/functions/v1/match-jobs` and the service key, 4 profiles at a time, only when there are new jobs.
- Jobs already sent are skipped using `_sub_key(token)` with `load_alert_log()` / `save_alert_log()`.
- `render_match_email()` follows `render_email()`'s layout and adds a `why` line per job. It links with `job_page_url()` and sends with `send_email(..., unsub_url=unsubscribe_url(token))`.
- A failed send makes `notify.py` exit non-zero, so `health.py` reports it as it does today.
- `--dry-run` and `--test-email` also cover match alerts.
- No workflow change is needed: `scrape.yml` already passes `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`.

**As built (30 Sep 2026)**
- **Institution choices:** `match_profiles` also has a `prefs` column (`{"unis": [...]}`), added by the migration `cv_match_2026_10_profile_prefs`. The alert run passes it to the function, so the emails respect those choices.
- **Saving a profile:** a new row gets a new unsubscribe token; saving again updates the row and keeps the token, so links in earlier emails still work.
- **Usage records:** the alert run deletes rows older than 90 days, as the privacy notice promises. It does this with a PostgREST `DELETE` as the service role. A failure only warns, and the next day's run tries again.

**New: `scraper/tests/test_match_alerts.py`** (monkeypatched HTTP and `send_email`)
- No call when there are no new jobs.
- Jobs already sent are excluded.
- Titles and `why` text are escaped in the email.
- The unsubscribe link carries the token.
- A failed send is reported.

## Docs

- `README.md`: Features, Project structure (`supabase/functions/`, `cv-match.js`, `vendor/`), Deployment (function secrets, deploy workflow, spend limits) and Privacy.
- `CHANGELOG.md`: a new dated entry.
- `BACKLOG.md`:
  - mark "Sign-in isn't tracked" done;
  - follow-ups: embeddings (e.g. Voyage) for better recall if the eval shows gaps, per-job topic tags added to `_SUMMARY_SCHEMA`, merging match and filter alerts into one email, and a Chinese UI.

## Owner setup (one-off, no code)

*The up-to-date checklist, with what's already done, is `CV_MATCH_LAUNCH.md`.*

1. Run `supabase/2026-10-cv-match.sql` in Supabase → SQL Editor.
2. In Supabase → Edge Functions → Secrets, add `ANTHROPIC_API_KEY`, ideally its own key to track spend. Optional: `MATCH_MODEL`, the limits and `MATCH_ENABLED`.
3. **Check Supabase Auth email sending.** Magic links should go through a custom SMTP sender (e.g. Resend, which already sends the alerts), with a raised email rate limit, so a sign-up spike isn't throttled.
4. Add the GitHub secrets `SUPABASE_ACCESS_TOKEN` and `SUPABASE_PROJECT_REF` (`xdlarqwycodfoahmkvha`), then run *Deploy functions*.
5. Set a monthly spend limit in the Anthropic Console as the hard backstop.
6. In GA4, mark `sign_up` and `cv_match_results` as key events, to measure how many sign-ups the feature brings.

## Verification

- **Function unit tests:** `deno test`, `deno lint` and `deno fmt --check` in `supabase/functions`.
  - Shortlist: each persona's labelled jobs are in the top 40 (recall ≥ 0.8), and past-deadline or wrong-role jobs are excluded.
  - Validation: LinkedIn and non-http URLs are rejected, and oversized input returns 400.
  - Contact-detail removal.
  - Output clean-up: unknown IDs are dropped.
  - Handler with the fake client: an anon-key request → 401 `sign_in_required`; per-user quota → 429; budget → 503; kill switch → 503; `service_role` alert calls with `only_ids` work; a URL request uses web_fetch with `allowed_domains=[host]`.
- **Python:** `python -m pyflakes scraper` and `python -m pytest -q scraper/tests`, including the new alert tests. `python scraper/notify.py --dry-run` prints the match-alert recipients and jobs.
- **Local end-to-end:**
  - Run `supabase functions serve match-jobs --env-file supabase/.env.local` with a real key and send `curl` requests with a user's JWT and a synthetic CV (text and URL) to check the profile, the matches, the `match_usage` rows and the cost. The same call with only the anon key must return 401.
  - Serve the site with `python -m http.server` and use Playwright (Chromium is pre-installed), stubbing `**/functions/v1/match-jobs` with fixture responses.
  - Signed out: CTA → intro → auth modal with the feature's copy; the intent flag is set.
  - Signed in (a fake session placed in localStorage): the modal resumes at upload → synthetic PDF → review with opt-in → "For you" view → panel reasons → reload keeps matches.
  - Also check: sign-out clears the matches; the LinkedIn hint; the 401/429/503 messages; mobile width.
  - *As run on 30 Sep:* 60 checks passed, on a desktop, a 390 px phone, and with the feature switched off. Sign-in, the database and the function were stubbed, and the match reasons were placeholders. The real Claude output and a real magic-link email are still to be checked; see `CV_MATCH_LAUNCH.md`.
    - **Switched off:** nothing new shows and `cv-match.js` isn't downloaded.
    - **Signing up and in:** the magic link resumes at "Add your CV", and a `sign_up` event is sent.
    - **Reading CVs:** a PDF, including its Chinese text, and a Word file are read in the browser. A scanned PDF gets an explanation.
    - **What gets sent:** only the redacted text, with the user's token.
    - **Results:** the review, the results and the "Why this may suit you" panel all show. A reload keeps the matches, and Back/Forward move between views.
    - **My CV profile:** saving a profile and switching alerts on and off work.
    - **Messages:** the daily-limit and LinkedIn messages show.
    - **Sign-out:** clears the matches, the pending sign-in intent and the consent tick.
- **Quality check (≈ US$1):** run the 8 personas through the live pipeline once. Read the top matches and the why/gaps text, then adjust the weights, `effort` and prompts. Record the results in the PR.
- **Live smoke test after deploy:**
  - On `https://www.hkacadjobs.org/?beta=match`, sign up with a new email and confirm the modal resumes after the magic link. Run one match.
  - Check the Supabase function logs (no CV text logged), the `match_usage` cost, the GA4 `sign_up` / `cv_match_*` events, and Anthropic Console usage.
  - Exceed the per-account limit once to see the 429 message.
  - Opt in, run `notify.py --test-email`, and check the email and its unsubscribe link.
