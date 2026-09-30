// Records the CV matching demo video. See README.md in this folder.
//   node demo/cv-match/record.js [--shots]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const api = require('./api');

const DIR = __dirname;
const REPO = path.resolve(__dirname, '../..');
const OUT = path.join(DIR, 'out');
const SITE = 'http://localhost:8000/';
const W = 1280, H = 720;
const SHOTS = process.argv.includes('--shots');

// Captions, a visible cursor and title cards, added to every page
const OVERLAY = `
(() => {
  const css = \`
    #demoCursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; pointer-events: none;
      left: 0; top: 0; transform: translate(-3px,-2px); transition: none; }
    #demoCursor svg { filter: drop-shadow(0 1px 2px rgba(0,0,0,.35)); }
    .demoRipple { position: fixed; z-index: 2147483646; width: 34px; height: 34px; margin: -17px 0 0 -17px;
      border-radius: 50%; background: rgba(124,58,237,.35); pointer-events: none; animation: demoR .5s ease-out forwards; }
    @keyframes demoR { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.4); opacity: 0 } }
    #demoCap { position: fixed; z-index: 2147483645; left: 50%; bottom: 26px; transform: translateX(-50%) translateY(12px);
      max-width: 900px; padding: 12px 22px; border-radius: 12px; background: rgba(20,22,34,.9); color: #fff;
      font: 500 19px/1.35 'DM Sans', system-ui, sans-serif; text-align: center; opacity: 0;
      transition: opacity .35s, transform .35s; pointer-events: none; box-shadow: 0 8px 30px rgba(0,0,0,.25); }
    #demoCap.on { opacity: 1; transform: translateX(-50%) translateY(0); }
    #demoCap b { color: #c4b5fd; font-weight: 600; }
    #demoCard { position: fixed; inset: 0; z-index: 2147483640; display: flex; flex-direction: column; align-items: center;
      justify-content: center; background: linear-gradient(135deg,#2b3240 0%,#3b2a63 100%); color: #fff; text-align: center;
      font-family: 'DM Sans', system-ui, sans-serif; opacity: 0; transition: opacity .6s; pointer-events: none; }
    #demoCard.on { opacity: 1; }
    #demoCard .k { font-size: 20px; letter-spacing: .12em; text-transform: uppercase; color: #c4b5fd; margin-bottom: 18px; }
    #demoCard h1 { font: 700 54px/1.15 'Playfair Display', Georgia, serif; margin: 0 0 18px; }
    #demoCard p { font-size: 22px; color: #dcdcf0; margin: 0; max-width: 860px; line-height: 1.45; }
    #demoCard .s { margin-top: 34px; font-size: 16px; color: #a9a9c8; }\`;
  const add = () => {
    if (document.getElementById('demoCursor')) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const c = document.createElement('div'); c.id = 'demoCursor';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l14 8.2-6.3 1.5L7.4 18z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const cap = document.createElement('div'); cap.id = 'demoCap'; document.body.appendChild(cap);
    const card = document.createElement('div'); card.id = 'demoCard'; document.body.appendChild(card);
    const pos = window.__demoPos || [W / 2, H / 2];
    c.style.left = pos[0] + 'px'; c.style.top = pos[1] + 'px';
  };
  const W = ${W}, H = ${H};
  document.addEventListener('mousemove', e => {
    const c = document.getElementById('demoCursor');
    window.__demoPos = [e.clientX, e.clientY];
    if (c) { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }
  }, true);
  document.addEventListener('mousedown', e => {
    const r = document.createElement('div'); r.className = 'demoRipple';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.body.appendChild(r); setTimeout(() => r.remove(), 600);
  }, true);
  window.__cap = html => {
    const el = document.getElementById('demoCap');
    if (!el) return;
    if (!html) { el.classList.remove('on'); return; }
    el.innerHTML = html; el.classList.add('on');
  };
  window.__card = html => {
    const el = document.getElementById('demoCard');
    if (!el) return;
    const cur = document.getElementById('demoCursor');
    if (cur) cur.style.visibility = html ? 'hidden' : '';
    if (!html) { el.classList.remove('on'); return; }
    el.innerHTML = html; el.classList.add('on');
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
  // No feedback popup during the demo
  try { localStorage.setItem('hkaj_fbk', JSON.stringify({ snoozed: Date.now() })); } catch (e) {}
})();`;

