"""Tests for deduplicate_items."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from main import deduplicate_items, _title_words, _content_words


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


class TestContentWords:
    def test_extracts_words(self):
        words = _content_words("Anthropic announced a new partnership with the Department of Defense")
        assert "anthropic" in words
        assert "partnership" in words
        assert "the" not in words

    def test_empty_content(self):
        assert _content_words("") == set()

    def test_truncates_to_500_chars(self):
        long_content = "frontword " + "x " * 500
        words = _content_words(long_content)
        assert "frontword" in words


class TestContentBasedDedup:
    def test_different_titles_overlapping_content_deduped(self):
        """Same story from different sources with different headlines."""
        items = [
            {
                "title": "Defense secretary Pete Hegseth designates Anthropic a supply chain risk",
                "source_type": "rss",
                "content": "Defense Secretary Pete Hegseth has designated Anthropic as a supply chain risk to the Department of War. The decision affects Anthropic's government contracts and raises concerns about AI safety partnerships.",
            },
            {
                "title": "Statement on comments from Secretary of War",
                "source_type": "anthropic_news",
                "content": "Anthropic responds to Secretary Hegseth's designation as a supply chain risk. The Department of War decision impacts government AI contracts and Anthropic's ongoing safety work.",
            },
        ]
        result = deduplicate_items(items)
        assert len(result) == 1
        assert result[0]["source_type"] == "anthropic_news"

    def test_different_titles_different_content_kept(self):
        """Unrelated stories should not be deduped even with minor word overlap."""
        items = [
            {
                "title": "OpenAI launches new GPT model for developers",
                "source_type": "rss",
                "content": "OpenAI today released GPT-5 with improved coding capabilities and a larger context window for developers building applications.",
            },
            {
                "title": "Google reveals Gemini update at conference",
                "source_type": "rss",
                "content": "Google announced major updates to Gemini at their annual developer conference, including multimodal improvements and faster inference.",
            },
        ]
        result = deduplicate_items(items)
        assert len(result) == 2

    def test_no_content_field_falls_back_to_title_only(self):
        """Items without content should still work via title-only dedup."""
        items = [
            {"title": "Anthropic AI Safety Research Update", "source_type": "rss"},
            {"title": "Anthropic AI Safety Research Update", "source_type": "anthropic_news"},
        ]
        result = deduplicate_items(items)
        assert len(result) == 1

    def test_low_title_overlap_skips_content_check(self):
        """Completely different titles should not trigger content check."""
        items = [
            {
                "title": "New breakthrough in quantum computing",
                "source_type": "rss",
                "content": "Anthropic Hegseth supply chain risk Department of War contracts safety",
            },
            {
                "title": "Recipe for chocolate cake",
                "source_type": "rss",
                "content": "Anthropic Hegseth supply chain risk Department of War contracts safety",
            },
        ]
        result = deduplicate_items(items)
        assert len(result) == 2
