"""Tests for deduplicate_items."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from main import deduplicate_items, _title_words


class TestTitleWords:
    def test_extracts_significant_words(self):
        words = _title_words("Defense secretary Pete Hegseth designates Anthropic a supply chain risk")
        assert "anthropic" in words
        assert "hegseth" in words
        assert "a" not in words  # stop word

    def test_empty_title(self):
        assert _title_words("") == set()


class TestDeduplicateItems:
    def test_similar_titles_deduplicated(self):
        items = [
            {"title": "Defense secretary Pete Hegseth designates Anthropic a supply chain risk", "source_type": "rss"},
            {"title": "Statement on the comments from Secretary of War Pete Hegseth", "source_type": "anthropic_news"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 1
        # Should keep anthropic_news (higher priority)
        assert result[0]["source_type"] == "anthropic_news"

    def test_different_stories_kept(self):
        items = [
            {"title": "New GPT-5 model released by OpenAI", "source_type": "rss"},
            {"title": "Anthropic publishes alignment research paper", "source_type": "anthropic_research"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 2

    def test_exact_duplicate_removed(self):
        items = [
            {"title": "Anthropic AI Safety Research", "source_type": "rss"},
            {"title": "Anthropic AI Safety Research", "source_type": "anthropic_news"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 1
        assert result[0]["source_type"] == "anthropic_news"

    def test_empty_list(self):
        assert deduplicate_items([]) == []

    def test_single_item(self):
        items = [{"title": "Some article", "source_type": "rss"}]
        assert deduplicate_items(items) == items

    def test_keeps_lower_priority_when_no_duplicate(self):
        items = [
            {"title": "OpenAI releases new model", "source_type": "rss"},
            {"title": "Google announces Gemini update", "source_type": "rss"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 2