(async () => {
  const browser = await chromium.launch();
  fs.mkdirSync(path.join(OUT, 'shots'), { recursive: true });
  {
    const p = await browser.newPage();
    await p.goto('file://' + path.join(DIR, 'cv.html'));
    await p.pdf({ path: path.join(OUT, 'Alex_Wong_CV.pdf'), format: 'A4' });
    await p.close();
  }
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 1,
    ...(SHOTS ? {} : { recordVideo: { dir: OUT, size: { width: W, height: H } } }),
  });
  await context.addInitScript(OVERLAY);

  // The page's own HTML, without the integrity check on the SDK (replaced by the stub below)
  await context.route(u => u.origin === 'http://localhost:8000' && (u.pathname === '/' || u.pathname === '/index.html'), async route => {
    const html = fs.readFileSync(path.join(REPO, 'index.html'), 'utf8')
      .replace(/(<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/@supabase[^"]+")\s+integrity="[^"]+"\s+crossorigin="anonymous"/, '$1');
    await route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
  });
  await context.route(/cdn\.jsdelivr\.net\/npm\/@supabase/, route =>
    route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(path.join(DIR, 'supabase-stub.js'), 'utf8') }));
  // No analytics hits from the recording
  await context.route(/googletagmanager|google-analytics/, route => route.abort());

  // Google Fonts from local copies, when out/fonts has them (for machines whose browser can't reach
  // Google Fonts; see README.md). Otherwise the page loads them as usual.
  if (fs.existsSync(path.join(OUT, 'fonts', 'css.css'))) {
    const crypto = require('crypto');
    await context.route(/fonts\.googleapis\.com\/css2/, route =>
      route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(OUT, 'fonts', 'css.css'), 'utf8') }));
    await context.route(/fonts\.gstatic\.com/, route => {
      const f = path.join(OUT, 'fonts', crypto.createHash('md5').update(route.request().url() + '\n').digest('hex').slice(0, 16) + '.woff2');
      return fs.existsSync(f) ? route.fulfill({ status: 200, contentType: 'font/woff2', body: fs.readFileSync(f), headers: { 'access-control-allow-origin': '*' } }) : route.abort();
    });
  }

  let page;
  const pause = ms => page.waitForTimeout(ms);

  await context.route(/\/functions\/v1\/match-jobs/, async route => {
    const req = JSON.parse(route.request().postData() || '{}');
    if (req.action === 'profile') {
      await pause(4200);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(api.profile) });
    }
    await pause(5200);
    const n = await page.evaluate(() => ALL_JOBS.length);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...api.match, open_jobs: n }) });
  });

  page = await context.newPage();
  const t0 = Date.now();
  const marks = {};
  const mark = name => { marks[name] = (Date.now() - t0) / 1000; };

  let shot = 0;
  const snap = async name => { if (SHOTS) await page.screenshot({ path: path.join(OUT, 'shots', `${String(++shot).padStart(2, '0')}-${name}.png`) }); };
  const cap = async (html, ms) => { await page.evaluate(h => window.__cap(h), html || ''); if (ms) await pause(ms); };
  const card = async (html, ms) => { await page.evaluate(h => window.__card(h), html || ''); if (ms) await pause(ms); };
  async function moveTo(target, opts = {}) {
    const loc = typeof target === 'string' ? page.locator(target).first() : target;
    await loc.scrollIntoViewIfNeeded();
    const b = await loc.boundingBox();
    const x = b.x + b.width * (opts.fx ?? 0.5), y = b.y + b.height * (opts.fy ?? 0.5);
    await page.mouse.move(x, y, { steps: opts.steps ?? 28 });
    await pause(opts.settle ?? 250);
    return loc;
  }
  async function click(target, opts = {}) {
    await moveTo(target, opts);
    await page.mouse.down(); await pause(90); await page.mouse.up();
    await pause(opts.after ?? 500);
  }
  async function scrollBy(sel, dy, ms = 700) {
    await page.evaluate(([s, d]) => {
      const el = s ? document.querySelector(s) : document.scrollingElement;
      el.scrollBy({ top: d, behavior: 'smooth' });
    }, [sel, dy]);
    await pause(ms);
  }

  // ── 1. Title card ──
  await page.goto(SITE + '?demo=1');
  await page.evaluate(() => { localStorage.removeItem('demo_signed_in'); localStorage.removeItem('hkaj_match'); localStorage.removeItem('hkaj_cvm_consent'); });
  await page.reload();
  await page.evaluate(() => { document.getElementById('demoCard').style.transition = 'none'; });
  await card(`<div class="k">New on HKAcadJobs</div><h1>✨ Find jobs that fit your CV</h1>
    <p>Add your CV. AI compares it with every open position at Hong Kong's universities and colleges, and shows you the best fits and why.</p>`);
  await page.evaluate(() => { document.getElementById('demoCard').style.transition = ''; });
  mark('start');
  await page.waitForFunction(() => typeof ALL_JOBS !== 'undefined' && ALL_JOBS.length > 1000, null, { timeout: 30000 });
  await page.mouse.move(W / 2, H * 0.62);
  await pause(3600);
  await snap('title');
  await card('', 800);

  // ── 2. Signed out: the call to action and intro ──
  await cap('Look for the violet <b>✨ Find jobs that fit your CV</b> button', 900);
  await moveTo('#cvmCtaBtn', { steps: 35 });
  await pause(900);
  await snap('home');
  await click('#cvmCtaBtn', { after: 900 });
  await cap('Three steps: a free account, your CV, then your matches', 2600);
  await snap('intro');
  await cap('Sign up with just your email. There is no password', 300);
  await click('[data-act="signup"]', { after: 700 });
  await moveTo('#authEmail', { steps: 18 });
  await page.locator('#authEmail').pressSequentially('alex.demo@example.com', { delay: 45 });
  await pause(400);
  await click('#authSubmitBtn', { after: 1500 });
  await snap('link-sent');
  await cap('The emailed link opens a new tab, signed in and ready for your CV', 2200);
  await cap('');

  // ── 3. Back from the magic link: straight to "Add your CV" ──
  mark('cutFrom');
  await page.evaluate(() => localStorage.setItem('demo_signed_in', '1'));
  await page.goto(SITE + '?link=1#access_token=demo&type=magiclink');
  await page.waitForSelector('#cvmOverlay.open', { timeout: 20000 });
  await page.waitForFunction(() => typeof ALL_JOBS !== 'undefined' && ALL_JOBS.length > 1000);
  await pause(300);
  mark('cutTo');
  await pause(300);
  await cap('Upload a PDF or Word file, paste the text, or link your academic web page', 900);
  await moveTo('.cvm-drop', { steps: 30 });
  await pause(500);
  await snap('add-cv');
  await page.locator('#cvmFile').setInputFiles(path.join(OUT, 'Alex_Wong_CV.pdf'));
  await page.waitForSelector('.cvm-file:not(.reading)', { timeout: 20000 });
  await pause(800);
  await cap('Your file is read <b>in your browser</b>. Emails, phone numbers and personal details are removed first', 1200);
  await click('.cvm-preview summary', { after: 700 });
  await scrollBy('.cvm-modal', 150, 900);
  await snap('redacted');
  await pause(2600);
  await click('.cvm-preview summary', { after: 400 });
  await cap('Agree to the AI analysis, then analyse', 200);
  await click('#cvmConsent', { after: 500 });
  await click('#cvmAnalyse', { after: 300 });
  await cap('Claude reads the CV and builds a short profile of your experience', 1500);
  await snap('analysing');
  await page.waitForSelector('.cvm-headline', { timeout: 20000 });
  await pause(500);

  // ── 4. Review the profile ──
  await cap('Check the profile: your level, the ranks that suit you, your fields', 1400);
  await moveTo('.cvm-headline', { steps: 25 });
  await pause(1600);
  await snap('profile');
  await scrollBy('.cvm-modal', 230, 900);
  await cap('Change anything that’s off, or add a field Claude missed', 500);
  await moveTo('#cvmAddTopic', { steps: 25 });
  await page.locator('#cvmAddTopic').click();
  await page.locator('#cvmAddTopic').pressSequentially('Multi-omics', { delay: 70 });
  await page.keyboard.press('Enter');
  await pause(1000);
  await snap('topic');
  await scrollBy('.cvm-modal', 400, 900);
  await cap('Optionally save the profile for daily emails about new jobs that fit', 500);
  await click('#cvmOptIn', { after: 1300 });
  await snap('optin');
  await cap('', 0);
  await click('[data-act="match"]', { after: 300 });
  await cap(`It compares your profile with all <b>${await page.evaluate(() => ALL_JOBS.length.toLocaleString('en'))}</b> open positions`, 1500);
  await snap('matching');
  await page.waitForSelector('#cvmHead', { timeout: 20000 });
  await cap('', 900);

  // ── 5. Results ──
  await page.evaluate(() => window.scrollTo({ top: Math.max(0, document.getElementById('cvmHead').getBoundingClientRect().top + scrollY - 70) }));
  await pause(500);
  await cap('<b>Jobs that fit you</b>: the best matches first, each with a fit label and a reason', 1200);
  await moveTo('#cvmHead .cvm-results-headline', { steps: 25 });
  await pause(1500);
  await snap('results');
  await scrollBy(null, 260, 900);
  await moveTo(page.locator('.cvm-why-line').nth(0), { steps: 25, fx: 0.3 });
  await pause(1700);
  await snap('results-list');
  await cap('Open a job to see why it may suit you, and what to check', 300);
  await click(page.locator('tr:has(.cvm-why-line) .job-title').first(), { fx: 0.4, after: 1200 });
  await page.waitForSelector('#cvmWhy', { timeout: 10000 });
  await moveTo('#cvmWhy', { steps: 25, fy: 0.4 });
  await pause(3200);
  await snap('panel');
  await cap('Apply straight from the job, on the university’s own site', 400);
  await moveTo('#panelApplyLink', { steps: 25 });
  await pause(2000);
  await cap('', 600);

  // ── 6. End card ──
  await card(`<div class="k">HKAcadJobs</div><h1>Find jobs that fit your CV</h1>
    <p>Free with an account · Your CV is never stored · Contact details are removed before AI analysis</p>
    <p class="s">www.hkacadjobs.org &nbsp;·&nbsp; Demo with a sample CV</p>`, 4200);
  await snap('end');
  mark('end');
  fs.writeFileSync(path.join(OUT, 'marks.json'), JSON.stringify(marks, null, 1));
  console.log(marks);

  const video = page.video();
  await context.close();
  if (video) {
    const p = await video.path();
    fs.renameSync(p, path.join(OUT, 'raw.webm'));
    console.log('video:', path.join(OUT, 'raw.webm'));
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
