"""Tests for generate_podcast_segment() and TLDR podcast integration."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestGeneratePodcastSegment:
    """Tests for GeminiSummarizer.generate_podcast_segment()."""

    def _make_summarizer(self):
        """Create a summarizer with a fake API key (no real calls)."""
        from summarizer import GeminiSummarizer
        return GeminiSummarizer(api_key="fake-key")

    def test_returns_empty_without_api_key(self):
        from summarizer import GeminiSummarizer
        s = GeminiSummarizer(api_key=None)
        # Force no env var
        with patch.dict(os.environ, {}, clear=True):
            s2 = GeminiSummarizer()
            s2.api_key = None
        result = s.generate_podcast_segment({"title": "Test", "tldr": "Summary"})
        assert result == ""

    @patch("summarizer.GEMINI_NEW_SDK", True)
    @patch("summarizer.GEMINI_AVAILABLE", True)
    def test_returns_segment_on_success(self):
        s = self._make_summarizer()
        mock_response = MagicMock()
        mock_response.text = "This is a great podcast segment about AI news that is definitely longer than fifty characters to pass the length check."

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        s._client = mock_client

        result = s.generate_podcast_segment({"title": "Test Article", "tldr": "AI does things", "source": "TLDR"})
        assert len(result) >= 50
        assert "podcast segment" in result.lower()

    @patch("summarizer.GEMINI_NEW_SDK", True)
    @patch("summarizer.GEMINI_AVAILABLE", True)
    def test_uses_tldr_in_prompt(self):
        s = self._make_summarizer()
        mock_response = MagicMock()
        mock_response.text = "A " * 30  # 60 chars, passes length check

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        s._client = mock_client

        s.generate_podcast_segment({"title": "My Title", "tldr": "My unique summary text", "source": "TLDR"})

        call_args = mock_client.models.generate_content.call_args
        prompt = call_args.kwargs.get("contents") or call_args[1].get("contents")
        assert "My unique summary text" in prompt
        assert "My Title" in prompt

    @patch("summarizer.GEMINI_NEW_SDK", True)
    @patch("summarizer.GEMINI_AVAILABLE", True)
    def test_retries_on_short_result(self):
        s = self._make_summarizer()

        short_response = MagicMock()
        short_response.text = "Too short"

        good_response = MagicMock()
        good_response.text = "This is a much longer podcast segment that passes the fifty character minimum length requirement easily."

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [short_response, good_response]
        s._client = mock_client

        result = s.generate_podcast_segment({"title": "Test", "tldr": "Summary"})
        assert len(result) >= 50
        assert mock_client.models.generate_content.call_count == 2

    @patch("summarizer.GEMINI_NEW_SDK", True)
    @patch("summarizer.GEMINI_AVAILABLE", True)
    def test_returns_empty_on_all_failures(self):
        s = self._make_summarizer()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")
        s._client = mock_client

        result = s.generate_podcast_segment({"title": "Test", "tldr": "Summary"})
        assert result == ""

    @patch("summarizer.GEMINI_NEW_SDK", True)
    @patch("summarizer.GEMINI_AVAILABLE", True)
    def test_stops_on_daily_quota_exhausted(self):
        s = self._make_summarizer()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel"
        )
        s._client = mock_client

        result = s.generate_podcast_segment({"title": "Test", "tldr": "Summary"})
        assert result == ""
        # Should only try once, not retry on daily quota
        assert mock_client.models.generate_content.call_count == 1


class TestSummarizeItemsIntegration:
    """Test that main.py's summarize_items() generates podcast segments for TLDR items."""

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key"})
    @patch("summarizer.time.sleep")  # Skip sleeps in tests
    @patch("summarizer.GEMINI_NEW_SDK", True)
    @patch("summarizer.GEMINI_AVAILABLE", True)
    def test_tldr_items_get_podcast_segments(self, _mock_sleep):
        """Items with pre-existing tldr should get podcast_segment via generate_podcast_segment."""
        from summarizer import GeminiSummarizer

        items = [
            # Pre-summarized TLDR item (no podcast_segment)
            {"title": "TLDR Article 1", "tldr": "Pre-existing summary", "source": "TLDR", "source_type": "newsletter", "content": "stuff"},
            {"title": "TLDR Article 2", "tldr": "Another summary", "source": "TLDR", "source_type": "newsletter", "content": "stuff"},
            # Regular item that needs full summarization
            {"title": "RSS Article", "source": "Verge", "source_type": "rss", "content": "Some content about AI"},
        ]

        mock_response = MagicMock()
        mock_response.text = "TLDR: A great summary of the content.\n\nPODCAST: This is a wonderful podcast segment about the latest developments in artificial intelligence and what they mean."

        mock_podcast_response = MagicMock()
        mock_podcast_response.text = "Here is a generated podcast segment that is definitely long enough to pass the fifty character minimum length check easily."

        mock_client = MagicMock()
        # First call: summarize_item for RSS article, then 2 calls for TLDR podcast segments
        mock_client.models.generate_content.side_effect = [
            mock_response,          # summarize_item for RSS
            mock_podcast_response,  # generate_podcast_segment for TLDR 1
            mock_podcast_response,  # generate_podcast_segment for TLDR 2
        ]

        with patch.object(GeminiSummarizer, '_get_client', return_value=mock_client):
            with patch.object(GeminiSummarizer, 'generate_daily_summary', return_value="Daily summary"):
                from main import summarize_items
                config = {"gemini": {"model": "gemini-2.5-flash-lite"}}
                result_items, daily = summarize_items(items, config)

        # All items should now have podcast_segment
        for item in result_items:
            assert item.get('podcast_segment'), f"Item '{item['title']}' missing podcast_segment, got: {repr(item.get('podcast_segment'))}"

        # Verify the API was called 3 times total (1 summarize + 2 podcast segments)
        assert mock_client.models.generate_content.call_count == 3
