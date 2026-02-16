"""Twitter/X Collector - Fetches tweets via Syndication API and Nitter RSS."""

import random
import re
import requests
from datetime import datetime, timezone
from dateutil import parser as date_parser
from typing import Optional
import logging
import time

import feedparser

logger = logging.getLogger(__name__)

SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"


class TwitterCollector:
    """Collects tweets from X/Twitter via Syndication API (by tweet URL/ID)
    and optionally via Nitter RSS (by account handle)."""

    def __init__(
        self,
        tweet_urls: list[str] = None,
        accounts: list[str] = None,
        nitter_instances: list[str] = None,
        max_age_hours: int = 48,
        accounts_per_day: int = 5
    ):
        self.tweet_urls = tweet_urls or []
        self.accounts = accounts or []
        self.nitter_instances = nitter_instances or []
        self.max_age_hours = max_age_hours
        self.accounts_per_day = accounts_per_day
        self._working_instance = None
        self._all_instances_down = False

    def collect(self) -> list[dict]:
        """Fetch tweets from configured URLs/IDs and accounts."""
        tweets = []

        # 1) Fetch individual tweets via Syndication API
        for url_or_id in self.tweet_urls:
            tweet_id = self._extract_tweet_id(url_or_id)
            if not tweet_id:
                logger.warning(f"Could not extract tweet ID from: {url_or_id}")
                continue
            try:
                tweet = self._fetch_tweet_by_id(tweet_id, url_or_id)
                if tweet:
                    tweets.append(tweet)
                    logger.info(f"Fetched tweet {tweet_id} via Syndication API")
            except Exception as e:
                logger.error(f"Error fetching tweet {tweet_id}: {e}")
            time.sleep(0.3)

        # 2) Fetch account timelines via Nitter RSS (fallback/legacy)
        if self.accounts and self.nitter_instances:
            nitter_tweets = self._collect_via_nitter()
            tweets.extend(nitter_tweets)

        return tweets

    # ── Syndication API ──────────────────────────────────────────────

    @staticmethod
    def _extract_tweet_id(url_or_id: str) -> Optional[str]:
        """Extract numeric tweet ID from a URL or bare ID string."""
        url_or_id = url_or_id.strip()
        # Bare numeric ID
        if url_or_id.isdigit():
            return url_or_id
        # URL patterns: twitter.com/user/status/ID or x.com/user/status/ID
        match = re.search(r'(?:twitter\.com|x\.com)/\w+/status/(\d+)', url_or_id)
        if match:
            return match.group(1)
        return None

    def _fetch_tweet_by_id(self, tweet_id: str, original_url: str = None) -> Optional[dict]:
        """Fetch a single tweet via the Syndication API."""
        token = random.randint(1, 999999)
        try:
            resp = requests.get(
                SYNDICATION_URL,
                params={"id": tweet_id, "token": str(token)},
                timeout=(5, 10)
            )
            if resp.status_code == 404:
                logger.warning(f"Tweet {tweet_id} not found (deleted or private)")
                return None
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Syndication API request failed for {tweet_id}: {e}")
            return None
        except ValueError:
            logger.error(f"Invalid JSON response for tweet {tweet_id}")
            return None

        text = data.get("text", "")
        if not text:
            return None

        user = data.get("user", {})
        screen_name = user.get("screen_name", "unknown")
        display_name = user.get("name", screen_name)

        # Parse created_at
        published = self._parse_date(data.get("created_at"))
        if published and not self._is_recent(published):
            logger.debug(f"Tweet {tweet_id} is too old, skipping")
            return None

        # Build canonical tweet URL
        if original_url and original_url.strip().isdigit():
            # Bare ID was passed — construct the URL
            tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}"
        else:
            tweet_url = original_url or f"https://x.com/{screen_name}/status/{tweet_id}"
        # Normalize to x.com
        tweet_url = tweet_url.replace("twitter.com", "x.com")

        # Extract media descriptions if available
        media_texts = []
        for photo in data.get("photos", []):
            alt = photo.get("alt_text")
            if alt:
                media_texts.append(f"[Image: {alt}]")
        for video in data.get("video", {}).get("variants", []):
            media_texts.append("[Video attached]")
            break  # only note once

        content_parts = [text] + media_texts
        content = "\n".join(content_parts)

        return {
            "source_type": "twitter",
            "source": f"@{screen_name}",
            "title": f"@{screen_name} ({display_name})",
            "url": tweet_url,
            "content": content[:1000],
            "published": published.isoformat() if published else None,
            "author": screen_name,
        }

    # ── Nitter RSS (legacy) ──────────────────────────────────────────

    def _collect_via_nitter(self) -> list[dict]:
        """Fetch tweets from accounts via Nitter RSS."""
        if self._all_instances_down:
            logger.info("Skipping Nitter - all instances previously failed")
            return []

        tweets = []
        failed_accounts = 0
        for account in self.accounts:
            try:
                account_tweets = self._fetch_account(account)
                tweets.extend(account_tweets)
                logger.info(f"Fetched {len(account_tweets)} tweets from @{account}")
                if not account_tweets:
                    failed_accounts += 1
            except Exception as e:
                logger.error(f"Error fetching @{account}: {e}")
                failed_accounts += 1

            if failed_accounts >= 2 and not self._working_instance:
                logger.warning("Multiple accounts failed - Nitter appears to be down, skipping remaining")
                self._all_instances_down = True
                break

            time.sleep(0.5)
        return tweets

    def _fetch_account(self, account: str) -> list[dict]:
        """Fetch tweets from a single account via Nitter RSS."""
        feed = None
        instances = self._get_instances_to_try()[:3]

        for instance in instances:
            try:
                rss_url = f"https://{instance}/{account}/rss"
                response = requests.get(rss_url, timeout=(3, 5))
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        self._working_instance = instance
                        break
            except requests.exceptions.Timeout:
                logger.debug(f"Instance {instance} timed out")
                continue
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

            content = entry.get('title', '') or entry.get('summary', '')

            tweet = {
                'source_type': 'twitter',
                'source': f"@{account}",
                'title': f"@{account}",
                'url': entry.get('link', '').replace(self._working_instance, 'x.com'),
                'content': content[:1000],
                'published': published.isoformat() if published else None,
                'author': account,
            }
            tweets.append(tweet)

        return tweets

    def _get_instances_to_try(self) -> list[str]:
        """Get Nitter instances in order of preference."""
        if self._working_instance:
            return [self._working_instance] + [
                i for i in self.nitter_instances if i != self._working_instance
            ]
        return self.nitter_instances

    # ── Utilities ────────────────────────────────────────────────────

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
