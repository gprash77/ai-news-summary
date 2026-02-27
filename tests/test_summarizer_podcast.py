"""Tests for generate_podcast_segment(), generate_podcast_script(), and TLDR podcast integration."""

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


class TestGeneratePodcastScript:
    """Tests for GeminiSummarizer.generate_podcast_script() — the stitching step.

    The key regression: with max_output_tokens=2000, 14 segments couldn't fit,
    so TLDR items (appended last as has_summary) were truncated/dropped.
    The fix is direct Python concatenation — no API call, no truncation.
    """

    def _make_summarizer(self):
        from summarizer import GeminiSummarizer
        return GeminiSummarizer(api_key="fake-key")

    def _make_segment(self, title: str, source: str = "TLDR AI") -> dict:
        """Helper: item with a pre-generated podcast_segment."""
        return {
            "title": title,
            "source": source,
            "podcast_segment": f"This is the podcast segment for {title}. It covers the topic in detail for the AI community.",
        }

    def test_empty_items_returns_empty_string(self):
        s = self._make_summarizer()
        assert s.generate_podcast_script([]) == ""

    def test_items_without_segments_returns_empty_string(self):
        s = self._make_summarizer()
        items = [{"title": "No segment", "source": "RSS"}]
        assert s.generate_podcast_script(items) == ""

    def test_all_14_stories_included_regression(self):
        """Regression: 14 items must all appear in the output (was truncated to ~7-8 before fix)."""
        s = self._make_summarizer()
        items = [self._make_segment(f"Story {i}", "YouTube" if i <= 7 else "TLDR AI") for i in range(1, 15)]
        script = s.generate_podcast_script(items)

        for i in range(1, 15):
            assert f"Story {i}" in script, f"Story {i} missing from podcast script"

    def test_tldr_items_at_end_are_included(self):
        """Regression: TLDR items (appended last as has_summary) must appear in script."""
        s = self._make_summarizer()
        # Simulate real ordering: non-TLDR first, TLDR last
        items = [
            self._make_segment("YouTube Video 1", "YouTube"),
            self._make_segment("RSS Article 1", "TechCrunch"),
            self._make_segment("TLDR Article 1", "TLDR AI"),
            self._make_segment("TLDR Article 2", "TLDR AI"),
            self._make_segment("TLDR Article 3", "TLDR AI"),
        ]
        script = s.generate_podcast_script(items)
        assert "TLDR Article 1" in script
        assert "TLDR Article 2" in script
        assert "TLDR Article 3" in script

    def test_script_has_intro_and_outro(self):
        s = self._make_summarizer()
        items = [self._make_segment("Test Story")]
        script = s.generate_podcast_script(items)
        assert "Welcome to AI News Daily" in script
        assert len(script) > 100

    def test_no_api_call_made(self):
        """Script generation must not consume a Gemini API call (quota preservation)."""
        s = self._make_summarizer()
        mock_client = MagicMock()
        s._client = mock_client
        items = [self._make_segment("Story A"), self._make_segment("Story B")]
        s.generate_podcast_script(items)
        mock_client.models.generate_content.assert_not_called()

    def test_segment_text_appears_verbatim(self):
        """Each segment's text must appear in the script unchanged."""
        s = self._make_summarizer()
        unique_text = "unique-canary-phrase-xyz-987"
        items = [{"title": "Test", "source": "TLDR", "podcast_segment": unique_text * 5}]
        script = s.generate_podcast_script(items)
        assert unique_text in script
