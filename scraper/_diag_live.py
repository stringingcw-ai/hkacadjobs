"""Temporary live diagnostics (run on GitHub Actions): HKUST, HKBU, Lingnan, SFU, Chu Hai, CPCE.
Prints page structure / network behaviour only; writes nothing. Delete after use."""
import json, re, time, requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
def sec(t): print(f"\n{'=' * 18} {t} {'=' * 18}", flush=True)
def squash(s, n=600): return re.sub(r"\s+", " ", s or "")[:n]

def hkust(p):
    sec("HKUST")
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA)
    pg.goto("https://hkustcareers.hkust.edu.hk/join-us/current-opening/academic-careers", timeout=60000)
    pg.wait_for_load_state("networkidle", timeout=30000); pg.wait_for_timeout(3000)
    cards = pg.evaluate("""() => {
      const out = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n; while ((n = walker.nextNode())) {
        const m = n.textContent.trim().match(/^Job ID: (\\d+)$/); if (!m) continue;
        let el = n.parentElement;
        for (let i = 0; i < 8 && el; i++) { if (el.querySelectorAll('a[href]').length) break; el = el.parentElement; }
        out.push({id: m[1], links: el ? [...el.querySelectorAll('a[href]')].map(a => [a.textContent.trim().slice(0,30), a.href]) : [],
                  html: el ? el.outerHTML.replace(/\\s+/g,' ').slice(0, 500) : ''});
      }
      return out; }""")
    print("cards:", len(cards))
    kinds = {}
    for c in cards:
        k = tuple(sorted({re.sub(r"[?#].*", "", h).split("/")[2] for _, h in c["links"]}))
        kinds.setdefault(k, []).append(c)
    for k, cs in kinds.items():
        print(f"link hosts {k}: {len(cs)} cards; e.g. {cs[0]['id']}: {cs[0]['links'][:4]}")
    noil = [c for c in cards if not any("interfolio" in h for _, h in c["links"])]
    for c in noil[:2]:
        print("NON-INTERFOLIO CARD:", c["id"], c["links"], "\n   ", c["html"])
    b.close()
    ref = noil[0]["id"] if noil else "179929"
    for u in [f"https://hrmsxprod.psft.ust.hk:8044/psp/hrmsxprod/EMPLOYEE/HRMS/c/HRS_HRAM.HRS_CE.GBL?Page=HRS_CE_JOB_DTL&Action=A&JobOpeningId={ref}&SiteId=1000&PostingSeq=1",
              f"https://hrmsxprod.psft.ust.hk/psp/hrmsxprod/EMPLOYEE/HRMS/c/HRS_HRAM.HRS_CE.GBL?Page=HRS_CE_JOB_DTL&Action=A&JobOpeningId={ref}&SiteId=1000&PostingSeq=1",
              "https://hkustcareers.hkust.edu.hk/join-us/current-opening/academic-careers"]:
        try:
            r = requests.get(u, headers=H, timeout=15); print(f"  GET {r.status_code} {len(r.text)}B {u[:110]}")
        except Exception as e:
            print(f"  GET ERR {type(e).__name__}: {str(e)[:120]} {u[:110]}")

def hkbu(p):
    sec("HKBU")
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA)
    seen = []
    def on_resp(r):
        if "hcmRestApi" in r.url and "recruitingCEJobRequisitions" in r.url:
            try: seen.append((r.status, r.url, r.json()))
            except Exception: seen.append((r.status, r.url, None))
    pg.on("response", on_resp)
    pg.goto("https://fa-ewqq-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/hkbu/jobs", timeout=60000)
    pg.wait_for_timeout(9000)
    for st, u, js in seen[:2]:
        print("API", st, u)
        if js:
            items = js.get("items") or []
            it = items[0] if items else {}
            reqs = it.get("requisitionList") or []
            print("  top keys:", list(js.keys())[:10], "| item keys:", list(it.keys())[:25])
            print("  TotalJobsCount:", it.get("TotalJobsCount"), "| requisitions on page:", len(reqs))
            if reqs: print("  requisition keys:", list(reqs[0].keys())); print("  first:", json.dumps({k: reqs[0].get(k) for k in list(reqs[0].keys())[:18]}, ensure_ascii=False)[:900])
    b.close()
    if seen:
        u = seen[0][1]
        u2 = re.sub(r"limit=\d+", "limit=200", u)
        r = requests.get(u2, headers={**H, "Accept": "application/json"}, timeout=30)
        try:
            it = (r.json().get("items") or [{}])[0]
            print(f"replay limit=200 via requests: {r.status_code} total={it.get('TotalJobsCount')} got={len(it.get('requisitionList') or [])}")
        except Exception as e:
            print("replay failed", r.status_code, str(e)[:100], r.text[:200])

