/* HKAcadJobs — "Find jobs that fit your CV" (see CV_MATCH_PLAN.md).
 *
 * Loaded on demand by index.html (ensureCvMatch), with cv-match.css. A signed-in user adds a CV:
 * a PDF, Word or text file, pasted text, or a link to a web page about their work. Files are read
 * here in the browser, contact details are removed, and the text goes to the match-jobs Edge
 * Function (supabase/functions/match-jobs), which asks Claude for a profile of the person and then
 * for the open jobs that fit them.
 *
 * The CV is never stored. The latest profile and matches are kept in this browser (hkaj_match,
 * cleared on sign-out). If the user opts in, the profile (never the CV) is saved to match_profiles,
 * and the daily run (scraper/match_alerts.py) emails them new jobs that fit it.
 *
 * Uses the page's globals: ALL_JOBS, currentView, openJobId, _sb, _currentUser, SUPABASE_URL,
 * SUPABASE_ANON_KEY, RANK_OPTIONS, UNI_ORDER, esc, uniDisplay, fmtDate, trackEvent,
 * showActionToast, switchTab, filterJobs, openAuthModal, openAbout.
 */
(function () {
  'use strict';
  if (window.CvMatch) return;

  const BASE = new URL('.', (document.currentScript && document.currentScript.src) || location.href).href;
  const API = SUPABASE_URL + '/functions/v1/match-jobs';
  const STORE_KEY = 'hkaj_match';
  const CONSENT_KEY = 'hkaj_cvm_consent';
  const MAX_FILE_BYTES = 5 * 1024 * 1024;
  const MAX_PDF_PAGES = 30;
  const TEXT_MIN = 200;      // the function needs at least this much text…
  const TEXT_MAX = 39000;    // …and takes at most 40,000 characters
  const STALE_DAYS = 7;
  const TIMEOUT_MS = 150000;
  const ACCEPT = '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain';

  const FIT_LABEL = { strong: 'Strong fit', good: 'Good fit', possible: 'Worth a look' };
  const STAGE_LABEL = { student: 'Student', early_career: 'Early career', mid_career: 'Mid-career', senior: 'Senior', executive: 'Executive' };
  const DEGREE_LABEL = { none: '', secondary: 'Secondary school', sub_degree: 'Sub-degree', bachelor: "Bachelor's degree", master: "Master's degree", doctorate: 'Doctorate' };
  const ROLE_LABEL = { academic: 'Academic roles', non_academic: 'Non-academic roles', both: 'Both' };

  // Codes the function returns about the CV or link itself: shown next to the input
  const INPUT_ERRORS = new Set(['text_too_short', 'text_too_long', 'url_invalid', 'url_linkedin', 'url_unreadable', 'refused', 'bad_request', 'too_large']);
  const ERROR_TITLE = {
    daily_limit: "You've reached today's limit",
    budget_reached: 'CV matching is busy today',
    paused: 'CV matching is paused',
    busy: 'The matching service is busy',
    network: "We couldn't connect",
    timeout: 'This is taking too long',
    jobs_unavailable: "The job listings couldn't be loaded",
  };
  const ERROR_TEXT = {
    network: "We couldn't reach the matching service. Please check your connection and try again.",
    timeout: "The analysis took too long. Please try again. If you used a web page link, uploading your CV usually works better.",
    origin_not_allowed: 'CV matching only works on hkacadjobs.org.',
  };

  class CvmError extends Error {
    constructor(code, message) { super(message || ''); this.code = code; }
  }

  // ── State ──────────────────────────────────────────────────────────────────────
  let results = readResults();   // the latest matches: {v, user, at, profile, prefs, matches, advice, open_jobs, considered, updated}
  let userId;                    // whose results these may be; undefined until the sign-in state is known
  let saved;                     // the saved profile row: undefined = not loaded yet, null = none
  let overlay = null;
  let body = null;
  let step = '';
  let request = null;            // AbortController of the call in progress
  let stageTimers = [];
  let input = freshInput();      // what the user has given us in this visit to the modal
  let draft = null;              // the profile being reviewed: {profile, prefs, from: 'cv' | 'results'}
  let lastMatch = null;          // arguments of the last match run, for "Try again"
  let errorState = null;
  let fileToken = null;
  let optInTouched = false;
  let workingTitle = '';

  function freshInput() { return { tab: 'file', file: null, paste: '', url: '' }; }

  // ── Storage (wrapped: private browsing can refuse localStorage) ───────────────────
  function readJson(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
  }
  function writeJson(key, value) {
    try {
      if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* storage full or blocked: results just won't survive a reload */ }
  }
  function readResults() {
    const r = readJson(STORE_KEY);
    return r && r.v === 1 && r.profile && Array.isArray(r.matches) ? r : null;
  }
  function setResults(r) {
    results = r;
    writeJson(STORE_KEY, r);
  }
  function consented() { return readJson(CONSENT_KEY) === 1; }

  // ── Matches and jobs ─────────────────────────────────────────────────────────────
  function matchFor(id) {
    return results ? results.matches.find(m => m.job_id === id) : undefined;
  }
  /** Matched jobs still listed on the site, best first */
  function matchedJobs() {
    if (!results) return [];
    const byId = new Map(ALL_JOBS.map(j => [j._id, j]));
    return results.matches.map(m => byId.get(m.job_id)).filter(Boolean);
  }
  function openCountText() {
    return ALL_JOBS.length ? ALL_JOBS.length.toLocaleString('en') : '1,500+';
  }
  function hasTopics(p) {
    return (p.disciplines.length + p.specialisms.length + p.skills.length + p.search_terms.length) > 0;
  }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  // ── Contact details: removed before any text leaves the browser ─────────────────────
  // The same rules as redactContacts() in the function, which applies them again. No
  // look-behind here: older iPhones can't parse it.
  const EMAIL = /[\p{L}\p{N}._%+-]+@[\p{L}\p{N}-]+(?:\.[\p{L}\p{N}-]+)*\.\p{L}{2,}/gu;
  const HKID = /\b[A-Z]{1,2}\d{6}\s?\(?[0-9A]\)?/g;
  const PERSONAL_LINE = /(\b(?:date of birth|d\.o\.b\.?|dob|age|gender|sex|marital status|nationality|religion|hkid(?: no\.?| number)?|passport(?: no\.?| number)?|id card(?: no\.?| number)?)|出生日期|年齡|性別|國籍|婚姻狀況|宗教|身份證(?:號碼)?)[ \t]*[:：][^\n]*/gi;
  const INTL_PHONE = /\+\s?\d[\d\s().-]{6,}\d/g;
  const HK_PHONE = /(^|[^\d-])(?:\(?852\)?[\s-]?)?([2-9]\d{3})[\s-]?(\d{4})(?![\d-])/g;
  const YEAR = /^(19|20)\d\d$/;

  function redact(text) {
    let removed = 0;
    const out = text
      .replace(EMAIL, () => { removed++; return '[email]'; })
      .replace(HKID, () => { removed++; return '[id]'; })
      .replace(PERSONAL_LINE, (m, label) => { removed++; return label + ': [removed]'; })
      .replace(INTL_PHONE, m => {
        const digits = m.replace(/\D/g, '').length;
        if (digits < 8 || digits > 15) return m;
        removed++;
        return '[phone]';
      })
      // An 8-digit Hong Kong number, but not a year range such as 2019-2023
      .replace(HK_PHONE, (m, before, a, b) => {
        if (YEAR.test(a) && YEAR.test(b)) return m;
        removed++;
        return before + '[phone]';
      });
    return { text: out, removed };
  }

  function normalise(text) {
    return String(text || '')
      .replace(/\r\n?/g, '\n')
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
      .replace(/[ \t ]+/g, ' ')
      .replace(/ *\n */g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  /** The text we send: tidied, contact details removed, and cut to the function's limit */
  function prepareText(raw) {
    const { text, removed } = redact(normalise(raw));
    if (text.length <= TEXT_MAX) return { text, removed, cut: false };
    const lineEnd = text.lastIndexOf('\n', TEXT_MAX);
    return { text: text.slice(0, lineEnd > TEXT_MAX * 0.8 ? lineEnd : TEXT_MAX).trim(), removed, cut: true };
  }

  // ── Reading files (the libraries are served from this site and loaded only when needed) ──
  let pdfjs = null;
  let mammothLoading = null;

  async function loadPdfjs() {
    if (!pdfjs) {
      const lib = await import(BASE + 'vendor/pdfjs/pdf.min.js');
      lib.GlobalWorkerOptions.workerSrc = BASE + 'vendor/pdfjs/pdf.worker.min.js';
      pdfjs = lib;
    }
    return pdfjs;
  }

  function loadMammoth() {
    if (window.mammoth) return Promise.resolve(window.mammoth);
    if (!mammothLoading) {
      mammothLoading = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = BASE + 'vendor/mammoth/mammoth.browser.min.js';
        s.onload = () => (window.mammoth ? resolve(window.mammoth) : reject(new Error('mammoth missing')));
        s.onerror = () => { mammothLoading = null; reject(new Error('mammoth failed to load')); };
        document.head.appendChild(s);
      });
    }
    return mammothLoading;
  }

  async function readPdf(file) {
    const lib = await loadPdfjs();
    const task = lib.getDocument({
      data: new Uint8Array(await file.arrayBuffer()),
      cMapUrl: BASE + 'vendor/pdfjs/cmaps/',
      cMapPacked: true,
      isEvalSupported: false,
      disableFontFace: true,
      enableXfa: false,
    });
    let doc;
    try {
      doc = await task.promise;
    } catch (err) {
      task.destroy();
      if (err && err.name === 'PasswordException') {
        throw new CvmError('file', 'This PDF is password-protected. Please upload a copy without a password, or paste the text of your CV.');
      }
      throw err;
    }
    try {
      const pages = Math.min(doc.numPages, MAX_PDF_PAGES);
      const out = [];
      for (let i = 1; i <= pages; i++) {
        const page = await doc.getPage(i);
        const content = await page.getTextContent();
        let text = '';
        let lastY = null;
        for (const item of content.items) {
          if (typeof item.str !== 'string') continue;
          const y = item.transform ? item.transform[5] : lastY;
          if (lastY !== null && y !== null && Math.abs(y - lastY) > 2 && text && !text.endsWith('\n')) text += '\n';
          text += item.str + (item.hasEOL ? '\n' : '');
          lastY = y;
        }
        out.push(text);
        page.cleanup();
      }
      return { kind: 'pdf', text: out.join('\n\n'), pages: doc.numPages, skipped: doc.numPages - pages };
    } finally {
      task.destroy();   // frees the worker's copy of the file
    }
  }

  async function readDocx(file) {
    const mammoth = await loadMammoth();
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
    return { kind: 'docx', text: result.value || '' };
  }

  async function readFile(file) {
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (file.size > MAX_FILE_BYTES) {
      throw new CvmError('file', 'That file is over 5 MB. Please upload a smaller copy (a text-only PDF is usually well under 1 MB), or paste the text of your CV.');
    }
    if (ext === 'pdf' || file.type === 'application/pdf') return readPdf(file);
    if (ext === 'docx' || file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') return readDocx(file);
    if (ext === 'txt' || file.type === 'text/plain') return { kind: 'txt', text: await file.text() };
    if (ext === 'doc') throw new CvmError('file', "Older Word files (.doc) can't be read here. Please save your CV as .docx or PDF, or paste its text.");
    if (/^(pages|odt|rtf)$/.test(ext)) throw new CvmError('file', 'Please save your CV as a PDF or Word (.docx) file, or paste its text.');
    throw new CvmError('file', 'Please choose a PDF, Word (.docx) or text file.');
  }

  async function readChosenFile(file) {
    const token = {};
    fileToken = token;
    input.file = { name: file.name, status: 'reading' };
    renderFileStatus();
    try {
      const got = await readFile(file);
      if (fileToken !== token) return;   // another file was chosen meanwhile
      const prepared = prepareText(got.text);
      if (prepared.text.length < TEXT_MIN) {
        throw new CvmError('file', got.kind === 'pdf'
          ? "We couldn't find any text in this PDF. It may be a scan or a picture of your CV. Please upload the Word version, or paste the text of your CV."
          : "This file doesn't have enough text to be a CV.");
      }
      input.file = { name: file.name, status: 'ready', kind: got.kind, text: prepared.text, removed: prepared.removed, cut: prepared.cut, pages: got.pages || 0, skipped: got.skipped || 0 };
    } catch (err) {
      if (fileToken !== token) return;
      if (!(err instanceof CvmError)) console.warn('[cv-match] could not read file:', err);
      input.file = {
        name: file.name,
        status: 'error',
        error: err instanceof CvmError ? err.message : "We couldn't read this file. Please try another copy, or paste the text of your CV.",
      };
      trackEvent('cv_match_error', { code: 'file_unreadable', stage: 'file' });
    }
    renderFileStatus();
  }

  // ── Web page links ──────────────────────────────────────────────────────────────
  function checkUrl(raw) {
    let text = String(raw || '').trim();
    if (!text) return {};
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = 'https://' + text;
    let url;
    try { url = new URL(text); } catch (e) { return { error: "That doesn't look like a web address." }; }
    const host = url.hostname.toLowerCase();
    if (!/^https?:$/.test(url.protocol) || !host.includes('.')) return { error: "That doesn't look like a web address." };
    if (host === 'linkedin.com' || host.endsWith('.linkedin.com') || host === 'lnkd.in') {
      return { error: "LinkedIn profiles can't be read here. LinkedIn can save your profile as a PDF (look for “Save to PDF” on your profile), which you can upload instead." };
    }
    return { url: url.toString() };
  }

  // ── Calling the matching service ─────────────────────────────────────────────────
  async function callApi(payload) {
    let token = null;
    try {
      const { data } = await _sb.auth.getSession();   // refreshes an expired token
      token = data.session && data.session.access_token;
    } catch (e) { /* treated as signed out */ }
    if (!token) throw new CvmError('sign_in_required');

    const ctrl = new AbortController();
    request = ctrl;
    const timer = setTimeout(() => { ctrl.timedOut = true; ctrl.abort(); }, TIMEOUT_MS);
    const stopped = () => new CvmError(ctrl.cancelled ? 'cancelled' : ctrl.timedOut ? 'timeout' : 'network');
    try {
      let res;
      try {
        res = await fetch(API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token, apikey: SUPABASE_ANON_KEY },
          body: JSON.stringify(payload),
          signal: ctrl.signal,
        });
      } catch (e) {
        throw stopped();
      }
      let data = null;
      try { data = await res.json(); } catch (e) {
        if (ctrl.cancelled || ctrl.timedOut) throw stopped();
      }
      if (res.ok && data && data.ok === true) return data;
      const code = (data && typeof data.error === 'string' && data.error) ||
        (res.status === 401 ? 'sign_in_required' : res.status === 429 ? 'daily_limit' : 'http_' + res.status);
      throw new CvmError(code, data && typeof data.message === 'string' ? data.message : '');
    } finally {
      clearTimeout(timer);
      if (request === ctrl) request = null;
    }
  }

  function cancelRequest() {
    if (request) { request.cancelled = true; request.abort(); }
  }

  // ── Saved profile (match_profiles; each user can only see and change their own row) ──
  function newToken() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  }

  const SAVED_COLUMNS = 'profile,prefs,alerts_enabled,updated_at';

  async function loadSaved(force) {
    if (!_currentUser) return null;
    if (saved !== undefined && !force) return saved;
    const { data, error } = await _sb.from('match_profiles').select(SAVED_COLUMNS).eq('user_id', _currentUser.id).maybeSingle();
    if (error) throw error;
    saved = data || null;
    return saved;
  }

  async function saveProfile(profile, prefs, alertsOn) {
    const row = {
      email: _currentUser.email,   // must be the sign-in email (row-level security checks it)
      profile,
      prefs: { unis: (prefs && prefs.unis) || [] },
      alerts_enabled: alertsOn,
      updated_at: new Date().toISOString(),
    };
    let existing = await loadSaved();
    let res;
    if (!existing) {
      // A new token only for a new row, so unsubscribe links in earlier emails keep working
      res = await _sb.from('match_profiles').insert({ ...row, user_id: _currentUser.id, token: newToken() }).select(SAVED_COLUMNS).single();
      if (res.error && res.error.code === '23505') existing = true;   // saved meanwhile in another tab
    }
    if (existing) res = await _sb.from('match_profiles').update(row).eq('user_id', _currentUser.id).select(SAVED_COLUMNS).single();
    if (res.error) throw res.error;
    saved = res.data;
    return saved;
  }

  async function setAlerts(on) {
    const res = await _sb.from('match_profiles')
      .update({ alerts_enabled: on, email: _currentUser.email, updated_at: new Date().toISOString() })
      .eq('user_id', _currentUser.id).select(SAVED_COLUMNS).single();
    if (res.error) throw res.error;
    saved = res.data;
  }

  async function deleteSaved() {
    const { error } = await _sb.from('match_profiles').delete().eq('user_id', _currentUser.id);
    if (error) throw error;
    saved = null;
  }

  // ── Modal ───────────────────────────────────────────────────────────────────────
  function ensureModal() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.id = 'cvmOverlay';
    overlay.innerHTML = '<div class="modal cvm-modal" role="dialog" aria-modal="true" aria-labelledby="cvmTitle">' +
      '<button type="button" class="modal-close" aria-label="Close">✕</button><div id="cvmBody"></div></div>';
    document.body.appendChild(overlay);
    body = overlay.querySelector('#cvmBody');
    overlay.addEventListener('click', e => { if (e.target === overlay && !request) close(); });
    overlay.querySelector('.modal-close').addEventListener('click', close);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && overlay.classList.contains('open') && !request) close();
    });
    body.addEventListener('click', onClick);
    body.addEventListener('input', onInput);
    body.addEventListener('change', onChange);
    body.addEventListener('keydown', onKeydown);
    body.addEventListener('dragover', e => { const d = e.target.closest && e.target.closest('.cvm-drop'); if (d) d.classList.add('over'); });
    body.addEventListener('dragleave', e => { const d = e.target.closest && e.target.closest('.cvm-drop'); if (d) d.classList.remove('over'); });
    body.addEventListener('drop', e => { const d = e.target.closest && e.target.closest('.cvm-drop'); if (d) d.classList.remove('over'); });
  }

  function openModal() {
    ensureModal();
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function isOpen() { return !!overlay && overlay.classList.contains('open'); }

  function close() {
    if (!overlay) return;
    cancelRequest();
    clearStages();
    overlay.classList.remove('open');
    // The job panel may be open underneath, and it keeps the page from scrolling too
    if (!document.getElementById('detailPanel').classList.contains('open')) document.body.style.overflow = '';
    input = freshInput();   // forget the CV text as soon as the modal is closed
    fileToken = null;
    step = '';
  }

  function clearStages() {
    stageTimers.forEach(clearTimeout);
    stageTimers = [];
  }

  function show(name) {
    clearStages();
    step = name;
    body.innerHTML = VIEWS[name]();
    overlay.querySelector('.cvm-modal').scrollTop = 0;
    if (name === 'input') updateAnalyse();
    if (name === 'review') syncOptIn();
    const first = body.querySelector('[data-autofocus]') || body.querySelector('h2');
    if (first) {
      if (first.tagName === 'H2') first.setAttribute('tabindex', '-1');
      first.focus({ preventScroll: true });
    }
  }

  function showWorking(title, stages) {
    workingTitle = title;
    show('working');
    const el = document.getElementById('cvmStage');
    stages.forEach(([ms, text]) => stageTimers.push(setTimeout(() => { if (el.isConnected) el.textContent = text; }, ms)));
  }

  const PROFILE_STAGES = [
    [0, 'Reading your CV…'],
    [2500, 'Understanding your experience…'],
    [9000, 'Picking out your fields, skills and seniority…'],
    [25000, 'Nearly there…'],
    [60000, 'Still working. Thanks for waiting…'],
  ];
  const URL_STAGES = [
    [0, 'Opening your web page…'],
    [8000, 'Reading about your work…'],
    [20000, 'Understanding your experience…'],
    [45000, 'Nearly there…'],
    [80000, 'Still working. Thanks for waiting…'],
  ];
  function matchStages() {
    return [
      [0, `Comparing your profile with ${openCountText()} open positions…`],
      [4000, 'Shortlisting the closest 40…'],
      [9000, 'Checking each one against your experience…'],
      [25000, 'Writing a reason for each match…'],
      [55000, 'Still working. Thanks for waiting…'],
    ];
  }

  // ── Views ───────────────────────────────────────────────────────────────────────
  function privacyHtml() {
    return `<details class="cvm-preview"><summary>How we handle your CV</summary><div class="cvm-privacy">
      <p>Your file is read in your browser. Email addresses, phone numbers, ID numbers and details such as date of birth are removed before anything is sent.</p>
      <p style="margin-top:6px">The rest of the text, or the web page you link, is analysed by Claude, an AI model from Anthropic, to describe your experience and compare it with open positions.</p>
      <p style="margin-top:6px">We don't store your CV or its text. Your latest matches stay in this browser until you sign out. Your profile is saved only if you choose to save it. <a href="#" data-act="privacy">Privacy notice</a></p>
    </div></details>`;
  }

  const VIEWS = {
    intro() {
      return `<div class="cvm-icon" aria-hidden="true">✨</div>
        <h2 id="cvmTitle">Find jobs that fit your CV</h2>
        <p class="modal-sub">Add your CV and we'll compare it with all ${openCountText()} open positions at Hong Kong's universities and colleges, then show you the best fits and why they suit you.</p>
        <ol class="cvm-steps">
          <li><strong>Create a free account</strong><span>Just your email. We send a one-click sign-in link, no password.</span></li>
          <li><strong>Add your CV</strong><span>Upload a PDF or Word file, paste the text, or link your academic web page.</span></li>
          <li><strong>See the jobs that fit you</strong><span>Up to 12 open positions, each with a short reason, in about a minute.</span></li>
        </ol>
        <p class="cvm-privacy">🔒 Your CV is read in your browser, and contact details are removed before it's analysed by AI. We never store your CV. <a href="#" data-act="privacy">Privacy notice</a></p>
        <button type="button" class="auth-submit cvm-primary" data-act="signup" data-autofocus>Sign up free</button>
        <p class="auth-note">Already have an account? <a href="#" data-act="signin">Sign in</a></p>`;
    },

    input() {
      const t = input.tab;
      const tab = (id, label) => `<button type="button" role="tab" data-act="tab" data-tab="${id}" aria-selected="${t === id}">${label}</button>`;
      return `<h2 id="cvmTitle">Add your CV</h2>
        <p class="modal-sub">We'll build a short profile of your experience, check it with you, then compare it with ${openCountText()} open positions.</p>
        <div class="cvm-tabs" role="tablist">${tab('file', 'Upload CV')}${tab('paste', 'Paste text')}${tab('url', 'Web page')}</div>
        <div data-panel="file"${t === 'file' ? '' : ' hidden'}>
          <label class="cvm-drop"${input.file && input.file.status === 'ready' ? ' hidden' : ''}>
            <input type="file" id="cvmFile" accept="${ACCEPT}" aria-label="Choose your CV file">
            <span class="cvm-drop-icon" aria-hidden="true">📄</span>
            <span class="cvm-drop-main">Choose a file or drag it here</span>
            <span class="cvm-drop-sub">PDF, Word (.docx) or text · up to 5 MB</span>
          </label>
          <div id="cvmFileStatus">${fileStatusHtml()}</div>
        </div>
        <div data-panel="paste"${t === 'paste' ? '' : ' hidden'}>
          <textarea id="cvmPaste" class="cvm-textarea" placeholder="Paste the text of your CV here" aria-label="The text of your CV">${esc(input.paste)}</textarea>
          <div class="cvm-hint" id="cvmPasteHint">${pasteHint()}</div>
        </div>
        <div data-panel="url"${t === 'url' ? '' : ' hidden'}>
          <input id="cvmUrl" class="auth-input" type="url" inputmode="url" autocomplete="url" placeholder="https://www.example.edu.hk/people/your-name" value="${esc(input.url)}" aria-label="Web page address">
          <div class="cvm-hint">A public page about your work, such as your university profile or personal website.</div>
          <div id="cvmUrlHint">${urlHint()}</div>
        </div>
        <label class="cvm-consent"><input type="checkbox" id="cvmConsent"${consented() ? ' checked' : ''}>
          <span>I agree to my CV being analysed by AI (Anthropic's Claude) to find jobs that fit me. Contact details are removed first, and my CV isn't stored.</span></label>
        ${privacyHtml()}
        <div id="cvmInputError"></div>
        <button type="button" class="auth-submit cvm-primary" id="cvmAnalyse" data-act="analyse" disabled>Analyse my CV</button>
        <p class="auth-note">You can analyse up to 3 CVs a day.</p>`;
    },

    working() {
      return `<h2 id="cvmTitle">${esc(workingTitle)}</h2>
        <div class="cvm-progress" aria-hidden="true"><div class="cvm-progress-bar"></div></div>
        <p class="cvm-stage" id="cvmStage" role="status" aria-live="polite"></p>
        <p class="auth-note" style="text-align:left">This usually takes under a minute. Please keep this window open.</p>`;
    },

    loading() {
      return `<h2 id="cvmTitle">My CV profile</h2>
        <div class="cvm-progress" aria-hidden="true"><div class="cvm-progress-bar"></div></div>
        <p class="cvm-stage" role="status">Loading…</p>`;
    },

    review() {
      const p = draft.profile;
      const fromCv = draft.from === 'cv';
      const meta = [
        STAGE_LABEL[p.career_stage],
        DEGREE_LABEL[p.highest_degree],
        p.years_experience ? `${p.years_experience} year${p.years_experience === 1 ? '' : 's'} of experience` : '',
      ].filter(Boolean).join(' · ');
      const roles = ['academic', 'non_academic', 'both'].map(r =>
        `<button type="button" role="radio" data-act="role" data-role="${r}" aria-checked="${p.role_type === r}">${ROLE_LABEL[r]}</button>`).join('');
      const ranks = RANK_OPTIONS.map(r =>
        `<button type="button" class="cvm-chip" data-act="rank" data-rank="${esc(r)}" aria-pressed="${p.suitable_ranks.includes(r)}">${esc(r)}</button>`).join('');
      const unis = UNI_ORDER.map(u =>
        `<button type="button" class="cvm-chip" data-act="uni" data-uni="${esc(u)}" aria-pressed="${draft.prefs.unis.includes(u)}">${esc(uniDisplay(u))}</button>`).join('');
      return `<h2 id="cvmTitle">${fromCv ? 'Your profile' : 'Edit your profile'}</h2>
        <p class="modal-sub">${fromCv
          ? "Here's what we understood from your CV. Change anything that's off, then find your matches."
          : 'Change what we match on, then run the match again.'}</p>
        ${p.looks_like_cv ? '' : `<div class="cvm-notice" style="margin:0 0 14px"><strong>This doesn't look like a CV.</strong> Your matches may not be useful. <button type="button" class="cvm-link" data-act="back">Try another file</button></div>`}
        <div class="cvm-card">
          <div class="cvm-headline">${esc(p.headline || 'Your profile')}</div>
          ${p.summary ? `<p class="cvm-summary">${esc(p.summary)}</p>` : ''}
          ${meta ? `<div class="cvm-meta">${esc(meta)}</div>` : ''}
        </div>
        <div class="cvm-field"><div class="cvm-label">Looking for</div><div class="cvm-seg" role="radiogroup" aria-label="Looking for">${roles}</div></div>
        <div class="cvm-field"><div class="cvm-label">Ranks that suit you</div><div class="cvm-chips">${ranks}</div></div>
        <div class="cvm-field"><div class="cvm-label">Your fields and specialisms</div>
          <div class="cvm-chips" id="cvmTopics">${topicsHtml()}</div>
          <input class="cvm-add" id="cvmAddTopic" maxlength="60" placeholder="Add a field or specialism, then press Enter" aria-label="Add a field or specialism">
        </div>
        <div class="cvm-field"><div class="cvm-label">Institutions <span>· optional, leave all off to search everywhere</span></div><div class="cvm-chips">${unis}</div></div>
        <label class="cvm-consent cvm-optin"><input type="checkbox" id="cvmOptIn"><span id="cvmOptInText">${optInText()}</span></label>
        <div id="cvmReviewError"></div>
        <div class="cvm-actions">
          <button type="button" class="cvm-secondary" data-act="${fromCv ? 'back' : 'close'}">${fromCv ? 'Back' : 'Cancel'}</button>
          <button type="button" class="auth-submit cvm-primary" data-act="match">Find my matches</button>
        </div>`;
    },

    manage() {
      const s = saved;
      if (!s) {
        const last = results
          ? `<div class="cvm-card"><div class="cvm-headline">${esc(results.profile.headline || 'Your profile')}</div><div class="cvm-meta">From your match on ${esc(fmtDate(results.at))}</div></div>
            <button type="button" class="auth-submit cvm-primary" data-act="save-last">Save this profile and email me new jobs</button>
            <p class="cvm-footer-links"><button type="button" class="cvm-link" data-act="new">Use a new CV instead</button></p>`
          : '<button type="button" class="auth-submit cvm-primary" data-act="new">Match my CV</button>';
        return `<h2 id="cvmTitle">My CV profile</h2>
          <p class="modal-sub">Save your profile to get an email when a new job fits you. We keep the profile, never your CV.</p>${last}`;
      }
      const p = s.profile || {};
      return `<h2 id="cvmTitle">My CV profile</h2>
        <p class="modal-sub">Saved ${esc(fmtDate(s.updated_at))}. We use it to email you new jobs that fit.</p>
        <div class="cvm-card"><div class="cvm-headline">${esc(p.headline || 'Your profile')}</div>${p.summary ? `<p class="cvm-summary">${esc(p.summary)}</p>` : ''}</div>
        <label class="cvm-switch"><input type="checkbox" id="cvmAlerts" role="switch"${s.alerts_enabled ? ' checked' : ''}>
          <span>Email me new jobs that fit this profile<small>At most one of these emails a day, only when a new job fits.</small></span></label>
        <div class="cvm-actions">
          <button type="button" class="cvm-secondary" data-act="new">Update from a new CV</button>
          <button type="button" class="auth-submit cvm-primary" data-act="rematch">Find matches now</button>
        </div>
        <p class="cvm-footer-links"><button type="button" class="cvm-link danger" data-act="delete">Delete my saved profile</button></p>
        <div id="cvmConfirm"></div>`;
    },

    error() {
      const e = errorState || {};
      const limit = ['daily_limit', 'budget_reached', 'paused'].includes(e.code);
      return `<div class="cvm-icon" aria-hidden="true">${limit ? '⏳' : '⚠️'}</div>
        <h2 id="cvmTitle">${esc(ERROR_TITLE[e.code] || 'Something went wrong')}</h2>
        <p class="modal-sub">${esc(e.message || ERROR_TEXT[e.code] || 'Please try again in a minute.')}</p>
        <div class="cvm-actions">
          <button type="button" class="cvm-secondary" data-act="close">Close</button>
          ${limit ? '' : '<button type="button" class="auth-submit cvm-primary" data-act="retry" data-autofocus>Try again</button>'}
        </div>`;
    },
  };

  function fileStatusHtml() {
    const f = input.file;
    if (!f) return '';
    if (f.status === 'reading') {
      return `<div class="cvm-file reading" role="status"><span class="cvm-spin" aria-hidden="true"></span><span>Reading <span class="cvm-file-name">${esc(f.name)}</span>…</span></div>`;
    }
    if (f.status === 'error') return `<div class="cvm-error" role="alert">${esc(f.error)}</div>`;
    const facts = [
      f.pages ? `${f.pages} page${f.pages === 1 ? '' : 's'}` : '',
      `${f.text.length.toLocaleString('en')} characters`,
      f.removed ? `${f.removed} contact detail${f.removed === 1 ? '' : 's'} removed` : '',
    ].filter(Boolean).join(' · ');
    const preview = f.text.length > 6000 ? f.text.slice(0, 6000) + '\n…' : f.text;
    return `<div class="cvm-file"><span aria-hidden="true">✓</span><span><span class="cvm-file-name">${esc(f.name)}</span><br><small>${esc(facts)}</small></span>
        <button type="button" class="cvm-link" data-act="clear-file">Change</button></div>
      ${f.cut ? `<div class="cvm-notice">Your CV is long, so we'll use its first ${TEXT_MAX.toLocaleString('en')} characters.</div>` : ''}
      ${f.skipped ? `<div class="cvm-notice">We'll use the first ${MAX_PDF_PAGES} pages.</div>` : ''}
      <details class="cvm-preview"><summary>Check the text we'll send</summary><pre>${esc(preview)}</pre></details>`;
  }

  function pasteHint() {
    const n = input.paste.trim().length;
    if (!n) return 'Emails and phone numbers are removed before your text is sent.';
    if (n < TEXT_MIN) return `${n.toLocaleString('en')} characters. Please paste your whole CV (at least ${TEXT_MIN}).`;
    if (n > TEXT_MAX) return `${n.toLocaleString('en')} characters. That's long, so we'll use the first ${TEXT_MAX.toLocaleString('en')}.`;
    return `${n.toLocaleString('en')} characters. Emails and phone numbers are removed before your text is sent.`;
  }

  function urlHint() {
    const checked = checkUrl(input.url);
    return checked.error ? `<div class="cvm-error">${esc(checked.error)}</div>` : '';
  }

  function topicList(p) {
    const seen = new Set();
    return [...p.disciplines, ...p.specialisms].filter(t => {
      const k = t.toLowerCase();
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }

  function topicsHtml() {
    const topics = topicList(draft.profile);
    if (!topics.length) return '<span class="cvm-hint" style="margin:0">None yet. Add at least one below.</span>';
    return topics.map(t => `<span class="cvm-chip topic">${esc(t)}<button type="button" data-act="topic-remove" data-topic="${esc(t)}" aria-label="Remove ${esc(t)}">×</button></span>`).join('');
  }

  function optInText() {
    if (saved) {
      return `<strong>Update my saved profile</strong><br><small>Your match alert emails use this profile${saved.alerts_enabled ? '' : ' (they are switched off)'}.</small>`;
    }
    return '<strong>Save my profile and email me new jobs that fit it</strong><br><small>We keep this profile (never your CV) with your email address. Switch the emails off or delete the profile any time.</small>';
  }

  /** The opt-in reflects whether a profile is already saved, once we know */
  function syncOptIn() {
    optInTouched = false;
    loadSaved().catch(() => null).then(() => {
      if (step !== 'review') return;
      const box = document.getElementById('cvmOptIn');
      const text = document.getElementById('cvmOptInText');
      if (text) text.innerHTML = optInText();
      if (box && !optInTouched) box.checked = !!saved;
    });
  }

  // ── Updating parts of the input view in place ──────────────────────────────────────
  function readyToAnalyse() {
    const consent = document.getElementById('cvmConsent');
    if (!consent || !consent.checked) return false;
    if (input.tab === 'file') return !!(input.file && input.file.status === 'ready');
    if (input.tab === 'paste') return input.paste.trim().length >= TEXT_MIN;
    return !!checkUrl(input.url).url;
  }
  function updateAnalyse() {
    const btn = document.getElementById('cvmAnalyse');
    if (btn) btn.disabled = !readyToAnalyse() || !!request;
  }
  function renderFileStatus() {
    const el = document.getElementById('cvmFileStatus');
    if (el) el.innerHTML = fileStatusHtml();
    const drop = body && body.querySelector('.cvm-drop');
    if (drop) drop.hidden = !!(input.file && input.file.status === 'ready');
    updateAnalyse();
  }
  function showInlineError(id, message) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = message ? `<div class="cvm-error" role="alert">${esc(message)}</div>` : '';
  }

  // ── Events ───────────────────────────────────────────────────────────────────────
  function onClick(e) {
    const el = e.target.closest('[data-act]');
    if (!el || !body.contains(el)) return;
    e.preventDefault();
    const act = ACTIONS[el.dataset.act];
    if (act) act(el);
  }

  function onInput(e) {
    if (e.target.id === 'cvmPaste') {
      input.paste = e.target.value;
      document.getElementById('cvmPasteHint').textContent = pasteHint();
      updateAnalyse();
    } else if (e.target.id === 'cvmUrl') {
      input.url = e.target.value;
      document.getElementById('cvmUrlHint').innerHTML = urlHint();
      updateAnalyse();
    }
  }

  function onChange(e) {
    const t = e.target;
    if (t.id === 'cvmFile' && t.files && t.files[0]) {
      readChosenFile(t.files[0]);
      t.value = '';   // choosing the same file again still works
    } else if (t.id === 'cvmConsent') {
      updateAnalyse();
    } else if (t.id === 'cvmOptIn') {
      optInTouched = true;
    } else if (t.id === 'cvmAlerts') {
      toggleAlerts(t);
    }
  }

  function onKeydown(e) {
    if (e.target.id === 'cvmAddTopic' && e.key === 'Enter') {
      e.preventDefault();
      addTopic(e.target.value);
      e.target.value = '';
    } else if (e.target.id === 'cvmUrl' && e.key === 'Enter') {
      e.preventDefault();
      analyse();
    }
  }

  function addTopic(raw) {
    const t = String(raw || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    if (!t) return;
    const p = draft.profile;
    const has = list => list.some(x => x.toLowerCase() === t.toLowerCase());
    // New topics go first: the function keeps the first 15 specialisms and 50 search terms
    if (!has(p.specialisms) && !has(p.disciplines)) p.specialisms.unshift(t);
    if (!has(p.search_terms)) p.search_terms.unshift(t);
    document.getElementById('cvmTopics').innerHTML = topicsHtml();
    showInlineError('cvmReviewError', '');
  }

  function removeTopic(t) {
    const k = t.toLowerCase();
    const p = draft.profile;
    for (const key of ['disciplines', 'specialisms', 'skills', 'search_terms']) {
      p[key] = p[key].filter(x => x.toLowerCase() !== k);
    }
    document.getElementById('cvmTopics').innerHTML = topicsHtml();
  }

  function toggleIn(list, value) {
    const i = list.indexOf(value);
    if (i >= 0) list.splice(i, 1); else list.push(value);
    return i < 0;
  }

  const ACTIONS = {
    signup: () => startSignIn('signup'),
    signin: () => startSignIn('signin'),
    privacy: () => {
      const about = document.getElementById('aboutOverlay');
      if (about) about.style.zIndex = '600';   // above this modal
      openAbout('privacy');
    },
    close: () => close(),
    tab: el => {
      input.tab = el.dataset.tab;
      body.querySelectorAll('[role="tab"]').forEach(b => b.setAttribute('aria-selected', String(b === el)));
      body.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== input.tab; });
      showInlineError('cvmInputError', '');
      updateAnalyse();
      const field = { paste: 'cvmPaste', url: 'cvmUrl' }[input.tab];
      if (field) document.getElementById(field).focus();
    },
    'clear-file': () => {
      input.file = null;
      fileToken = null;
      renderFileStatus();
      document.getElementById('cvmFile').click();   // straight to choosing another file
    },
    analyse: () => analyse(),
    back: () => show('input'),
    role: el => {
      draft.profile.role_type = el.dataset.role;
      body.querySelectorAll('[data-act="role"]').forEach(b => b.setAttribute('aria-checked', String(b === el)));
    },
    rank: el => el.setAttribute('aria-pressed', String(toggleIn(draft.profile.suitable_ranks, el.dataset.rank))),
    uni: el => el.setAttribute('aria-pressed', String(toggleIn(draft.prefs.unis, el.dataset.uni))),
    'topic-remove': el => removeTopic(el.dataset.topic),
    match: () => matchFromReview(),
    new: () => {
      input = freshInput();
      show('input');
    },
    rematch: () => {
      if (!saved) return;
      runMatch(clone(saved.profile), { unis: (saved.prefs && saved.prefs.unis) || [] }, { where: 'profile' });
    },
    'save-last': async el => {
      if (!results) return;
      el.disabled = true;
      try {
        await saveProfile(results.profile, results.prefs, true);
        trackEvent('cv_match_alert_on', { where: 'profile' });
        showActionToast('Profile saved · alerts on');
        show('manage');
        renderHead();
      } catch (err) {
        console.error('[cv-match] save profile:', err);
        showActionToast("Couldn't save your profile");
        el.disabled = false;
      }
    },
    delete: () => {
      document.getElementById('cvmConfirm').innerHTML = `<div class="cvm-confirm" role="alert">Delete your saved profile? The match alert emails will stop. Your latest matches stay in this browser.
        <div class="cvm-actions"><button type="button" class="cvm-secondary" data-act="cancel-delete">Cancel</button><button type="button" class="cvm-danger" data-act="confirm-delete">Delete</button></div></div>`;
    },
    'cancel-delete': () => { document.getElementById('cvmConfirm').innerHTML = ''; },
    'confirm-delete': async el => {
      el.disabled = true;
      try {
        await deleteSaved();
        trackEvent('cv_match_profile_deleted');
        showActionToast('Saved profile deleted');
        show('manage');
        renderHead();
      } catch (err) {
        console.error('[cv-match] delete profile:', err);
        showActionToast("Couldn't delete your profile");
        el.disabled = false;
      }
    },
    retry: () => {
      if (errorState && errorState.stage === 'match' && lastMatch) runMatch(lastMatch.profile, lastMatch.prefs, lastMatch.opts);
      else if (errorState && errorState.stage === 'profile') { show('input'); analyse(); }
      else if (errorState && errorState.stage === 'manage') showManage();
      else show(_currentUser ? 'input' : 'intro');
    },
  };

  function startSignIn(which) {
    close();
    trackEvent('cv_match_signin_prompt', { action: which });
    openAuthModal('cv_match', which);
  }

  async function toggleAlerts(box) {
    const on = box.checked;
    box.disabled = true;
    try {
      await setAlerts(on);
      trackEvent(on ? 'cv_match_alert_on' : 'cv_match_alert_off', { where: 'profile' });
      showActionToast(on ? 'Match alerts on' : 'Match alerts off');
      renderHead();
    } catch (err) {
      console.error('[cv-match] alerts:', err);
      box.checked = !on;
      showActionToast("Couldn't update alerts");
    }
    box.disabled = false;
  }

  // ── The two steps: profile, then matches ─────────────────────────────────────────
  async function analyse() {
    if (step !== 'input' || request || !readyToAnalyse()) return;
    writeJson(CONSENT_KEY, 1);
    let payload;
    let kind = input.tab;
    if (input.tab === 'file') {
      payload = { action: 'profile', text: input.file.text };
      kind = input.file.kind;
    } else if (input.tab === 'paste') {
      const prepared = prepareText(input.paste);
      if (prepared.text.length < TEXT_MIN) {
        showInlineError('cvmInputError', "That's too short for a CV. Please paste your whole CV.");
        return;
      }
      payload = { action: 'profile', text: prepared.text };
    } else {
      payload = { action: 'profile', url: checkUrl(input.url).url };
    }
    trackEvent('cv_match_submit', { input: kind });
    showWorking('Analysing your CV', kind === 'url' ? URL_STAGES : PROFILE_STAGES);
    let data;
    try {
      data = await callApi(payload);
    } catch (err) {
      failed(err, 'profile');
      return;
    }
    const profile = data.profile;
    draft = { profile: clone(profile), prefs: { unis: [] }, from: 'cv' };
    trackEvent('cv_match_profile', { input: kind, career_stage: profile.career_stage, role_type: profile.role_type, looks_like_cv: !!profile.looks_like_cv });
    show('review');
  }

  function matchFromReview() {
    if (!hasTopics(draft.profile)) {
      showInlineError('cvmReviewError', 'Add at least one field or specialism, so we know what to look for.');
      return;
    }
    const box = document.getElementById('cvmOptIn');
    runMatch(clone(draft.profile), clone(draft.prefs), { optIn: !!(box && box.checked), where: draft.from === 'cv' ? 'review' : 'edit' });
  }

  async function runMatch(profile, prefs, opts) {
    lastMatch = { profile, prefs, opts };
    if (!isOpen()) openModal();
    showWorking('Finding your matches', matchStages());
    let data;
    try {
      data = await callApi({ action: 'match', profile, prefs: { unis: prefs.unis || [] } });
    } catch (err) {
      failed(err, 'match');
      return;
    }
    setResults({
      v: 1,
      user: _currentUser ? _currentUser.id : null,
      at: new Date().toISOString(),
      profile,
      prefs: { unis: prefs.unis || [] },
      matches: Array.isArray(data.matches) ? data.matches : [],
      advice: data.advice || '',
      open_jobs: data.open_jobs || 0,
      considered: data.considered || 0,
      updated: data.updated || '',
    });
    trackEvent('cv_match_results', { count: results.matches.length, top_score: results.matches.length ? results.matches[0].score : 0, where: opts.where });
    if (opts.optIn) {
      const had = saved;
      try {
        await saveProfile(profile, prefs, had ? had.alerts_enabled : true);
        if (!had) trackEvent('cv_match_alert_on', { where: opts.where });
        showActionToast(had ? 'Saved profile updated' : 'Profile saved · alerts on');
      } catch (err) {
        console.error('[cv-match] save profile:', err);
        showActionToast("Couldn't save your profile");
      }
    }
    close();
    openView();
  }

  function failed(err, stage) {
    clearStages();
    const code = (err && err.code) || 'internal';
    if (code === 'cancelled') return;
    if (!(err instanceof CvmError)) console.error('[cv-match]', err);
    trackEvent('cv_match_error', { code, stage });
    if (code === 'sign_in_required') {
      close();
      showActionToast('Please sign in again');
      openAuthModal('cv_match');
      return;
    }
    if (stage === 'profile' && INPUT_ERRORS.has(code)) {
      show('input');
      showInlineError('cvmInputError', err.message || "We couldn't use that. Please try another way of adding your CV.");
      return;
    }
    if (stage === 'match' && code === 'profile_invalid' && draft) {
      show('review');
      showInlineError('cvmReviewError', err.message);
      return;
    }
    errorState = { code, stage, message: err.message };
    show('error');
  }

  // ── "Jobs that fit you" view ─────────────────────────────────────────────────────
  function openView(replace) {
    if (!results) return;
    if (currentView !== 'matches') {
      switchTab('matches', { replace: !!replace });
    } else {
      filterJobs();
      onViewChange();
    }
    if (!replace) {
      const head = document.getElementById('cvmHead');
      if (head) window.scrollTo({ top: Math.max(0, head.getBoundingClientRect().top + window.scrollY - 80), behavior: 'smooth' });
    }
  }

  function toggleView() {
    if (currentView === 'matches') switchTab('all'); else openView();
  }

  function onViewChange() {
    renderHead();
    syncEntryPoints();
  }

  function renderHead() {
    let el = document.getElementById('cvmHead');
    if (currentView !== 'matches' || !results) {
      if (el) el.remove();
      return;
    }
    if (!el) {
      el = document.createElement('div');
      el.id = 'cvmHead';
      el.className = 'cvm-results-head';
      el.addEventListener('click', onHeadClick);
      const tableWrap = document.getElementById('tableWrap');
      tableWrap.parentNode.insertBefore(el, tableWrap);
    }
    const r = results;
    const live = matchedJobs().length;
    const closed = r.matches.length - live;
    const days = Math.floor((Date.now() - Date.parse(r.at)) / 86400000);
    const meta = [
      `Matched ${fmtDate(r.at)}`,
      r.open_jobs ? `${r.open_jobs.toLocaleString('en')} open positions compared` : '',
      closed > 0 ? `${closed} no longer listed` : '',
    ].filter(Boolean).join(' · ');
    el.innerHTML = `<div class="cvm-results-main">
        <div class="cvm-results-title">Jobs that fit you <span class="ai-badge">AI suggestions</span></div>
        <div class="cvm-results-headline">${esc(r.profile.headline || '')}</div>
        <div class="cvm-results-meta">${esc(meta)}</div>
        ${r.advice && live ? `<div class="cvm-results-advice">💡 ${esc(r.advice)}</div>` : ''}
        ${days >= STALE_DAYS ? `<div class="cvm-stale">These matches are ${days} days old, and new jobs have been posted since. <button type="button" class="cvm-link" data-act="rerun">Match again</button></div>` : ''}
        <div class="cvm-results-note">Suggested by AI (Claude) from your CV profile. Always check the full advertisement.</div>
      </div>
      <div class="cvm-results-actions">
        <button type="button" class="cvm-btn" data-act="all">← All jobs</button>
        <button type="button" class="cvm-btn" data-act="edit">✎ Edit profile</button>
        <button type="button" class="cvm-btn" data-act="new">↻ New CV</button>
        <span id="cvmAlertSlot"></span>
      </div>`;
    renderAlertButton();
  }

  /** "Email me new jobs like these", or the state of the user's match alerts */
  function renderAlertButton() {
    const paint = () => {
      const slot = document.getElementById('cvmAlertSlot');
      if (!slot) return;
      if (!_currentUser) { slot.innerHTML = ''; return; }
      if (saved && saved.alerts_enabled) {
        slot.innerHTML = '<button type="button" class="cvm-btn on" data-act="manage">✓ Match alerts on</button>';
      } else if (saved) {
        slot.innerHTML = '<button type="button" class="cvm-btn" data-act="manage">🔔 Match alerts off</button>';
      } else {
        slot.innerHTML = '<button type="button" class="cvm-btn primary" data-act="alerts">🔔 Email me new jobs like these</button>';
      }
    };
    paint();
    if (saved === undefined && _currentUser) loadSaved().then(paint, () => {});
  }

  async function onHeadClick(e) {
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    if (act === 'all') {
      switchTab('all');
    } else if (act === 'edit' && results) {
      draft = { profile: clone(results.profile), prefs: clone(results.prefs || { unis: [] }), from: 'results' };
      openModal();
      show('review');
    } else if (act === 'new') {
      input = freshInput();
      openModal();
      show(_currentUser ? 'input' : 'intro');
    } else if (act === 'rerun' && results) {
      runMatch(clone(results.profile), clone(results.prefs || { unis: [] }), { where: 'rerun' });
    } else if (act === 'manage') {
      showManage();
    } else if (act === 'alerts' && results) {
      if (!_currentUser) { openAuthModal('cv_match'); return; }
      el.disabled = true;
      try {
        await saveProfile(results.profile, results.prefs, true);
        trackEvent('cv_match_alert_on', { where: 'results' });
        showActionToast('Match alerts on');
      } catch (err) {
        console.error('[cv-match] save profile:', err);
        showActionToast("Couldn't turn on alerts");
      }
      renderAlertButton();
    }
  }

  async function showManage() {
    openModal();
    show('loading');
    try {
      await loadSaved(true);
    } catch (err) {
      console.error('[cv-match] load profile:', err);
      errorState = { code: 'load', stage: 'manage', message: "We couldn't load your saved profile. Please try again." };
      show('error');
      return;
    }
    if (step === 'loading') show('manage');
  }

  /** Nav button and hero call to action */
  function syncEntryPoints() {
    const n = results ? matchedJobs().length : 0;
    document.body.classList.toggle('cvm-has-results', !!results);
    const nav = document.getElementById('cvmNavBtn');
    if (nav) {
      nav.style.display = results ? '' : 'none';
      nav.classList.toggle('active', currentView === 'matches');
      const count = document.getElementById('cvmNavCount');
      if (count) count.textContent = n;
    }
    const cta = document.getElementById('cvmCtaBtn');
    if (cta) cta.innerHTML = results ? `✨ See the jobs that fit you <span class="cvm-cta-count">${n}</span>` : '✨ Find jobs that fit your CV';
  }

  // ── Hooks used by index.html ─────────────────────────────────────────────────────
  function rowHtml(id, inMatchesView) {
    const m = matchFor(id);
    if (!m || !inMatchesView) return '';
    return `<div class="cvm-why-line">${esc(m.why)}</div>`;
  }

  function pillHtml(id) {
    const m = matchFor(id);
    return m ? `<span class="cvm-pill ${esc(m.fit)}" title="Fits your CV profile">${esc(FIT_LABEL[m.fit] || 'Match')}</span>` : '';
  }

  function panelHtml(id) {
    const m = matchFor(id);
    if (!m) return '';
    const gaps = (m.gaps || []).filter(Boolean);
    return `<div class="psection cvm-why" id="cvmWhy">
      <div class="psection-title">Why this may suit you <span class="ai-badge">AI suggestion</span></div>
      <p>${pillHtml(id)}${esc(m.why)}</p>
      ${gaps.length ? `<p class="cvm-gaps"><strong>Worth checking:</strong> ${gaps.map(esc).join('; ')}</p>` : ''}
      <p class="cvm-note">From your CV profile, matched ${esc(fmtDate(results.at))}. Always check the full advertisement.</p>
    </div>`;
  }

  /** A panel opened before this script loaded gets its section now */
  function refreshPanel() {
    if (!openJobId || document.getElementById('cvmWhy')) return;
    const html = panelHtml(openJobId);
    const panel = document.getElementById('panelBody');
    const about = panel && panel.querySelectorAll('.psection')[1];
    if (html && about) about.insertAdjacentHTML('beforebegin', html);
  }

  function renderEmpty(el) {
    el.innerHTML = `<div class="cvm-empty"><div class="empty-icon">🧭</div>
      <p style="font-size:1rem;font-weight:600;color:var(--ink)">No close matches right now</p>
      <p>${esc((results && results.advice) || "None of today's open positions fits your profile closely. New jobs are added every day.")}</p>
      <div class="cvm-results-actions">
        <button type="button" class="cvm-btn" data-act="edit">✎ Edit profile</button>
        ${saved && saved.alerts_enabled ? '' : '<button type="button" class="cvm-btn primary" data-act="alerts">🔔 Email me when one appears</button>'}
      </div></div>`;
    el.onclick = onHeadClick;
  }

  /** Whose results are shown: only the signed-in user's own */
  function applyUser(user) {
    const id = user ? user.id : null;
    if (id === userId) return;
    userId = id;
    saved = undefined;
    if (results && results.user !== id) {
      setResults(null);
      if (currentView === 'matches') switchTab('all');
      else if (ALL_JOBS.length) renderTable();
    }
    syncEntryPoints();
    if (currentView === 'matches') renderHead();
  }

  async function init(opts) {
    try {
      const { data } = await _sb.auth.getSession();
      applyUser(data.session ? data.session.user : null);
    } catch (e) { /* leave as is */ }
    syncEntryPoints();
    if (opts && opts.showView && results && currentView !== 'matches') openView(true);
    else if (ALL_JOBS.length && results) renderTable();   // fit labels on the listing
    refreshPanel();
  }

  /** Entry points: 'hero', 'empty', 'menu', 'nav', 'resume' (after signing in) */
  function open(where) {
    if (where === 'nav') { toggleView(); return; }
    if (!_currentUser) {
      openModal();
      show('intro');
      trackEvent('cv_match_intro', { where });
      return;
    }
    if (where === 'menu') { showManage(); return; }
    if (results && (where === 'hero' || where === 'empty')) { openView(); return; }
    input = freshInput();
    openModal();
    show('input');
  }

  function reset() {
    close();
    setResults(null);
    saved = undefined;
    userId = null;
    const head = document.getElementById('cvmHead');
    if (head) head.remove();
    syncEntryPoints();
  }

  window.CvMatch = {
    init,
    open,
    reset,
    onAuthChange: applyUser,
    onViewChange,
    hasResults: () => !!results,
    matchedJobs,
    rowHtml,
    pillHtml,
    panelHtml,
    renderEmpty,
  };
})();
