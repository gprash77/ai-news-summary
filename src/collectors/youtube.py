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

            # Get video description and optionally transcript
            content = snippet.get('description', '')[:500]

            if self.fetch_transcripts:
                transcript = self._get_transcript(video_id)
                if transcript:
                    content = transcript[:2000]

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

    def _get_transcript(self, video_id: str) -> Optional[str]:
        """Fetch video transcript if available."""
        if not TRANSCRIPT_API_AVAILABLE:
            return None

        try:
            # New API uses instance.fetch() method
            api = YouTubeTranscriptApi()
            transcript_list = api.fetch(video_id)
            # Combine transcript segments
            full_text = ' '.join(segment.text for segment in transcript_list)
            return full_text
        except Exception as e:
            logger.debug(f"Could not fetch transcript for {video_id}: {e}")
            return None
