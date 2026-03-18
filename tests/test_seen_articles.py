"""Tests for seen_articles module."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from seen_articles import SeenArticles


@pytest.fixture
def seen_file(tmp_path):
    """Return a path to a temporary seen_articles.json."""
    return tmp_path / "seen_articles.json"


class TestSeenArticles:
    def test_load_empty(self, seen_file):
        """No file yet — should start empty."""
        sa = SeenArticles(seen_file)
        assert sa.is_seen("https://example.com/article") is False

    def test_mark_and_check(self, seen_file):
        sa = SeenArticles(seen_file)
        sa.mark_seen(["https://example.com/a1", "https://example.com/a2"])
        sa.save()

        # Reload from disk
        sa2 = SeenArticles(seen_file)
        assert sa2.is_seen("https://example.com/a1") is True
        assert sa2.is_seen("https://example.com/a2") is True
        assert sa2.is_seen("https://example.com/a3") is False

    def test_filter_items(self, seen_file):
        sa = SeenArticles(seen_file)
        sa.mark_seen(["https://example.com/old"])
        sa.save()

        sa2 = SeenArticles(seen_file)
        items = [
            {"title": "Old article", "url": "https://example.com/old", "source_type": "rss"},
            {"title": "New article", "url": "https://example.com/new", "source_type": "rss"},
            {"title": "No URL", "source_type": "rss"},
        ]
        filtered = sa2.filter_unseen(items)
        assert len(filtered) == 2
        assert filtered[0]["title"] == "New article"
        assert filtered[1]["title"] == "No URL"

    def test_prune_old_entries(self, seen_file):
        """Entries older than retention_days should be pruned."""
        old_date = (datetime.now() - timedelta(days=20)).isoformat()
        recent_date = datetime.now().isoformat()

        data = {
            "https://example.com/old": old_date,
            "https://example.com/recent": recent_date,
        }
        seen_file.write_text(json.dumps(data))

        sa = SeenArticles(seen_file, retention_days=14)
        assert sa.is_seen("https://example.com/old") is False
        assert sa.is_seen("https://example.com/recent") is True

    def test_save_creates_file(self, seen_file):
        sa = SeenArticles(seen_file)
        sa.mark_seen(["https://example.com/x"])
        sa.save()
        assert seen_file.exists()
        data = json.loads(seen_file.read_text())
        assert "https://example.com/x" in data

    def test_duplicate_marks_ignored(self, seen_file):
        sa = SeenArticles(seen_file)
        sa.mark_seen(["https://example.com/x"])
        sa.mark_seen(["https://example.com/x"])
        sa.save()
        data = json.loads(seen_file.read_text())
        assert len(data) == 1

    def test_normalize_urls(self, seen_file):
        """Trailing slashes and fragments should be normalized."""
        sa = SeenArticles(seen_file)
        sa.mark_seen(["https://example.com/article/"])
        assert sa.is_seen("https://example.com/article") is True
        assert sa.is_seen("https://example.com/article/") is True
