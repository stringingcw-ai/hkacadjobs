"""EdUHK's category pages: wait for the jobs or EdUHK's "No results found.", retry a
page that shows neither, and check an empty answer once more (the 21 Nov 2026 run
found no Academic jobs after a fixed 3 s wait)."""
import pytest

from sites.eduhk import _open_category

JOBS = "Current Openings Assistant Professor Department of Psychology Ref: 2600980 Ad Date: 19 Nov 2026"
EMPTY = "Current Openings Filter by Units All Units Search Reset No results found. Email info@eduhk.hk"
BROKEN = "Service Unavailable"


class Page:
    """A Playwright page that shows `screens` in turn, one per load."""
    def __init__(self, *screens):
        self.screens, self.loads, self.waits = list(screens), 0, []

    def goto(self, url, **kw):
        self.loads += 1

    @property
    def text(self):
        return self.screens[min(self.loads, len(self.screens)) - 1]

    def wait_for_function(self, script, **kw):
        if "Ad Date:" not in self.text and "No results found" not in self.text:
            raise TimeoutError("Page.wait_for_function: Timeout 30000ms exceeded.")

    def inner_text(self, selector):
        return self.text

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_a_page_with_jobs_is_read_straight_away():
    page = Page(JOBS)
    assert _open_category(page, "u") is True
    assert (page.loads, page.waits) == (1, [])


def test_no_results_is_checked_once_more_then_believed(capsys):
    page = Page(EMPTY, EMPTY)
    assert _open_category(page, "u") is False
    assert page.loads == 2
    out = capsys.readouterr().out
    assert "⚠️" not in out        # an empty category is usual (Senior Management)
    assert "EdUHK lists no jobs at u ('No results found.')" in out


def test_a_momentary_no_results_gets_the_jobs_on_the_second_look():
    page = Page(EMPTY, JOBS)
    assert _open_category(page, "u") is True
    assert page.loads == 2


def test_a_page_showing_neither_is_retried(capsys):
    page = Page(BROKEN, JOBS)
    assert _open_category(page, "u") is True
    assert page.waits == [5000]
    assert "Timeout 30000ms exceeded.; the page says: 'Service Unavailable' (attempt 1/3)" in capsys.readouterr().out


def test_a_page_that_never_shows_either_raises_with_what_it_said():
    page = Page(BROKEN)
    with pytest.raises(RuntimeError, match=r"u showed no jobs and no 'No results found' .*Service Unavailable"):
        _open_category(page, "u")
    assert page.loads == 3
