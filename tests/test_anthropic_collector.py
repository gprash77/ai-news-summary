"""Tests for AnthropicCollector - news and research scraping."""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from collectors.anthropic import AnthropicCollector


def make_listing_html(prefix, slugs):
    """Build a minimal listing page with links."""
    links = ''.join(f'<a href="{prefix}{s}">Article</a>' for s in slugs)
    return f"<html><body>{links}</body></html>"


def make_article_html(title, date_iso=None, content="Some article content", use_jsonld=False):
    """Build a minimal article page."""
    meta = ""
    if date_iso and not use_jsonld:
        meta = f'<time datetime="{date_iso}">date</time>'
    jsonld = ""
    if date_iso and use_jsonld:
        jsonld = f'<script type="application/ld+json">{json.dumps({"publishedOn": date_iso})}</script>'
    return f"""<html><head>
        <meta property="og:title" content="{title}"/>
        {jsonld}
    </head><body><main>{meta}<p>{content}</p></main></body></html>"""


def make_mock_session(get_side_effect):
    mock_session = MagicMock()
    mock_session.get.side_effect = get_side_effect
    return mock_session


class TestAnthropicCollector:
    def test_collects_from_both_news_and_research(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url.endswith("/news"):
                resp.text = make_listing_html("/news/", ["article-1"])
            elif url.endswith("/research"):
                resp.text = make_listing_html("/research/", ["paper-1"])
            elif "/news/article-1" in url:
                resp.text = make_article_html("News Article", recent)
            elif "/research/paper-1" in url:
                resp.text = make_article_html("Research Paper", recent, use_jsonld=True)
            return resp

        collector = AnthropicCollector(max_articles=2, max_research=2, max_age_hours=72)
        collector.session = make_mock_session(mock_get)

        results = collector.collect()
        assert len(results) == 2
        sources = {r["source"] for r in results}
        assert "Anthropic News" in sources
        assert "Anthropic Research" in sources

    def test_skips_old_articles(self):
        old_date = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url.endswith("/news"):
                resp.text = make_listing_html("/news/", ["old-article"])
            elif url.endswith("/research"):
                resp.text = make_listing_html("/research/", [])
            elif "/news/old-article" in url:
                resp.text = make_article_html("Old News", old_date)
            return resp

        collector = AnthropicCollector(max_articles=2, max_research=2, max_age_hours=72)
        collector.session = make_mock_session(mock_get)

        results = collector.collect()
        assert len(results) == 0

    def test_jsonld_date_parsing(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url.endswith("/news"):
                resp.text = make_listing_html("/news/", [])
            elif url.endswith("/research"):
                resp.text = make_listing_html("/research/", ["paper-1"])
            elif "/research/paper-1" in url:
                resp.text = make_article_html("Paper", recent, use_jsonld=True)
            return resp

        collector = AnthropicCollector(max_articles=2, max_research=2, max_age_hours=72)
        collector.session = make_mock_session(mock_get)

        results = collector.collect()
        assert len(results) == 1
        assert results[0]["published"] is not None

    def test_respects_max_limits(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url.endswith("/news"):
                resp.text = make_listing_html("/news/", ["a1", "a2", "a3", "a4"])
            elif url.endswith("/research"):
                resp.text = make_listing_html("/research/", ["r1", "r2", "r3", "r4"])
            else:
                resp.text = make_article_html("Article", recent)
            return resp

        collector = AnthropicCollector(max_articles=2, max_research=2, max_age_hours=72)
        collector.session = make_mock_session(mock_get)

        results = collector.collect()
        assert len(results) <= 4
