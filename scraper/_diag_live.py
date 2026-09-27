"""Temporary live diagnostics for the THEi and HKU scrapers (run on GitHub Actions).
Prints page structure / network behaviour only; writes nothing. Delete after use."""
import re, time, json, requests
from playwright.sync_api import sync_playwright

JOB_RE = re.compile(r"/en/job/(\d+)")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def section(t): print(f"\n{'=' * 20} {t} {'=' * 20}", flush=True)

def diag_thei(p):
    section("THEi")
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900}, user_agent=UA)
    t0 = time.time()
    try:
        pg.goto("https://thei.edu.hk/career-opportunities/", wait_until="domcontentloaded", timeout=60000)
        print(f"domcontentloaded in {time.time()-t0:.1f}s")
        pg.wait_for_selector(".e-loop-item", timeout=30000)
        print(f".e-loop-item appeared after {time.time()-t0:.1f}s")
    except Exception as e:
        print("LOAD ERROR:", e)
    js = """() => {
      const out = {};
      out.items = document.querySelectorAll('.e-loop-item').length;
      out.grids = [...document.querySelectorAll('.elementor-widget-loop-grid, .elementor-widget-loop-carousel, [data-widget_type^="loop"]')].map(g => ({
        cls: g.className.slice(0, 120), wtype: g.getAttribute('data-widget_type'),
        items: g.querySelectorAll('.e-loop-item').length,
        settings: (g.getAttribute('data-settings') || '').slice(0, 300),
        heading: (g.closest('.e-con, section')?.querySelector('h1,h2,h3,h4')?.innerText || '').slice(0, 60),
      }));
      out.loadMore = [...document.querySelectorAll('.e-loop__load-more, [class*="load-more"], [class*="load_more"]')].map(e => ({
        cls: e.className.slice(0, 100), display: getComputedStyle(e).display,
        html: e.outerHTML.replace(/\\s+/g, ' ').slice(0, 400)}));
      out.moreButtons = [...document.querySelectorAll('a,button')].filter(e => /load|more|next/i.test(e.innerText || ''))
        .map(e => ({tag: e.tagName, text: (e.innerText || '').trim().slice(0, 40), cls: e.className.slice(0, 80), href: e.getAttribute('href')})).slice(0, 15);
      out.pagination = [...document.querySelectorAll('.e-load-more-anchor, nav.elementor-pagination, .page-numbers')].map(e => e.outerHTML.replace(/\\s+/g,' ').slice(0, 300));
      out.firstCards = [...document.querySelectorAll('.e-loop-item')].slice(0, 3).map(c => ({
        text: c.innerText.replace(/\\s+/g, ' | ').slice(0, 200),
        links: [...c.querySelectorAll('a[href]')].map(a => a.href).slice(0, 3)}));
      return out;
    }"""
    try:
        print(json.dumps(pg.evaluate(js), indent=1, ensure_ascii=False)[:6000])
        for i in range(6):
            pg.keyboard.press("End"); pg.wait_for_timeout(1500)
        print("items after 6x End:", pg.evaluate("document.querySelectorAll('.e-loop-item').length"))
        # try every candidate load-more control
        for i in range(8):
            before = pg.evaluate("document.querySelectorAll('.e-loop-item').length")
            clicked = pg.evaluate("""() => {
              const c = document.querySelector('.e-loop__load-more a, .e-loop__load-more button, .e-loop__load-more .elementor-button');
              if (!c) return null; if (getComputedStyle(c.closest('.e-loop__load-more')).display === 'none') return 'hidden';
              c.click(); return c.tagName + ':' + (c.innerText || '').trim(); }""")
            if clicked in (None, 'hidden'):
                print(f"load-more round {i}: {clicked}"); break
            try:
                pg.wait_for_function(f"document.querySelectorAll('.e-loop-item').length > {before}", timeout=10000)
            except Exception:
                pass
            after = pg.evaluate("document.querySelectorAll('.e-loop-item').length")
            print(f"load-more round {i}: clicked {clicked}; items {before} -> {after}")
        hrefs = pg.evaluate("""() => [...new Set([...document.querySelectorAll('.e-loop-item a[href]')].map(a => a.href))]""")
        single = [h for h in hrefs if h.startswith('https://thei.edu.hk/') and h.replace('https://thei.edu.hk/', '').strip('/').count('/') == 0 and h.replace('https://thei.edu.hk/', '').strip('/')]
        print(f"unique card links: {len(hrefs)}; single-slug job links: {len(single)}")
        print("sample:", single[:5])
    except Exception as e:
        print("THEI DIAG ERROR:", repr(e))
    b.close()

