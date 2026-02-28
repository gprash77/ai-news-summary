"""Anthropic News & Research Collector - Scrapes anthropic.com/news and /research."""

import json
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
RESEARCH_URL = f"{BASE_URL}/research"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class AnthropicCollector:
    """Collects recent articles from anthropic.com/news and /research by scraping."""

    def __init__(self, max_articles: int = 3, max_research: int = 3, max_age_hours: int = 72):
        self.max_articles = max_articles
        self.max_research = max_research
        self.max_age_hours = max_age_hours
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def collect(self) -> list[dict]:
        """Scrape anthropic.com/news and /research, return recent articles."""
        all_articles = []

        # Collect from /news
        news = self._collect_from_page(NEWS_URL, "/news/", self.max_articles, "Anthropic News")
        all_articles.extend(news)

        # Collect from /research
        research = self._collect_from_page(RESEARCH_URL, "/research/", self.max_research, "Anthropic Research")
        all_articles.extend(research)

        logger.info(f"AnthropicCollector: fetched {len(all_articles)} articles ({len(news)} news, {len(research)} research)")
        return all_articles

    def _collect_from_page(self, listing_url: str, prefix: str, max_items: int, source_label: str) -> list[dict]:
        """Collect articles from a listing page."""
        try:
            slugs = self._get_slugs(listing_url, prefix)
            if not slugs:
                logger.warning(f"AnthropicCollector: no slugs found on {listing_url}")
                return []

            articles = []
            for slug in slugs:
                if len(articles) >= max_items:
                    break
                article = self._fetch_article(slug, source_label)
                if article:
                    articles.append(article)
                time.sleep(1)
            return articles

        except Exception as e:
            logger.error(f"AnthropicCollector error for {listing_url}: {e}")
            return []

    def _get_slugs(self, listing_url: str, prefix: str) -> list[str]:
        """Fetch a listing page and extract hrefs matching the prefix."""
        try:
            resp = self.session.get(listing_url, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch {listing_url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        slugs = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(prefix) and len(href) > len(prefix):
                if href not in seen:
                    seen.add(href)
                    slugs.append(href)

        return slugs

    def _fetch_article(self, path: str, source_label: str = "Anthropic") -> Optional[dict]:
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
            "source_type": "anthropic_research" if "/research/" in url else "anthropic_news",
            "source": source_label,
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

        # 3. JSON-LD publishedOn (used by /research pages)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                for key in ("publishedOn", "datePublished"):
                    if key in data:
                        dt = self._parse_date(data[key])
                        if dt:
                            return dt
            except (json.JSONDecodeError, TypeError):
                continue

        # 4. No date found — treat as recent (within window)
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