def lingnan(p):
    sec("LINGNAN")
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA)
    calls = []
    pg.on("request", lambda r: calls.append((r.method, r.url, r.post_data, dict(r.headers))) if r.resource_type in ("xhr", "fetch") else None)
    pg.goto("https://lingnan.csod.com/ux/ats/careersite/4/home?c=lingnan", timeout=60000)
    pg.wait_for_load_state("networkidle", timeout=30000); pg.wait_for_timeout(2000)
    links = pg.evaluate("() => [...new Set([...document.querySelectorAll('a[href*=requisition]')].map(a => a.getAttribute('href')))]")
    print("requisition links on page 1:", len(links), links[:3])
    for m, u, body, hdr in calls[:15]:
        print(" ", m, u[:150], "| body:", (body or "")[:250])
    search = [c for c in calls if "search" in c[1].lower()]
    if search:
        m, u, body, hdr = search[0]
        print("SEARCH headers:", {k: (v[:25] + "…") for k, v in hdr.items() if k.lower() in ("authorization", "content-type", "csod-accept-language")})
        try:
            payload = json.loads(body or "{}")
            for key in ("pageSize", "pagesize", "PageSize"):
                if key in payload: payload[key] = 200
            r = pg.request.post(u, data=json.dumps(payload), headers={k: v for k, v in hdr.items() if k.lower() in ("authorization", "content-type", "csod-accept-language", "accept")})
            js = r.json()
            print("replay status", r.status, "| keys:", list(js.keys())[:8])
            data = js.get("data") or {}
            reqs = data.get("requisitions") or []
            print("  totalCount:", data.get("totalCount"), "returned:", len(reqs), "| req keys:", list(reqs[0].keys())[:20] if reqs else None)
            if reqs: print("  first:", json.dumps(reqs[0], ensure_ascii=False)[:700])
        except Exception as e:
            print("replay error", repr(e)[:300])
    b.close()

def sfu():
    sec("SFU")
    for u in ["https://www.sfu.edu.hk/en/career/academic-teaching-positions/index.html",
              "https://www.sfu.edu.hk/en/career/research-project-positions/index.html"]:
        s = BeautifulSoup(requests.get(u, headers=H, timeout=30).text, "html.parser")
        accs = s.find_all("div", class_="accordion-wrap")
        print(u.split("/")[-2], "accordions:", len(accs))
        for a in accs[:2]:
            print("  HTML:", squash(str(a), 700))
            c = a.find("div", class_="accordion-content")
            if c:
                t = c.get_text("\n")
                i = t.find("Deadline")
                print("  deadline text:", repr(t[i:i + 80]) if i >= 0 else None)

def chuhai(p):
    sec("CHU HAI")
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA)
    got = {}
    pg.on("response", lambda r: got.setdefault(r.url, r) if "api/special/careers" in r.url else None)
    pg.goto("https://www.chuhai.edu.hk/en/page/jobs?id=b9f07df8-bc36-430a-91ea-b8f196e36f18", timeout=60000, wait_until="networkidle")
    pg.wait_for_timeout(1500)
    for u, r in list(got.items())[:1]:
        html = ((r.json().get("data") or {}).get("content") or {}).get("article_content", "")
        s = BeautifulSoup(html, "html.parser")
        w = s.select("div.accordion-wrapper")
        print("accordions:", len(w))
        for x in w[:2]: print("  HTML:", squash(str(x), 500))
    dom = pg.evaluate("() => [...document.querySelectorAll('.accordion-wrapper, [class*=accordion]')].slice(0,4).map(e => ({id: e.id, cls: e.className.slice(0,60), anchors: [...e.querySelectorAll('[id]')].slice(0,3).map(x => x.id)}))")
    print("DOM accordion ids:", dom)
    b.close()

def cpce():
    sec("CPCE")
    base = "https://jas.cpce-polyu.edu.hk"
    rows = []
    for sid in (5011, 5013, 5015):
        s = BeautifulSoup(requests.get(f"{base}/list?id={sid}&sort=sort_rel", headers=H, timeout=30).text, "html.parser")
        hdr = [squash(th.get_text(), 60) for th in s.select("table.list-table th")]
        print(sid, "header:", hdr)
        for r in s.select("table.list-table tr.list-row")[:4]:
            rows.append((r.get("data-id"), [squash(td.get_text(), 50) for td in r.find_all("td")]))
    for did, cells in rows[:6]:
        t = BeautifulSoup(requests.get(f"{base}/detail?id={did}", headers=H, timeout=30).text, "html.parser").get_text("\n", strip=True)
        hits = [squash(t[max(0, m.start() - 60): m.end() + 90], 170) for m in re.finditer(r"screening|closing date|commence|until the post|until filled|deadline", t, re.I)][:3]
        print(f"  {did} listing={cells[2] if len(cells) > 2 else cells} :: {hits}")

with sync_playwright() as p:
    for fn in (lambda: hkust(p), lambda: hkbu(p), lambda: lingnan(p), sfu, lambda: chuhai(p), cpce):
        try: fn()
        except Exception as e: print("DIAG ERROR:", repr(e)[:300])
