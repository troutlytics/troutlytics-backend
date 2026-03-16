import os

import pytest
import requests
from dotenv import load_dotenv
from geopy import GoogleV3

from web_scraper.scraper import Scraper


class DummyResponse:
    def __init__(self, status_code, content=b"<html></html>"):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def test_session_uses_browser_headers_by_default(monkeypatch):
    monkeypatch.delenv("SCRAPER_USER_AGENT", raising=False)

    session = Scraper._session()

    assert session.headers["User-Agent"] == Scraper.DEFAULT_BROWSER_USER_AGENT
    assert session.headers["Accept-Language"] == "en-US,en;q=0.9"
    assert session.headers["Upgrade-Insecure-Requests"] == "1"


def test_fetch_retries_with_browser_headers_after_403(monkeypatch):
    monkeypatch.setenv("SCRAPER_USER_AGENT", "TroutlyticsScraper/1.0 (+contact: troutlytics)")
    scraper = Scraper()
    calls = []

    def fake_get(url, timeout, headers=None):
        calls.append({"url": url, "timeout": timeout, "headers": headers})
        if len(calls) == 1:
            return DummyResponse(403, b"blocked")
        return DummyResponse(200, b"<html><body>ok</body></html>")

    monkeypatch.setattr(scraper.session, "get", fake_get)

    soup = scraper.fetch("https://example.com/trout")

    assert soup.select_one("body").get_text(strip=True) == "ok"
    assert calls[0]["headers"] is None
    assert calls[1]["headers"]["User-Agent"] == Scraper.DEFAULT_BROWSER_USER_AGENT
    assert calls[1]["headers"]["Accept-Language"] == "en-US,en;q=0.9"


@pytest.mark.skipif(not os.getenv("GV3_API_KEY"), reason="GV3_API_KEY is not configured")
def test_geocoder():
    load_dotenv()
    locator = GoogleV3(api_key=os.getenv("GV3_API_KEY"))
    lat_lon = locator.geocode("BLUE Lake Columbia County Washington").point
    assert lat_lon == (46.2775138, -117.814262, 0.0)
