# CV matching: review and launch checklist

**Where things stand (30 Sep 2026)**
- **The branch:** everything is on `claude/gallant-mendel-d4hyab`, and nothing on the live site has changed.
- **The live Supabase project:** already has the database tables and the `match-jobs` function.
- **What's missing:** the function can't analyse a CV until it has a Claude API key (step 1 below).
- **More detail:** the design is in `CV_MATCH_PLAN.md`; how it all works is in README.md, "CV matching".

## 1. Before you review (about 10 minutes)

1. **Give the function a Claude API key.**
   - Create a key just for this in the Anthropic Console, so its spend is easy to follow.
   - Add it in Supabase → Edge Functions → Secrets as `ANTHROPIC_API_KEY`.
   - Until then, "Analyse my CV" ends with "Something went wrong".
2. **Let sign-in links come back to your computer.** In Supabase → Authentication → URL Configuration → Redirect URLs, add `http://localhost:8000/**`. Without it, the sign-in link takes you to the live site instead.
3. **Set a monthly spend limit** in the Anthropic Console, as a hard stop on top of the site's own limits.
   - The site's limits: US$10 a day for users, US$3 a day for alert emails.
   - Each user can analyse 3 CVs and run 10 matches a day.

## 2. Review it on your computer

In the folder where you keep the repository:

```
git fetch origin claude/gallant-mendel-d4hyab
git checkout claude/gallant-mendel-d4hyab
python3 -m http.server 8000
```

Then open **http://localhost:8000/?beta=match**. Use `localhost` rather than your computer's network address. The `?beta=match` switch is remembered in that browser; `?beta=off` hides the feature again.

Things to try:
- [ ] **Signed out:** click "✨ Find jobs that fit your CV" in the header area. You should see the short intro, then "Sign up free".
- [ ] **Sign in:** use the emailed link. It opens a new tab, signed in, straight at "Add your CV".
- [ ] **Add your CV:** upload your own CV as a PDF or Word file. "Check the text we'll send" shows exactly what leaves your browser, with the contact details taken out.
- [ ] **Check the profile:** adjust it if needed, tick "Save my profile and email me new jobs that fit it", then click "Find my matches". It takes about a minute.
- [ ] **Read the reasons:** open a match and read "Why this may suit you". Are the reasons fair and useful?
- [ ] **My CV profile** (in the account menu): switch the alerts off and on, and try deleting the saved profile.
- [ ] **Web page tab:** try a university staff page. Also try a LinkedIn link, which should be turned away with a tip.
- [ ] **Signing out:** your matches should disappear from that browser.

Each full run costs about US$0.08, or US$0.10 from a web page link. Screenshots of every step, on a desktop and a phone, were shared in the Claude session on 30 Sep. They use placeholder match reasons, not Claude's.

A phone can't reach `localhost`. To test on your phone, open the live site with `?beta=match` after the branch is merged. The feature stays hidden from everyone else until step 3.5 below.

## 3. Before going live

1. **Sign-in emails.**
   - Supabase's built-in email service sends only a few sign-in emails an hour, so a sign-up rush would be throttled.
   - Set up your own sender under Supabase → Authentication → Emails → SMTP settings. Resend, which already sends the alerts, works.
   - Then raise the email rate limit.
2. **Automatic function deploys (optional for now).** The function is already deployed. To deploy future changes by themselves:
   - Add the GitHub repository secrets `SUPABASE_ACCESS_TOKEN` (Supabase → Account → Access Tokens) and `SUPABASE_PROJECT_REF` (value `xdlarqwycodfoahmkvha`).
   - Then run *Deploy functions* in the Actions tab once.
3. **Google Analytics.** Mark `sign_up` and `cv_match_results` as key events. That shows how many sign-ups the feature brings.
   - The funnel is `cv_match_cta_click` → `cv_match_intro` → `cv_match_signin_prompt` → `magic_link_sent` → `sign_up` → `cv_match_submit` → `cv_match_profile` → `cv_match_results` → `apply_click` with `source` = `cv_match`.
   - To break these down, register `where`, `input` and `code` as custom dimensions.
4. **Read the privacy wording** (About → Privacy, also linked from the footer).
   - It's written as a collection notice in the spirit of Hong Kong's privacy law (PDPO).
   - Check that it says what you're happy to promise. In particular, check the line about Anthropic not training on the data against the terms of your API account.
5. **Launch.**
   - Set `CV_MATCH_PUBLIC = true` in `index.html`, and add a launch banner (`BANNER_VERSION`) if you'd like one.
   - Merge the branch into `main` through a pull request. A Claude session can do all of this on request.
   - Match alert emails start with the first daily run after the merge.

## 4. Optional

- **Quality check with Claude.** This runs the eight test CVs through the real pipeline, costs about US$0.70, and prints the matches for us to judge.
  - It needs an Anthropic key in the environment that runs it. Either add `ANTHROPIC_API_KEY` to the Claude Code environment's settings, which applies to new sessions, and ask Claude to run it, or run it yourself:
    `cd supabase/functions/match-jobs && ANTHROPIC_API_KEY=… deno task eval`
- **Hide subscribers' email addresses in the Actions logs.**
  - The existing filter alerts print each subscriber's full email address in the public GitHub Actions log ("✅ Sent to …").
  - The new match alerts print a masked form (`n***@example.com`). The same for the old lines would be a two-line change.
- **Supabase advisor warnings that predate this work:**
  - `saved_jobs` and `saved_filters` policies re-check sign-in for every row, which is slower than needed.
  - `rls_auto_enable` can be called by signed-out visitors.
  - Leaked-password protection is off. That doesn't matter with magic links, but it's flagged.
  - `subscriptions.user_id` has no index.

## Changes made on the live Supabase project

- **29–30 Sep:**
  - The database side, as the migrations `cv_match_2026_10` and `cv_match_2026_10_policy_select_auth`:
    - the `match_usage` and `match_profiles` tables;
    - the `match_quota_status` function;
    - `unsubscribe_alert`, which now also stops match alerts.
  - The `match-jobs` function, deployed as version 1.
- **30 Sep:** migration `cv_match_2026_10_profile_prefs`, which adds a `prefs` column to `match_profiles` (then empty) so alert emails respect the institutions a user chose.

## What has and hasn't been checked

**Checked**
- A 60-step browser walkthrough, on a desktop, a 390 px phone, and with the feature switched off. Sign-in, the database and the function were stubbed.
  - Every step of the journey worked.
  - Only the redacted text is sent.
  - Chinese text in a PDF is read.
  - Nothing new loads while the feature is switched off.
- 84 Python tests and 46 function tests. They include the new alert email, the institution choices and the 90-day clean-up.

**Not yet checked**
- Claude's real profiles and reasons: that needs the key (steps 1 and 4).
- A real sign-in email round trip on `localhost`.
- Safari on an actual iPhone: the walkthrough used Chromium's phone mode.
