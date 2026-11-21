"""HKUST's listing: each job's Interfolio link comes from its own card. Until 22 Nov
2026 each link went to the Job ID seen before it, and as a card's link comes before
its Job ID, every academic job had the next card's link and summary."""
from sites.hkust import interfolio_links


def card(ref, title, link=None, link_after=False):
    a = f'<a href="https://apply.interfolio.com/{link}" target="_blank">Apply</a>' if link else ""
    return (f'<div class="job-card"><h3><a href="#">{title}</a></h3>{"" if link_after else a}'
            f'<div class="job-meta"><span>Job ID: {ref}</span></div>'
            f'<p>Department of Chemistry</p><p>Apply by: 2026-12-31</p>{a if link_after else ""}</div>')


def listing(*cards):
    return f'<html><body><h2>School (3)</h2><div class="job-list">{"".join(cards)}</div></body></html>'


def test_each_job_gets_the_link_in_its_own_card():
    html = listing(card("195841", "Teaching-track Faculty Position", 196417),
                   card("195054", "CHEM - Faculty Positions", 194909),
                   card("193429", "Assistant, Associate, or Full Professor", 194207))
    assert interfolio_links(html) == {
        "195841": "https://apply.interfolio.com/196417",
        "195054": "https://apply.interfolio.com/194909",
        "193429": "https://apply.interfolio.com/194207",
    }


def test_a_card_without_a_link_gets_none_not_its_neighbours():
    html = listing(card("1", "Lecturer", 101), card("2", "Research Assistant"), card("3", "Professor", 103))
    assert interfolio_links(html) == {"1": "https://apply.interfolio.com/101",
                                      "3": "https://apply.interfolio.com/103"}


def test_a_link_after_the_job_id_in_the_same_card_is_found_too():
    html = listing(card("1", "Lecturer", 101, link_after=True), card("2", "Professor", 102, link_after=True))
    assert interfolio_links(html) == {"1": "https://apply.interfolio.com/101",
                                      "2": "https://apply.interfolio.com/102"}


def test_relative_links_are_made_absolute():
    html = listing('<div><a href="/apply/interfolio/7">Apply</a><span>Job ID: 7</span></div>')
    assert interfolio_links(html, "https://hkustcareers.hkust.edu.hk/join-us/x") == {
        "7": "https://hkustcareers.hkust.edu.hk/apply/interfolio/7"}
