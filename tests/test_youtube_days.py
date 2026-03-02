"""Tests for weekend-only YouTube collection."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from main import collect_all


def _base_config(youtube_days=None):
    """Return a minimal config with only YouTube enabled."""
    config = {
        'sources': {
            'youtube': {
                'channels': ['@test_channel'],
                'max_videos_per_channel': 1,
                'fetch_transcripts': False,
            },
            'rss': {'enabled': False},
            'twitter': {'enabled': False},
            'research_feeds': {'enabled': False},
            'anthropic': {'enabled': False},
            'newsletters': {},
        },
        'filters': {'max_age_hours': 48},
    }
    if youtube_days is not None:
        config['sources']['youtube']['youtube_days'] = youtube_days
    return config


@patch('main.YouTubeCollector')
def test_youtube_skipped_on_weekday(mock_yt_cls):
    """YouTube should be skipped when today is not in youtube_days."""
    # Wednesday = weekday 2, only enabled on [5, 6]
    with patch('main.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 4)  # Wednesday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        collect_all(_base_config(youtube_days=[5, 6]))
    mock_yt_cls.assert_not_called()


@patch('main.YouTubeCollector')
def test_youtube_collected_on_saturday(mock_yt_cls):
    """YouTube should run when today is in youtube_days."""
    mock_yt_cls.return_value.collect.return_value = []
    with patch('main.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 7)  # Saturday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        collect_all(_base_config(youtube_days=[5, 6]))
    mock_yt_cls.assert_called_once()


@patch('main.YouTubeCollector')
def test_youtube_collected_when_no_days_configured(mock_yt_cls):
    """YouTube should run every day when youtube_days is empty or missing."""
    mock_yt_cls.return_value.collect.return_value = []
    with patch('main.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 4)  # Wednesday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        collect_all(_base_config(youtube_days=[]))
    mock_yt_cls.assert_called_once()


@patch('main.YouTubeCollector')
def test_youtube_collected_when_days_not_set(mock_yt_cls):
    """YouTube should run every day when youtube_days key is absent."""
    mock_yt_cls.return_value.collect.return_value = []
    with patch('main.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 4)  # Wednesday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        collect_all(_base_config())  # no youtube_days key
    mock_yt_cls.assert_called_once()
