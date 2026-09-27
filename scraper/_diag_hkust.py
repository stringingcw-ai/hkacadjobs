"""Temporary: can HKUST PeopleSoft job descriptions be read from GitHub's runners?"""
import csv
from playwright.sync_api import sync_playwright
rows = [r for r in csv.DictReader(open("jobs.csv", encoding="utf-8"))
        if r["university"] == "HKUST" and "psft" in r["apply_url"]][:3]
with sync_playwright() as p:
    b = p.chromium.launch()
    for r in rows:
        for label, url in [("psp", r["apply_url"]), ("psc", r["apply_url"].replace("/psp/", "/psc/"))]:
            pg = b.new_page()
            try:
                resp = pg.goto(url, timeout=40000, wait_until="networkidle")
                pg.wait_for_timeout(3000)
                print(f"\n=== {r['id']} {label} status={resp.status if resp else None} url={pg.url[:120]}")
                for f in pg.frames:
                    try:
                        t = f.inner_text("body")
                    except Exception as e:
                        t = f"<err {e}>"
                    print(f"  frame {f.name!r} {f.url[:100]} len={len(t)}")
                    print("   ", t[:700].replace("\n", " | "))
            except Exception as e:
                print(f"=== {r['id']} {label} ERROR {e}")
            pg.close()
    # the careers page: does a card link to a detail page with text?
    pg = b.new_page()
    pg.goto("https://hkustcareers.hkust.edu.hk/join-us/current-opening/academic-careers", timeout=40000, wait_until="networkidle")
    pg.wait_for_timeout(3000)
    links = pg.evaluate("() => [...document.querySelectorAll('a')].map(a => [a.innerText.trim().slice(0,60), a.href]).filter(x => x[1] && !x[1].includes('#'))")
    ext = [l for l in links if 'hkustcareers' not in l[1]]
    print("\nlinks:", len(links), "external:", len(ext))
    for l in ext[:25]: print("  ", l)
    b.close()
