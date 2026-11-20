"""HKU's careers site (since 19/20 Nov 2026): search result cards, paging, AWS WAF
challenges, and job ids that stay the same as on the old site."""
import pytest
import requests

import core
from sites import hku


def card(number, title, closing="Closing on: Dec 10 2026", dept="Faculty of Business and Economics (07000)"):
    """A result card as the search page renders it (trimmed)."""
    closing_li = (f'<li class="job-component-icon-and-text job-component-closing-on">'
                  f'<i class="fas fa-calendar-day"></i><span> {closing} </span></li>') if closing else ""
    return f"""
    <article><div class="card job-search-results-card"><div class="card-body job-search-results-card-body">
      <h3 class="card-title job-search-results-card-title">
        <a href="https://jobs.hku.hk/jobs/{title.lower().replace(' ', '-')}-2ca71215" id="link_job_title_3_0_0">{title}</a></h3>
      <div class="job-component-details"><div class="job-component-list"><ul>
        <li class="job-component-icon-and-text job-component-requisition-identifier">
          <i title="Requisition identifier"></i><span> {number} </span></li></ul></div>
      <div class="job-component-list job-component-list-department"><ul>
        <li class="job-component-icon-and-text job-component-department"><span> {dept} </span></li></ul></div>
      <div class="job-component-list job-component-list-employment_type"><ul>
        <li class="job-component-icon-and-text job-component-employment-type"><span> Full-time </span></li></ul></div>
      <div class="job-component-list"><ul>{closing_li}</ul></div>
      <div class="job-component-list"><ul>
        <li class="job-component-icon-and-text job-component-dropdown-field-1"><span> Faculty of Business and Economics </span></li>
      </ul></div></div></div>
      <div class="card-footer job-search-results-footer"><a href="https://jobs.hku.hk/jobs/x">Read more</a></div>
    </div></article>"""


def search_page(cards, pages=(1, 2)):
    featured = card("400001", "Featured Professoriate Posts")
    paging = "".join(f'<a href="/jobs/search?page={p}">{p}</a>' for p in pages)
    return (f'<div class="featured-jobs">{featured}</div>'
            f'<div class="block-job-search-results">{"".join(cards)}</div><nav>{paging}</nav>')


def test_a_card_becomes_a_job_with_the_id_the_old_site_gave_it():
    [job] = hku.parse_cards(search_page([card("537976", "Assistant Professor in Finance")]))
    assert job["id"] == "HKU-537976" == core.make_id("HKU", "537976")
    assert job["reference"] == "537976"
    assert job["title"] == "Assistant Professor in Finance"
    assert job["department"] == "Faculty of Business and Economics (07000)"
    assert job["deadline"] == "2026-12-10"
    assert job["apply_url"] == "https://jobs.hku.hk/jobs/assistant-professor-in-finance-2ca71215"
    assert core.PLACEHOLDER_MARKER in job["description"]


def test_featured_jobs_are_not_results_and_a_missing_closing_date_is_blank():
    jobs = hku.parse_cards(search_page([card("537977", "Post-doctoral Fellow", closing="")]))
    assert [j["id"] for j in jobs] == ["HKU-537977"]
    assert jobs[0]["deadline"] == ""


@pytest.mark.parametrize("text,date", [
    ("Closing on: Dec 10 2026", "2026-12-10"),
    ("Closing on: September 3 2027", "2027-09-03"),
    ("Closing on: 15 January 2027", "2027-01-15"),
    ("Closing on: until filled", ""),
    ("", ""),
])
def test_closing_dates(text, date):
    assert hku.closing_date(text) == date


def test_every_search_page_is_read_and_repeats_are_dropped():
    pages = {
        hku.SEARCH.format(1): search_page([card("1001", "Lecturer in Law"), card("1002", "Professor of Physics")], pages=(1, 2, 3)),
        hku.SEARCH.format(2): search_page([card("1002", "Professor of Physics"), card("1003", "Research Assistant")], pages=(1, 2, 3)),
        hku.SEARCH.format(3): search_page([card("1004", "Postdoctoral Fellow")], pages=(2, 3)),
    }
    asked = []
    jobs = hku.search_all(lambda url: asked.append(url) or pages[url])
    assert [j["id"] for j in jobs] == ["HKU-1001", "HKU-1002", "HKU-1003", "HKU-1004"]
    assert asked == [hku.SEARCH.format(n) for n in (1, 2, 3)]


