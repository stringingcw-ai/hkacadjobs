"""HKUST's listing: each job's Interfolio link comes from its own card. Until 22 Nov
2026 each link went to the Job ID seen before it, and as a card's link comes before
its Job ID, every academic job had the next card's link and summary."""
from sites.hkust import interfolio_links


def card(ref, title, link=None, link_after=False):
    """A card as the listing renders it (trimmed): the title is the Interfolio link."""
    href = f"https://apply.interfolio.com/{link}" if link and not link_after else "#"
    after = f'<a href="https://apply.interfolio.com/{link}">Apply</a>' if link and link_after else ""
    return (f'<div class="views-row"><div class="views-field views-field-nothing"><span class="field-content">'
            f'<div class="job-card"><h3><a href="{href}" rel="noopener" target="_blank">{title}</a></h3>'
            f'<p>Job ID: {ref}</p><div class="info-row"><p><img alt="Department"/> Division of Life Science </p>'
            f'<p><img alt="Open Date"/> Open Date: <time>20 November 2026</time></p></div>{after}</div>'
            f'</span></div></div>')


def listing(*cards):
    return f'<html><body><h2>School (3)</h2><div class="view-content">{"".join(cards)}</div></body></html>'


def test_each_job_gets_the_link_in_its_own_card():
    # As on the live page (21 Nov 2026); the old mapping gave 195841 the CHEM link
    # (196417) and 195054 the next job's (194909).
    html = listing(card("195841", "Teaching-track Faculty Position", 197127),
                   card("195054", "CHEM - Faculty Positions", 196417),
                   card("193429", "Assistant, Associate, or Full Professor", 194909))
    assert interfolio_links(html) == {
        "195841": "https://apply.interfolio.com/197127",
        "195054": "https://apply.interfolio.com/196417",
        "193429": "https://apply.interfolio.com/194909",
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
