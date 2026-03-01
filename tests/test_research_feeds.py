"""Tests for diversified research sources and podcast improvements."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from main import collect_all, deduplicate_items, summarize_items
from summarizer import GeminiSummarizer


def _make_item(source_type, title="Test", url="http://example.com", podcast_segment=""):
    item = {"source_type": source_type, "title": title, "url": url, "content": "Some AI content"}
    if podcast_segment:
        item["podcast_segment"] = podcast_segment
    return item


class TestResearchFeedCollection:
    """Test that research feeds are collected with correct source_type."""

    @patch('main.AnthropicCollector')
    def test_openai_feed_gets_openai_research_type(self, MockAnthropicCollector):
        """Items from OpenAI RSS should get source_type='openai_research'."""
        MockAnthropicCollector.return_value.collect.return_value = []
        config = {
            'sources': {
                'research_feeds': {
                    'enabled': True,
                    'max_items_per_feed': 1,
                    'feeds': ['https://openai.com/blog/rss.xml'],
                },
                'anthropic': {'enabled': False},
            },
            'filters': {'max_age_hours': 168},
        }
        fake_item = {
            'source_type': 'rss', 'source': 'OpenAI Blog',
            'title': 'New Research', 'url': 'https://openai.com/research/foo',
            'content': 'Content', 'published': None, 'author': '',
        }
        with patch('main.RSSCollector') as MockRSS:
            instance = MockRSS.return_value
            instance.collect.return_value = [fake_item]
            items = collect_all(config)

        assert len(items) == 1
        assert items[0]['source_type'] == 'openai_research'

    @patch('main.AnthropicCollector')
    def test_google_feed_gets_google_research_type(self, MockAnthropicCollector):
        """Items from Google AI blog should get source_type='google_research'."""
        MockAnthropicCollector.return_value.collect.return_value = []
        config = {
            'sources': {
                'research_feeds': {
                    'enabled': True,
                    'max_items_per_feed': 1,
                    'feeds': ['https://blog.google/technology/ai/rss/'],
                },
                'anthropic': {'enabled': False},
            },
            'filters': {'max_age_hours': 168},
        }
        fake_item = {
            'source_type': 'rss', 'source': 'Google AI Blog',
            'title': 'Gemini Update', 'url': 'https://blog.google/ai/foo',
            'content': 'Content', 'published': None, 'author': '',
        }
        with patch('main.RSSCollector') as MockRSS:
            instance = MockRSS.return_value
            instance.collect.return_value = [fake_item]
            items = collect_all(config)

        assert len(items) == 1
        assert items[0]['source_type'] == 'google_research'

    @patch('main.AnthropicCollector')
    def test_research_feeds_disabled_skipped(self, MockAnthropicCollector):
        """Research feeds with enabled=false should be skipped."""
        MockAnthropicCollector.return_value.collect.return_value = []
        config = {
            'sources': {
                'research_feeds': {
                    'enabled': False,
                    'feeds': ['https://openai.com/blog/rss.xml'],
                },
                'anthropic': {'enabled': False},
            },
            'filters': {'max_age_hours': 168},
        }
        with patch('main.RSSCollector') as MockRSS:
            items = collect_all(config)
            MockRSS.assert_not_called()
        assert items == []


class TestDeduplicationWithResearch:
    """Test that new research source types have correct dedup priority."""

    def test_openai_research_priority_over_rss(self):
        items = [
            {"title": "GPT-5 released by OpenAI today", "source_type": "rss"},
            {"title": "GPT-5 released by OpenAI today", "source_type": "openai_research"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 1
        assert result[0]["source_type"] == "openai_research"

    def test_google_research_priority_over_rss(self):
        items = [
            {"title": "Gemini 3 model announced by Google", "source_type": "rss"},
            {"title": "Gemini 3 model announced by Google", "source_type": "google_research"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 1
        assert result[0]["source_type"] == "google_research"


class TestYouTubeCalloutInPodcast:
    """Test that YouTube items get a video callout in the podcast script."""

    def test_youtube_item_has_callout(self):
        items = [
            _make_item("youtube", "AI Explained Video", podcast_segment="This is the segment about AI."),
            _make_item("rss", "RSS Article", podcast_segment="This is an RSS segment."),
        ]
        s = GeminiSummarizer(api_key="")
        script = s.generate_podcast_script(items)
        assert "YouTube" in script or "youtube" in script.lower()
        assert "watch" in script.lower() or "video" in script.lower()

    def test_non_youtube_no_callout(self):
        items = [
            _make_item("rss", "RSS Article", podcast_segment="This is an RSS segment."),
        ]
        s = GeminiSummarizer(api_key="")
        script = s.generate_podcast_script(items)
        assert "YouTube" not in script


class TestResearchPodcastSegments:
    """Test that all research items always get podcast segments."""

    def test_research_items_get_podcast_segments(self):
        """Research items without podcast_segment should get one generated."""
        items = [
            _make_item("anthropic_research", "Anthropic Paper"),
            _make_item("openai_research", "OpenAI Paper"),
            _make_item("google_research", "Google Paper"),
        ]
        # Give them tldrs but no podcast segments
        for item in items:
            item['tldr'] = "This is a research paper summary."

        config = {'gemini': {'model': 'gemini-2.5-flash-lite', 'max_tokens': 1024}}

        with patch.object(GeminiSummarizer, 'summarize_item', return_value=("Summary", "Podcast text")):
            with patch.object(GeminiSummarizer, 'generate_podcast_segment', return_value="Generated podcast segment"):
                with patch.object(GeminiSummarizer, 'generate_daily_summary', return_value="Daily summary"):
                    result_items, _ = summarize_items(items, config)

        research_types = {'anthropic_research', 'openai_research', 'google_research'}
        for item in result_items:
            if item['source_type'] in research_types:
                assert item.get('podcast_segment'), f"{item['source_type']} missing podcast_segment"


class TestBalancedSelectionWithResearch:
    """Test _select_balanced_items includes new research types."""

    def test_includes_openai_and_google_research(self):
        s = GeminiSummarizer(api_key="")
        items = (
            [_make_item("youtube")] * 3
            + [_make_item("newsletter")] * 4
            + [_make_item("rss")] * 2
            + [_make_item("twitter")] * 2
            + [_make_item("anthropic_news")] * 3
            + [_make_item("anthropic_research")] * 3
            + [_make_item("openai_research")] * 2
            + [_make_item("google_research")] * 2
        )
        selected = s._select_balanced_items(items)
        types = [i["source_type"] for i in selected]
        assert types.count("openai_research") == 1
        assert types.count("google_research") == 1

    def test_reduced_anthropic_counts(self):
        s = GeminiSummarizer(api_key="")
        items = (
            [_make_item("anthropic_news")] * 3
            + [_make_item("anthropic_research")] * 3
            + [_make_item("openai_research")] * 2
            + [_make_item("google_research")] * 2
        )
        selected = s._select_balanced_items(items)
        types = [i["source_type"] for i in selected]
        assert types.count("anthropic_news") == 1
        assert types.count("anthropic_research") == 1

    def test_works_without_new_research(self):
        """Should still work when no OpenAI/Google research items exist."""
        s = GeminiSummarizer(api_key="")
        items = [_make_item("youtube")] * 3 + [_make_item("rss")] * 2
        selected = s._select_balanced_items(items)
        assert len(selected) >= 2
