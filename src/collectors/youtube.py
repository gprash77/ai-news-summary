"""YouTube Collector - Fetches videos from YouTube channels."""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Optional imports - gracefully handle if not installed
try:
    from googleapiclient.discovery import build
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    TRANSCRIPT_API_AVAILABLE = False


class YouTubeCollector:
    """Collects videos from YouTube channels via YouTube Data API."""

    def __init__(
        self,
        channels: list[str],
        max_videos_per_channel: int = 3,
        fetch_transcripts: bool = True,
        max_age_hours: int = 48,
        api_key: Optional[str] = None
    ):
        self.channels = channels
        self.max_videos = max_videos_per_channel
        self.fetch_transcripts = fetch_transcripts and TRANSCRIPT_API_AVAILABLE
        self.max_age_hours = max_age_hours
        self.api_key = api_key or os.environ.get('YOUTUBE_API_KEY')
        self._youtube = None

    def _get_youtube_client(self):
        """Get or create YouTube API client."""
        if not YOUTUBE_API_AVAILABLE:
            raise RuntimeError("google-api-python-client not installed")
        if not self.api_key:
            raise ValueError("YouTube API key not configured")
        if not self._youtube:
            self._youtube = build('youtube', 'v3', developerKey=self.api_key)
        return self._youtube

    def collect(self) -> list[dict]:
        """Fetch videos from all configured channels."""
        if not self.channels:
            logger.info("No YouTube channels configured")
            return []

        if not self.api_key:
            logger.warning("YouTube API key not set - skipping YouTube collection")
            return []

        videos = []
        for channel_id in self.channels:
            try:
                channel_videos = self._fetch_channel(channel_id)
                videos.extend(channel_videos)
                logger.info(f"Fetched {len(channel_videos)} videos from channel {channel_id}")
            except Exception as e:
                logger.error(f"Error fetching channel {channel_id}: {e}")
        return videos

    def _fetch_channel(self, channel_identifier: str) -> list[dict]:
        """Fetch recent videos from a single channel.

        Args:
            channel_identifier: Either a channel ID (UCxxx) or handle (@username)
        """
        youtube = self._get_youtube_client()

        # Determine if this is a handle or channel ID
        if channel_identifier.startswith('@'):
            # Look up by handle
            channel_response = youtube.channels().list(
                part='contentDetails,snippet',
                forHandle=channel_identifier[1:]  # Remove @ prefix
            ).execute()
        else:
            # Look up by channel ID
            channel_response = youtube.channels().list(
                part='contentDetails,snippet',
                id=channel_identifier
            ).execute()

        if not channel_response.get('items'):
            logger.warning(f"Channel {channel_identifier} not found")
            return []

        channel_info = channel_response['items'][0]
        channel_name = channel_info['snippet']['title']
        uploads_playlist = channel_info['contentDetails']['relatedPlaylists']['uploads']

        # Get recent videos from uploads playlist
        playlist_response = youtube.playlistItems().list(
            part='snippet,contentDetails',
            playlistId=uploads_playlist,
            maxResults=self.max_videos
        ).execute()

        videos = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

        for item in playlist_response.get('items', []):
            snippet = item['snippet']
            video_id = snippet['resourceId']['videoId']

            # Parse publish date
            published_str = snippet.get('publishedAt')
            if published_str:
                published = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
                if published < cutoff:
                    continue
            else:
                published = None

            # Get video content: prefer transcript > full description > title fallback
            content = None

            if self.fetch_transcripts:
                transcript = self._get_transcript(video_id)
                if transcript:
                    content = transcript[:2000]

            if not content:
                # Fetch full description via videos endpoint (playlistItems can truncate)
                description = self._get_full_description(youtube, video_id)
                if not description:
                    description = snippet.get('description', '')

                if self._is_low_quality_description(description):
                    title = snippet.get('title', 'No title')
                    content = f"Video titled: {title}. No meaningful description or transcript available."
                else:
                    content = description[:500]

            video = {
                'source_type': 'youtube',
                'source': channel_name,
                'title': snippet.get('title', 'No title'),
                'url': f"https://youtube.com/watch?v={video_id}",
                'content': content,
                'published': published.isoformat() if published else None,
                'author': channel_name,
                'video_id': video_id,
            }
            videos.append(video)

        return videos

    def _get_full_description(self, youtube, video_id: str) -> Optional[str]:
        """Fetch the full, untruncated video description via the videos endpoint."""
        try:
            response = youtube.videos().list(
                part='snippet',
                id=video_id
            ).execute()
            items = response.get('items', [])
            if items:
                return items[0]['snippet'].get('description', '')
        except Exception as e:
            logger.debug(f"Could not fetch full description for {video_id}: {e}")
        return None

    def _is_low_quality_description(self, description: str) -> bool:
        """Detect bio/profile descriptions that won't produce useful summaries."""
        if not description or len(description.strip()) < 30:
            return True

        text = description.lower()
        boilerplate_signals = [
            'subscribe', 'follow me on', 'follow us on', 'check out my',
            'patreon.com', 'twitter.com', 'instagram.com', 'discord.gg',
            'business inquiries', 'contact:', 'merch:', '#shorts',
        ]
        lines = [l.strip() for l in description.strip().splitlines() if l.strip()]
        if not lines:
            return True

        # Count lines that are mostly links or boilerplate
        low_quality_lines = 0
        for line in lines:
            lower = line.lower()
            is_link = lower.startswith('http') or lower.startswith('www.')
            is_boilerplate = any(signal in lower for signal in boilerplate_signals)
            if is_link or is_boilerplate:
                low_quality_lines += 1

        # If more than 60% of lines are links/boilerplate, it's low-quality
        return low_quality_lines / len(lines) > 0.6

    def _get_transcript(self, video_id: str) -> Optional[str]:
        """Fetch video transcript if available."""
        if not TRANSCRIPT_API_AVAILABLE:
            return None

        try:
            api = YouTubeTranscriptApi()
            # Try default language first, then auto-generated English
            for lang in [None, ['en'], ['en-US']]:
                try:
                    if lang is None:
                        transcript_list = api.fetch(video_id)
                    else:
                        transcript_list = api.fetch(video_id, languages=lang)
                    full_text = ' '.join(segment.text for segment in transcript_list)
                    return full_text
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Could not fetch transcript for {video_id}: {e}")
        return None
