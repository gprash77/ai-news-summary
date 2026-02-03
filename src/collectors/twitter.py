"""Twitter/X Collector - Fetches tweets via Nitter RSS proxy."""

import feedparser
import requests
from datetime import datetime, timezone
from dateutil import parser as date_parser
from typing import Optional
import logging
import time

logger = logging.getLogger(__name__)


class TwitterCollector:
    """Collects tweets from X/Twitter via Nitter RSS feeds."""

    def __init__(
        self,
        accounts: list[str],
        nitter_instances: list[str],
        max_age_hours: int = 48
    ):
        self.accounts = accounts
        self.nitter_instances = nitter_instances
        self.max_age_hours = max_age_hours
        self._working_instance = None

    def collect(self) -> list[dict]:
        """Fetch tweets from all configured accounts."""
        tweets = []
        for account in self.accounts:
            try:
                account_tweets = self._fetch_account(account)
                tweets.extend(account_tweets)
                logger.info(f"Fetched {len(account_tweets)} tweets from @{account}")
            except Exception as e:
                logger.error(f"Error fetching @{account}: {e}")
            time.sleep(1)  # Rate limit between accounts
        return tweets

    def _fetch_account(self, account: str) -> list[dict]:
        """Fetch tweets from a single account via Nitter RSS."""
        # Try to find a working Nitter instance
        feed = None
        for instance in self._get_instances_to_try():
            try:
                rss_url = f"https://{instance}/{account}/rss"
                response = requests.get(rss_url, timeout=10)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        self._working_instance = instance
                        break
            except Exception as e:
                logger.debug(f"Instance {instance} failed: {e}")
                continue

        if not feed or not feed.entries:
            logger.warning(f"No working Nitter instance found for @{account}")
            return []

        tweets = []
        for entry in feed.entries:
            published = self._parse_date(entry.get('published'))
            if published and not self._is_recent(published):
                continue

            # Extract tweet content
            content = entry.get('title', '') or entry.get('summary', '')

            tweet = {
                'source_type': 'twitter',
                'source': f"@{account}",
                'title': f"@{account}",
                'url': entry.get('link', '').replace(self._working_instance, 'twitter.com'),
                'content': content[:1000],
                'published': published.isoformat() if published else None,
                'author': account,
            }
            tweets.append(tweet)

        return tweets

    def _get_instances_to_try(self) -> list[str]:
        """Get Nitter instances in order of preference."""
        if self._working_instance:
            # Try the working instance first
            return [self._working_instance] + [
                i for i in self.nitter_instances if i != self._working_instance
            ]
        return self.nitter_instances

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
