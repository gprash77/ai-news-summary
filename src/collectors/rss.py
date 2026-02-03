"""RSS Feed Collector - Fetches articles from RSS feeds."""

import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from dateutil import parser as date_parser
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class RSSCollector:
    """Collects articles from RSS feeds."""

    def __init__(self, feeds: list[str], max_age_hours: int = 48, max_items_per_feed: int = 2):
        self.feeds = feeds
        self.max_age_hours = max_age_hours
        self.max_items_per_feed = max_items_per_feed

    def collect(self) -> list[dict]:
        """Fetch articles from all configured RSS feeds."""
        articles = []
        for feed_url in self.feeds:
            try:
                feed_articles = self._fetch_feed(feed_url)
                articles.extend(feed_articles)
                logger.info(f"Fetched {len(feed_articles)} articles from {feed_url}")
            except Exception as e:
                logger.error(f"Error fetching {feed_url}: {e}")
        return articles

    def _fetch_feed(self, feed_url: str) -> list[dict]:
        """Fetch and parse a single RSS feed."""
        feed = feedparser.parse(feed_url)
        articles = []

        for entry in feed.entries:
            # Stop if we have enough items from this feed
            if len(articles) >= self.max_items_per_feed:
                break

            published = self._parse_date(entry.get('published') or entry.get('updated'))
            if published and not self._is_recent(published):
                continue

            # Extract content, preferring full content over summary
            content = self._extract_content(entry)

            article = {
                'source_type': 'rss',
                'source': feed.feed.get('title', feed_url),
                'title': entry.get('title', 'No title'),
                'url': entry.get('link', ''),
                'content': content,
                'published': published.isoformat() if published else None,
                'author': entry.get('author', ''),
            }
            articles.append(article)

        return articles

    def _extract_content(self, entry) -> str:
        """Extract and clean content from feed entry."""
        # Try content first, then summary
        content = ''
        if 'content' in entry and entry.content:
            content = entry.content[0].get('value', '')
        elif 'summary' in entry:
            content = entry.summary

        # Strip HTML tags
        if content:
            soup = BeautifulSoup(content, 'lxml')
            content = soup.get_text(separator=' ', strip=True)

        return content[:2000]  # Limit content length

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None
        try:
            dt = date_parser.parse(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _is_recent(self, dt: datetime) -> bool:
        """Check if datetime is within max_age_hours."""
        now = datetime.now(timezone.utc)
        age = now - dt
        return age.total_seconds() < (self.max_age_hours * 3600)
