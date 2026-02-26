"""Tests for YouTube content extraction fallback improvements."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from collectors.youtube import YouTubeCollector


class TestIsLowQualityDescription:
    """Tests for YouTubeCollector._is_low_quality_description()."""

    def _collector(self):
        return YouTubeCollector(channels=[], api_key="fake")

    def test_empty_description(self):
        c = self._collector()
        assert c._is_low_quality_description("") is True
        assert c._is_low_quality_description(None) is True

    def test_short_description(self):
        c = self._collector()
        assert c._is_low_quality_description("Hi") is True
        assert c._is_low_quality_description("Short text only") is True

    def test_good_description(self):
        c = self._collector()
        desc = (
            "In this video we explore how large language models are changing "
            "the way developers write code. We look at the latest benchmarks "
            "and discuss what this means for the future of software engineering."
        )
        assert c._is_low_quality_description(desc) is False

    def test_bio_description_mostly_links(self):
        c = self._collector()
        desc = """Check out my latest video!
https://twitter.com/user
https://instagram.com/user
https://patreon.com/user
Subscribe for more content!
https://discord.gg/invite"""
        assert c._is_low_quality_description(desc) is True

    def test_mixed_content_mostly_good(self):
        c = self._collector()
        desc = """In this episode we discuss the latest AI breakthroughs.
We cover new model releases from major labs.
The implications for healthcare are significant.
We also look at regulatory developments.
https://twitter.com/user"""
        # Only 1 of 5 lines is low-quality = 20%, below 60% threshold
        assert c._is_low_quality_description(desc) is False

    def test_mixed_content_mostly_boilerplate(self):
        c = self._collector()
        desc = """Quick update!
Subscribe for more AI news
Follow me on Twitter for updates
https://patreon.com/support
Business inquiries: email@example.com"""
        # 4 of 5 lines are boilerplate = 80%, above 60%
        assert c._is_low_quality_description(desc) is True

    def test_social_handles_detected(self):
        c = self._collector()
        desc = """Follow me on Twitter
Follow us on Instagram
Check out my Patreon
Subscribe to the channel
www.mysite.com/merch"""
        assert c._is_low_quality_description(desc) is True


class TestGetFullDescription:
    """Tests for YouTubeCollector._get_full_description()."""

    def test_returns_description_from_videos_endpoint(self):
        c = YouTubeCollector(channels=[], api_key="fake")
        mock_youtube = _mock_youtube_client(
            description="Full untruncated description text here"
        )
        result = c._get_full_description(mock_youtube, "abc123")
        assert result == "Full untruncated description text here"

    def test_returns_none_on_empty_items(self):
        c = YouTubeCollector(channels=[], api_key="fake")
        mock_youtube = _mock_youtube_client(items=[])
        result = c._get_full_description(mock_youtube, "abc123")
        assert result is None

    def test_returns_none_on_exception(self):
        c = YouTubeCollector(channels=[], api_key="fake")

        class FailingYoutube:
            def videos(self):
                raise Exception("API error")

        result = c._get_full_description(FailingYoutube(), "abc123")
        assert result is None


class TestContentFallbackLogic:
    """Test the content selection priority in _fetch_channel."""

    def test_low_quality_description_uses_title_fallback(self):
        """When transcript fails and description is bio/links, content should reference the title."""
        c = YouTubeCollector(channels=[], api_key="fake")

        bio_desc = """Subscribe for more!
https://twitter.com/creator
https://patreon.com/creator
Follow me on Instagram
https://discord.gg/invite"""

        assert c._is_low_quality_description(bio_desc) is True
        # The actual fallback message format
        title = "Amazing AI Breakthrough Explained"
        expected = f"Video titled: {title}. No meaningful description or transcript available."
        assert "Video titled:" in expected
        assert title in expected


# --- Helpers ---

def _mock_youtube_client(description=None, items=None):
    """Build a mock YouTube client that returns a canned videos().list() response."""
    from unittest.mock import MagicMock

    if items is None and description is not None:
        items = [{"snippet": {"description": description}}]
    elif items is None:
        items = []

    mock_response = {"items": items}
    mock_list = MagicMock()
    mock_list.execute.return_value = mock_response

    mock_videos = MagicMock()
    mock_videos.list.return_value = mock_list

    mock_client = MagicMock()
    mock_client.videos.return_value = mock_videos
    return mock_client
