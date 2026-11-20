"""HKU's listing: a plain request is used only when it returns job links; anything
else (an error, or an AWS WAF challenge page) falls back to a browser."""
import requests

from sites.hku import fetch_listing


class Resp:
    def __init__(self, status, text, headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")


LISTING = '<table><tr><td><a href="/en/job/537812/lecturer">Lecturer</a></td></tr></table>'


def test_a_listing_with_jobs_is_used():
    assert fetch_listing("u", get=lambda *a, **k: Resp(200, LISTING)) == LISTING


def test_a_waf_challenge_falls_back_to_the_browser(capsys):
    challenge = Resp(202, "<html><script src='challenge.js'></script></html>",
                     {"x-amzn-waf-action": "challenge"})
    assert fetch_listing("u", get=lambda *a, **k: challenge) is None
    assert "returned no jobs (HTTP 202, AWS WAF challenge); retrying in a browser" in capsys.readouterr().out


def test_an_empty_listing_or_an_error_falls_back_too(capsys):
    assert fetch_listing("u", get=lambda *a, **k: Resp(200, "<html></html>")) is None
    assert fetch_listing("u", get=lambda *a, **k: Resp(503, "busy")) is None

    def down(*a, **k):
        raise requests.ConnectionError("timed out")
    assert fetch_listing("u", get=down) is None
    out = capsys.readouterr().out
    assert "(HTTP 200)" in out and "503 Error" in out and "timed out" in out
