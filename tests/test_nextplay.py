"""Tests for NextPlay Substack collector."""
from unittest.mock import patch, MagicMock, call

import pytest

from shortlist.collectors.nextplay import (
    NextPlayCollector, _is_career_url, _is_ats_url, _domain_to_slugs,
)
from shortlist.collectors.base import RawJob


MOCK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss>
<channel>
<item>
<title><![CDATA[37 fastest-growing startups]]></title>
<link>https://nextplayso.substack.com/p/37-fastest-growing</link>
<content:encoded><![CDATA[
<p>Check out these companies:</p>
<a href="https://jobs.ashbyhq.com/suno">Suno on Ashby</a>
<a href="https://job-boards.greenhouse.io/nabis">Nabis on Greenhouse</a>
<a href="https://jobs.lever.co/soraschools">Sora on Lever</a>
<a href="https://www.acme.com/about">About Acme (not career)</a>
<a href="https://www.linkedin.com/company/foo/jobs/">Foo on LinkedIn (skipped)</a>
<a href="https://jobs.ashbyhq.com/suno/another-job">Suno dupe</a>
<a href="https://www.bretton.com/careers#open-positions">Bretton direct careers</a>
<a href="https://resolve.ai/careers#open-positions">Resolve direct careers</a>
<a href="https://www.wonderful.ai/jobs">Wonderful direct jobs</a>
<a href="https://coolstartup.io/">CoolStartup homepage only</a>
]]></content:encoded>
</item>
</channel>
</rss>"""


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


class TestUrlClassification:
    def test_ats_url_ashby(self):
        assert _is_ats_url("https://jobs.ashbyhq.com/suno")

    def test_ats_url_greenhouse(self):
        assert _is_ats_url("https://job-boards.greenhouse.io/nabis")

    def test_ats_url_lever(self):
        assert _is_ats_url("https://jobs.lever.co/soraschools")

    def test_not_ats_url(self):
        assert not _is_ats_url("https://www.acme.com/careers")

    def test_career_url_path_careers(self):
        assert _is_career_url("https://www.bretton.com/careers")

    def test_career_url_path_jobs(self):
        assert _is_career_url("https://www.wonderful.ai/jobs")

    def test_career_url_path_positions(self):
        assert _is_career_url("https://www.acme.com/positions")

    def test_career_url_path_join_team(self):
        assert _is_career_url("https://lucislife.notion.site/join-lucis-team")

    def test_career_url_ats(self):
        assert _is_career_url("https://jobs.ashbyhq.com/suno")

    def test_not_career_url(self):
        assert not _is_career_url("https://www.acme.com/about")

    def test_not_career_url_homepage(self):
        assert not _is_career_url("https://coolstartup.io/")


class TestDomainToSlugs:
    def test_simple_domain(self):
        assert "acme" in _domain_to_slugs("acme.com")

    def test_strips_www(self):
        assert "acme" in _domain_to_slugs("www.acme.com")

    def test_strips_tld(self):
        assert "activesite" in _domain_to_slugs("activesite.bio")


class TestExtractUrls:
    def test_finds_ats_links(self):
        c = NextPlayCollector(probe_ats=False)
        articles = c._parse_rss(MOCK_RSS)
        career_urls, _ = c._extract_urls(articles)

        assert any("ashbyhq.com/suno" in u for u in career_urls)
        assert any("greenhouse.io/nabis" in u for u in career_urls)
        assert any("lever.co/soraschools" in u for u in career_urls)

    def test_finds_direct_career_paths(self):
        c = NextPlayCollector(probe_ats=False)
        articles = c._parse_rss(MOCK_RSS)
        career_urls, _ = c._extract_urls(articles)

        assert any("bretton.com/careers" in u for u in career_urls)
        assert any("resolve.ai/careers" in u for u in career_urls)
        assert any("wonderful.ai/jobs" in u for u in career_urls)

    def test_dedupes_same_ats_org(self):
        c = NextPlayCollector(probe_ats=False)
        articles = c._parse_rss(MOCK_RSS)
        career_urls, _ = c._extract_urls(articles)

        suno_urls = [u for u in career_urls if "ashbyhq.com/suno" in u]
        assert len(suno_urls) == 1

    def test_skips_linkedin(self):
        c = NextPlayCollector(probe_ats=False)
        articles = c._parse_rss(MOCK_RSS)
        career_urls, homepages = c._extract_urls(articles)

        all_urls = career_urls + homepages
        assert not any("linkedin.com" in u for u in all_urls)

    def test_collects_homepage_domains_for_probing(self):
        c = NextPlayCollector(probe_ats=False)
        articles = c._parse_rss(MOCK_RSS)
        _, homepages = c._extract_urls(articles)

        # coolstartup.io and acme.com are homepages (not career pages)
        assert any("coolstartup.io" in d for d in homepages)

    def test_doesnt_probe_domains_with_career_links(self):
        """If we already found a career link for a domain, don't probe it."""
        c = NextPlayCollector(probe_ats=False)
        articles = c._parse_rss(MOCK_RSS)
        _, homepages = c._extract_urls(articles)

        # bretton.com has a /careers link — shouldn't be in homepages
        assert not any("bretton.com" in d for d in homepages)


