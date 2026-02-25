"""Anthropic News Collector - Scrapes anthropic.com/news (no RSS feed available)."""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

BASE_URL = "https://www.anthropic.com"
NEWS_URL = f"{BASE_URL}/news"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class AnthropicCollector:
    """Collects recent articles from anthropic.com/news by scraping."""

    def __init__(self, max_articles: int = 3, max_age_hours: int = 72):
        self.max_articles = max_articles
        self.max_age_hours = max_age_hours
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def collect(self) -> list[dict]:
        """Scrape anthropic.com/news and return recent articles."""
        try:
            slugs = self._get_news_slugs()
            if not slugs:
                logger.warning("AnthropicCollector: no article slugs found on news page")
                return []

            articles = []
            for slug in slugs:
                if len(articles) >= self.max_articles:
                    break
                article = self._fetch_article(slug)
                if article:
                    articles.append(article)
                time.sleep(1)

            logger.info(f"AnthropicCollector: fetched {len(articles)} articles")
            return articles

        except Exception as e:
            logger.error(f"AnthropicCollector error: {e}")
            return []

    def _get_news_slugs(self) -> list[str]:
        """Fetch the news listing page and extract /news/SLUG hrefs."""
        try:
            resp = self.session.get(NEWS_URL, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch {NEWS_URL}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        slugs = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Match /news/SLUG but not /news itself (the listing page)
            if href.startswith("/news/") and len(href) > len("/news/"):
                if href not in seen:
                    seen.add(href)
                    slugs.append(href)

        return slugs

    def _fetch_article(self, path: str) -> Optional[dict]:
        """Fetch a single article page and parse it."""
        url = f"{BASE_URL}{path}"
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch article {url}: {e}")
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        title = self._extract_title(soup)
        published = self._extract_date(soup)

        # Age filter — if we got a date, check it
        if published and not self._is_recent(published):
            logger.debug(f"Skipping old article: {url}")
            return None

        content = self._extract_content(soup)

        return {
            "source_type": "rss",
            "source": "Anthropic",
            "title": title,
            "url": url,
            "content": content[:2000],
            "published": published.isoformat() if published else None,
            "author": "Anthropic",
        }

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title."""
        # Try og:title meta first
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        # Try <title>
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        # Try first h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return "Anthropic News"

    def _extract_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract publication date using fallback chain."""
        # 1. <time datetime="...">
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            dt = self._parse_date(time_tag["datetime"])
            if dt:
                return dt

        # 2. <meta property="article:published_time">
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            dt = self._parse_date(meta["content"])
            if dt:
                return dt

        # 3. No date found — treat as recent (within window)
        return None

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract article body text using fallback chain."""
        # 1. <article>
        article = soup.find("article")
        if article:
            return article.get_text(separator=" ", strip=True)

        # 2. <main>
        main = soup.find("main")
        if main:
            return main.get_text(separator=" ", strip=True)

        # 3. Full body
        body = soup.find("body")
        if body:
            return body.get_text(separator=" ", strip=True)

        return ""

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to timezone-aware datetime."""
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