def test_a_search_page_with_no_jobs_before_the_last_one_fails_the_scrape():
    pages = {hku.SEARCH.format(1): search_page([card("1001", "Lecturer in Law")], pages=(1, 2, 3)),
             hku.SEARCH.format(2): "<html>Something went wrong</html>"}
    with pytest.raises(RuntimeError, match="page 2 of 3 has no jobs"):
        hku.search_all(pages.get)


class Resp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class Session:
    def __init__(self, *answers):
        self.answers = list(answers)

    def get(self, url, **kw):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_a_waf_challenge_is_waited_out(capsys):
    waits = []
    challenge = Resp(202, "", {"x-amzn-waf-action": "challenge"})
    html = hku.fetch("u", Session(challenge, requests.ConnectionError("reset"), Resp(200, "<html>ok</html>")),
                     sleep=waits.append)
    assert html == "<html>ok</html>"
    assert waits[1:] == [hku.RETRY_WAIT, 2 * hku.RETRY_WAIT]
    assert "u: HTTP 202, AWS WAF challenge; waiting to retry" in capsys.readouterr().out


def test_a_page_that_never_loads_raises():
    challenge = Resp(202, "", {"x-amzn-waf-action": "challenge"})
    with pytest.raises(RuntimeError, match=r"u didn't load \(HTTP 202, AWS WAF challenge\)"):
        hku.fetch("u", Session(challenge, challenge, challenge), sleep=lambda s: None)


JOB_PAGE = """<html><body><header><nav>Visit Home My Profile Kiosk mode and other site links here</nav></header>
<main><h1>Assistant Professor in Finance</h1>
<p>Assistant Professor in Finance in the Faculty of Business and Economics (Ref.: 537976)</p>
<p>Applicants should possess a PhD in Finance and a strong record of research publications in leading journals.</p>
<p>The appointee will teach undergraduate and postgraduate courses and supervise research students.</p>
<p>A highly competitive salary commensurate with qualifications and experience will be offered.</p>
<section>%s</section></main>
<footer>Copyright © 2026 Human Resources Office, The University of Hong Kong. All rights reserved.</footer></body></html>
""" % card("537978", "Post-doctoral Fellow in the Department of Chemistry")


def test_a_job_page_description_leaves_out_the_site_chrome_and_other_jobs():
    text = hku.description(JOB_PAGE)
    assert text.startswith("Assistant Professor in Finance in the Faculty of Business and Economics (Ref.: 537976)")
    assert "Applicants should possess a PhD" in text
    assert "Kiosk mode" not in text and "Copyright" not in text and "Chemistry" not in text


def test_a_job_page_with_too_little_text_has_no_description():
    assert hku.description("<html><body><main><p>Let's confirm you are human</p></main></body></html>") == ""


def test_known_jobs_keep_their_summaries_and_new_ones_get_their_job_page(monkeypatch):
    summary = "**Role**\n• Teach finance\n• Research in finance, publishing regularly in leading international journals"
    monkeypatch.setitem(core._existing_descriptions, "HKU-1001", summary)
    page = search_page([card("1001", "Lecturer in Law"), card("1002", "Professor of Physics"),
                        card("1003", "Administrative Assistant")], pages=(1,))
    asked = []

    def fake_fetch(url, session):
        asked.append(url)
        return page if "/jobs/search" in url else JOB_PAGE
    monkeypatch.setattr(hku, "fetch", fake_fetch)

    jobs = {j["id"]: j for j in hku.scrape_hku()}
    assert set(jobs) == {"HKU-1001", "HKU-1002"}          # admin role skipped
    assert jobs["HKU-1001"]["description"] == summary
    assert "Applicants should possess a PhD" in jobs["HKU-1002"]["description"]
    assert asked == [hku.SEARCH.format(1), "https://jobs.hku.hk/jobs/professor-of-physics-2ca71215"]