class TestFetchNew:
    @patch("shortlist.collectors.nextplay.fetch_career_page")
    @patch("shortlist.http.get")
    def test_fetches_career_pages(self, mock_get, mock_fetch):
        mock_resp = MagicMock()
        mock_resp.text = MOCK_RSS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        mock_fetch.return_value = [
            RawJob(title="VP Eng", company="test", url="https://example.com",
                   description="Lead team", source="ashby")
        ]

        c = NextPlayCollector(probe_ats=False)
        jobs = c.fetch_new()

        # Should call fetch_career_page for ATS links only (suno, nabis, soraschools)
        assert mock_fetch.call_count == 3
        assert len(jobs) == 3

    @patch("shortlist.http.get")
    def test_feed_failure_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("network error")
        c = NextPlayCollector()
        assert c.fetch_new() == []

class TestArticleCaching:
    def test_skips_already_crawled(self, tmp_path):
        from shortlist.db import init_db
        db = init_db(tmp_path / "test.db")
        db.row_factory = __import__("sqlite3").Row

        # Mark the article as already crawled
        db.execute(
            "INSERT INTO crawled_articles (url, source, title) "
            "VALUES ('https://nextplayso.substack.com/p/37-fastest-growing', 'nextplay', 'test')"
        )
        db.commit()

        with patch("shortlist.http.get") as mock_get, \
             patch("shortlist.collectors.nextplay.fetch_career_page") as mock_fetch:
            mock_resp = MagicMock()
            mock_resp.text = MOCK_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            c = NextPlayCollector(probe_ats=False, db=db)
            jobs = c.fetch_new()

            # Should NOT call fetch_career_page because article was already crawled
            mock_fetch.assert_not_called()
            assert jobs == []

    def test_marks_articles_crawled_after_fetch(self, tmp_path):
        from shortlist.db import init_db
        db = init_db(tmp_path / "test.db")
        db.row_factory = __import__("sqlite3").Row

        with patch("shortlist.http.get") as mock_get, \
             patch("shortlist.collectors.nextplay.fetch_career_page") as mock_fetch:
            mock_resp = MagicMock()
            mock_resp.text = MOCK_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            mock_fetch.return_value = []

            c = NextPlayCollector(probe_ats=False, db=db)
            c.fetch_new()

            # Article should now be recorded
            row = db.execute(
                "SELECT * FROM crawled_articles WHERE url = ?",
                ("https://nextplayso.substack.com/p/37-fastest-growing",)
            ).fetchone()
            assert row is not None
            assert row["source"] == "nextplay"

    def test_no_db_doesnt_crash(self):
        """Without a DB, caching is a no-op."""
        with patch("shortlist.http.get") as mock_get, \
             patch("shortlist.collectors.nextplay.fetch_career_page") as mock_fetch:
            mock_resp = MagicMock()
            mock_resp.text = MOCK_RSS
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            mock_fetch.return_value = []

            c = NextPlayCollector(probe_ats=False, db=None)
            jobs = c.fetch_new()
            # Should still work — just no caching
            assert mock_fetch.call_count == 3  # 3 ATS links


class TestProbeHomepages:
    @patch("shortlist.collectors.nextplay.discover_ats_from_domain")
    @patch("shortlist.collectors.career_page.fetch_greenhouse_jobs")
    def test_discovers_and_fetches(self, mock_gh, mock_discover):
        mock_discover.return_value = ("greenhouse", "coolstartup")
        mock_gh.return_value = [
            RawJob(title="EM", company="coolstartup", url="u",
                   description="d", source="greenhouse")
        ]
        # Patch FETCHERS to use the mock
        from shortlist.collectors import career_page
        original = career_page.FETCHERS["greenhouse"]
        career_page.FETCHERS["greenhouse"] = mock_gh
        try:
            c = NextPlayCollector(probe_ats=True)
            jobs = c._probe_homepages(["coolstartup.io"])
            mock_discover.assert_called_with("coolstartup.io")
            mock_gh.assert_called_with("coolstartup")
            assert len(jobs) == 1
        finally:
            career_page.FETCHERS["greenhouse"] = original

    @patch("shortlist.collectors.nextplay.discover_ats_from_domain")
    def test_skips_when_no_ats_found(self, mock_discover):
        mock_discover.return_value = (None, None)
        c = NextPlayCollector(probe_ats=True)
        jobs = c._probe_homepages(["unknown.com"])
        assert jobs == []

    @patch("shortlist.collectors.nextplay.discover_ats_from_domain")
    @patch("shortlist.collectors.nextplay.fetch_greenhouse_jobs")
    def test_skips_already_seen_slugs(self, mock_gh, mock_discover):
        mock_discover.return_value = ("greenhouse", "coolstartup")
        c = NextPlayCollector(probe_ats=True)
        c._seen_slugs.add("greenhouse:coolstartup")
        c._probe_homepages(["coolstartup.io"])
        mock_gh.assert_not_called()