def diag_hku(p):
    section("HKU")
    b = p.chromium.launch()
    pg = b.new_page(user_agent=UA)
    xhr = []
    pg.on("request", lambda r: xhr.append((r.method, r.url)) if r.resource_type in ("xhr", "fetch") else None)
    t0 = time.time()
    pg.goto("https://jobs.hku.hk/en/listing/", timeout=60000)
    pg.wait_for_load_state("networkidle", timeout=30000)
    print(f"loaded in {time.time()-t0:.1f}s")
    count_js = """() => ({rows: document.querySelectorAll('tr').length,
        jobs: new Set([...document.querySelectorAll('a[href*="/en/job/"]')].map(a => a.getAttribute('href'))).size})"""
    print("initial:", pg.evaluate(count_js))
    info = pg.evaluate("""() => {
      const btn = [...document.querySelectorAll('button, a, input[type=button]')].find(b => /more.?job|load.?more|show.?more|view.?more/i.test(b.textContent));
      return {button: btn ? btn.outerHTML.replace(/\\s+/g,' ').slice(0, 400) : null,
              rss: [...document.querySelectorAll('link[type*="rss"], a[href*="rss"]')].map(l => l.href || l.getAttribute('href')),
              tables: document.querySelectorAll('table').length,
              firstRow: document.querySelector('a[href*="/en/job/"]')?.closest('tr')?.outerHTML.replace(/\\s+/g,' ').slice(0, 600)};
    }""")
    print(json.dumps(info, indent=1, ensure_ascii=False))
    # click 6 times, measuring how long each batch takes to arrive
    for i in range(6):
        before = pg.evaluate(count_js)
        t = time.time()
        ok = pg.evaluate("""() => { const b = [...document.querySelectorAll('button, a, input[type=button]')].find(b => /more.?job|load.?more|show.?more|view.?more/i.test(b.textContent)); if (!b) return false; b.scrollIntoView(); b.click(); return b.textContent.trim(); }""")
        if not ok:
            print(f"click {i}: no button"); break
        waited = None
        for _ in range(60):
            pg.wait_for_timeout(250)
            if pg.evaluate(count_js)["jobs"] > before["jobs"]:
                waited = time.time() - t; break
        print(f"click {i} ('{ok}'): {before} -> {pg.evaluate(count_js)} ; batch arrived after {waited if waited is None else round(waited, 2)}s")
    print("XHR/fetch requests seen:")
    for m, u in xhr[:25]: print("  ", m, u[:200])
    b.close()
    section("HKU direct endpoints")
    s = requests.Session(); s.headers["User-Agent"] = UA
    for u in ["https://jobs.hku.hk/en/listing/rss", "https://jobs.hku.hk/en/listing.rss",
              "https://jobs.hku.hk/en/listing/?page=2&page-items=20",
              "https://jobs.hku.hk/en/listing/?page=1&page-items=500"]:
        try:
            r = s.get(u, timeout=30)
            body = r.text
            n = len(set(JOB_RE.findall(body)))
            print(f"{r.status_code} {len(body):>8}B items={body.count('<item>')} joblinks={n} ctype={r.headers.get('content-type')} {u}")
        except Exception as e:
            print("ERR", u, e)
    for u, _ in [(u, m) for m, u in xhr[:8] if "listing" in u or "job" in u]:
        try:
            r = s.get(u, timeout=30, headers={"X-Requested-With": "XMLHttpRequest"})
            n = len(set(JOB_RE.findall(r.text)))
            print(f"replay {r.status_code} {len(r.text)}B joblinks={n} {u[:160]}")
        except Exception as e:
            print("replay ERR", u, e)

with sync_playwright() as p:
    for fn in (diag_thei, diag_hku):
        try: fn(p)
        except Exception as e: print(f"{fn.__name__} crashed: {e!r}")
