"""Track previously seen articles to avoid cross-day duplicates."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class SeenArticles:
    """Tracks article URLs that have already been included in a digest."""

    def __init__(self, path: Union[str, Path] = None, retention_days: int = 14):
        if path is None:
            path = Path(__file__).parent.parent / 'seen_articles.json'
        self.path = Path(path)
        self.retention_days = retention_days
        self._seen: dict[str, str] = {}  # url -> date_seen (ISO format)
        self._load()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent comparison."""
        return url.rstrip('/')

    def _load(self):
        """Load seen articles from disk and prune old entries."""
        if not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text())
            cutoff = datetime.now() - timedelta(days=self.retention_days)
            for url, date_str in data.items():
                try:
                    seen_date = datetime.fromisoformat(date_str)
                    if seen_date > cutoff:
                        self._seen[self._normalize_url(url)] = date_str
                except (ValueError, TypeError):
                    pass
            pruned = len(data) - len(self._seen)
            if pruned > 0:
                logger.info(f"Pruned {pruned} old entries from seen articles")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load seen articles: {e}")

    def is_seen(self, url: str) -> bool:
        """Check if a URL has been seen before."""
        return self._normalize_url(url) in self._seen

    def mark_seen(self, urls: list[str]):
        """Mark URLs as seen with current timestamp."""
        now = datetime.now().isoformat()
        for url in urls:
            normalized = self._normalize_url(url)
            if normalized not in self._seen:
                self._seen[normalized] = now

    def filter_unseen(self, items: list[dict]) -> list[dict]:
        """Filter out items that have been seen before. Items without URLs are kept."""
        unseen = []
        seen_count = 0
        for item in items:
            url = item.get('url', '')
            if url and self.is_seen(url):
                logger.info(f"Skipping previously seen: {item.get('title', '')[:60]}")
                seen_count += 1
            else:
                unseen.append(item)
        if seen_count:
            logger.info(f"Filtered {seen_count} previously seen articles")
        return unseen

    def save(self):
        """Save seen articles to disk."""
        self.path.write_text(json.dumps(self._seen, indent=2))
        logger.info(f"Saved {len(self._seen)} seen article URLs")
