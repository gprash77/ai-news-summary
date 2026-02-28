"""Tests for _select_balanced_items including Anthropic source types."""
from unittest.mock import patch
from src.summarizer import GeminiSummarizer


def _make_item(source_type, title="Test"):
    return {"source_type": source_type, "title": title, "url": "http://example.com"}


def _make_summarizer():
    return GeminiSummarizer(api_key="")


class TestSelectBalancedItems:
    def test_anthropic_news_included(self):
        s = _make_summarizer()
        items = [_make_item("anthropic_news", f"news-{i}") for i in range(3)]
        selected = s._select_balanced_items(items)
        assert len(selected) == 2
        assert all(i["source_type"] == "anthropic_news" for i in selected)

    def test_anthropic_research_included(self):
        s = _make_summarizer()
        items = [_make_item("anthropic_research", f"research-{i}") for i in range(3)]
        selected = s._select_balanced_items(items)
        assert len(selected) == 2
        assert all(i["source_type"] == "anthropic_research" for i in selected)

    def test_full_mix_all_sources(self):
        s = _make_summarizer()
        items = (
            [_make_item("youtube")] * 3
            + [_make_item("newsletter")] * 4
            + [_make_item("rss")] * 2
            + [_make_item("twitter")] * 2
            + [_make_item("anthropic_news")] * 3
            + [_make_item("anthropic_research")] * 3
        )
        selected = s._select_balanced_items(items)
        types = [i["source_type"] for i in selected]
        assert types.count("youtube") == 2
        assert types.count("newsletter") == 3
        assert types.count("rss") == 1
        assert types.count("twitter") == 1
        assert types.count("anthropic_news") == 2
        assert types.count("anthropic_research") == 2
        assert len(selected) == 11

    def test_no_anthropic_still_works(self):
        s = _make_summarizer()
        items = [_make_item("youtube")] * 3 + [_make_item("rss")] * 2
        selected = s._select_balanced_items(items)
        types = [i["source_type"] for i in selected]
        assert types.count("youtube") == 2
        assert types.count("rss") == 1
        assert len(selected) == 3
