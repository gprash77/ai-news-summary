#!/usr/bin/env python3
"""AI News Summary Aggregator - Main entry point."""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import yaml

from collectors import RSSCollector, TwitterCollector, YouTubeCollector, GmailCollector, AnthropicCollector
from summarizer import GeminiSummarizer
from emailer import EmailSender
from archiver import Archiver
from audio_generator import AudioGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent.parent / 'aggregator.log')
    ]
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / 'config.yaml'

    with open(config_path) as f:
        return yaml.safe_load(f)


def collect_all(config: dict) -> list[dict]:
    """Collect items from all configured sources."""
    all_items = []
    max_age = config.get('filters', {}).get('max_age_hours', 48)

    # RSS feeds
    rss_config = config.get('sources', {}).get('rss', {})
    if rss_config.get('feeds') and rss_config.get('enabled', True):
        logger.info("Collecting from RSS feeds...")
        rss_collector = RSSCollector(
            feeds=rss_config['feeds'],
            max_age_hours=max_age,
            max_items_per_feed=rss_config.get('max_items_per_feed', 2)
        )
        items = rss_collector.collect()
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from RSS")
    elif rss_config.get('feeds') and not rss_config.get('enabled', True):
        logger.info("RSS collection disabled in config")

    # Twitter/X via Syndication API (tweet URLs) and/or Nitter RSS (accounts)
    twitter_config = config.get('sources', {}).get('twitter', {})
    has_tweets = twitter_config.get('tweet_urls')
    has_accounts = twitter_config.get('accounts')
    if (has_tweets or has_accounts) and twitter_config.get('enabled', True):
        logger.info("Collecting from Twitter/X...")
        twitter_collector = TwitterCollector(
            tweet_urls=twitter_config.get('tweet_urls', []),
            accounts=twitter_config.get('accounts', []),
            nitter_instances=twitter_config.get('nitter_instances', []),
            max_age_hours=max_age
        )
        items = twitter_collector.collect()
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from Twitter")
    elif (has_tweets or has_accounts) and not twitter_config.get('enabled', True):
        logger.info("Twitter collection disabled in config")

    # YouTube
    youtube_config = config.get('sources', {}).get('youtube', {})
    if youtube_config.get('channels'):
        logger.info("Collecting from YouTube...")
        youtube_collector = YouTubeCollector(
            channels=youtube_config['channels'],
            max_videos_per_channel=youtube_config.get('max_videos_per_channel', 3),
            fetch_transcripts=youtube_config.get('fetch_transcripts', True),
            max_age_hours=max_age
        )
        items = youtube_collector.collect()
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from YouTube")

    # Anthropic news (scraped)
    anthropic_config = config.get('sources', {}).get('anthropic', {})
    if anthropic_config.get('enabled', True):
        logger.info("Collecting from Anthropic news...")
        anthropic_collector = AnthropicCollector(
            max_articles=anthropic_config.get('max_articles', 3),
            max_age_hours=anthropic_config.get('max_age_hours', 72)
        )
        items = anthropic_collector.collect()
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from Anthropic")

    # Email newsletters
    newsletter_config = config.get('sources', {}).get('newsletters', {})
    if newsletter_config.get('gmail_label'):
        logger.info("Collecting from Gmail newsletters...")
        gmail_collector = GmailCollector(
            label=newsletter_config['gmail_label'],
            mark_as_read=newsletter_config.get('mark_as_read', True),
            max_newsletters=newsletter_config.get('max_newsletters', 1),
            allowed_senders=newsletter_config.get('allowed_senders'),
            subject_must_contain=newsletter_config.get('subject_must_contain'),
            from_name_contains=newsletter_config.get('from_name_contains')
        )
        items = gmail_collector.collect()
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from newsletters")

    return all_items


def summarize_items(items: list[dict], config: dict) -> tuple[list[dict], str]:
    """Generate summaries for all items and overall digest."""
    gemini_config = config.get('gemini', {})

    summarizer = GeminiSummarizer(
        model=gemini_config.get('model', 'gemini-2.5-flash-lite'),
        max_tokens=gemini_config.get('max_tokens', 1024)
    )

    # Summarize items that don't already have a tldr (e.g. TLDR articles are pre-summarized)
    to_summarize = [item for item in items if not item.get('tldr') and item.get('content')]
    logger.info(f"Generating summaries for {len(to_summarize)} items ({len(items) - len(to_summarize)} already have summaries)...")
    for item in to_summarize:
        item['tldr'], item['podcast_segment'] = summarizer.summarize_item(item)

    # Generate podcast segments for pre-summarized items (e.g. TLDR newsletter articles)
    needs_podcast = [item for item in items if item.get('tldr') and not item.get('podcast_segment')]
    if needs_podcast:
        logger.info(f"Generating podcast segments for {len(needs_podcast)} pre-summarized items...")
        for item in needs_podcast:
            item['podcast_segment'] = summarizer.generate_podcast_segment(item)

    # Generate overall summary
    logger.info("Generating daily summary...")
    daily_summary = summarizer.generate_daily_summary(items)

    return items, daily_summary


def run(
    config_path: str = None,
    skip_email: bool = False,
    skip_archive: bool = False,
    dry_run: bool = False
):
    """Main execution flow."""
    logger.info("=" * 50)
    logger.info(f"AI News Summary - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 50)

    # Load config
    config = load_config(config_path)

    # Collect from all sources
    items = collect_all(config)

    if not items:
        logger.warning("No items collected from any source")
        return

    logger.info(f"Total items collected: {len(items)}")

    # Filter to AI-related content using fast keyword matching
    # (All our sources are AI-focused, so this is just a safety check)
    from summarizer import GeminiSummarizer
    filter_summarizer = GeminiSummarizer()

    original_count = len(items)
    items = [item for item in items if filter_summarizer._keyword_ai_check(item)]
    if original_count != len(items):
        logger.info(f"After AI filter: {len(items)} items (filtered {original_count - len(items)} non-AI items)")

    if not items:
        logger.warning("No AI-related items after filtering")
        return

    # Limit items that need Gemini summarization to stay within API rate limits.
    # Items that already have a tldr (e.g. parsed TLDR newsletter articles) are free.
    max_items = config.get('filters', {}).get('max_items', 10)
    needs_summary = [item for item in items if not item.get('tldr')]
    has_summary = [item for item in items if item.get('tldr')]
    if len(needs_summary) > max_items:
        logger.info(f"Limiting items needing summarization to {max_items} (from {len(needs_summary)})")
        needs_summary = needs_summary[:max_items]
    items = needs_summary + has_summary
    logger.info(f"Items to process: {len(needs_summary)} need summarization, {len(has_summary)} already summarized")

    if dry_run:
        logger.info("[DRY RUN] Would process the following items:")
        for item in items[:10]:
            logger.info(f"  - [{item['source_type']}] {item.get('title', 'No title')[:60]}")
        if len(items) > 10:
            logger.info(f"  ... and {len(items) - 10} more")
        return

    # Generate summaries
    items, daily_summary = summarize_items(items, config)

    logger.info("\n--- Daily Summary ---")
    logger.info(daily_summary)
    logger.info("---")

    # Generate podcast audio (optional)
    audio_url = None
    audio_config = config.get('audio', {})
    if audio_config.get('enabled'):
        logger.info("Generating podcast script...")
        gemini_config = config.get('gemini', {})
        script_summarizer = GeminiSummarizer(
            model=gemini_config.get('model', 'gemini-2.5-flash-lite'),
            max_tokens=gemini_config.get('max_tokens', 1024)
        )
        script = script_summarizer.generate_podcast_script(items)
        if script:
            logger.info("Generating audio...")
            newsletter_config = config.get('sources', {}).get('newsletters', {})
            creds = None
            if newsletter_config.get('gmail_label'):
                try:
                    _cred_collector = GmailCollector(label=newsletter_config['gmail_label'])
                    creds = _cred_collector._get_credentials()
                except Exception as e:
                    logger.warning(f"Could not load Google credentials for Drive: {e}")
            audio_gen = AudioGenerator(
                creds=creds,
                audio_path=audio_config.get('path', './audio'),
                voice=audio_config.get('voice', 'en-US-GuyNeural'),
            )
            audio_url = audio_gen.generate(script)
            if audio_url:
                logger.info(f"Podcast audio available at: {audio_url}")
            else:
                logger.warning("Audio generation failed or Drive upload skipped")

    # Archive
    if not skip_archive:
        archive_config = config.get('archive', {})
        archiver = Archiver(
            archive_path=archive_config.get('path', './archive'),
            format=archive_config.get('format', 'markdown')
        )
        archive_path = archiver.save(items, daily_summary)
        logger.info(f"Archived to: {archive_path}")

    # Send email
    if not skip_email:
        email_config = config.get('email', {})
        twitter_config = config.get('sources', {}).get('twitter', {})
        from_email = os.environ.get(email_config.get('from_env', 'EMAIL_FROM'), email_config.get('from', ''))
        subscribers_str = os.environ.get(email_config.get('subscribers_env', 'EMAIL_SUBSCRIBERS'), '')
        subscribers = [s.strip() for s in subscribers_str.split(',') if s.strip()] if subscribers_str else email_config.get('subscribers', [])
        if subscribers:
            emailer = EmailSender(
                from_email=from_email,
                subscribers=subscribers,
                subject_prefix=email_config.get('subject_prefix', 'AI News Summary'),
                twitter_accounts=twitter_config.get('accounts', [])
            )
            success = emailer.send_digest(items, daily_summary, audio_url=audio_url)
            if success:
                logger.info("Email sent successfully!")
            else:
                logger.error("Failed to send email")
        else:
            logger.warning("No subscribers configured - skipping email")

    logger.info("Done!")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='AI News Summary Aggregator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Full run: collect, summarize, archive, email
  python main.py --dry-run          # Test collection without processing
  python main.py --skip-email       # Run without sending email
  python main.py --skip-archive     # Run without saving to archive
  python main.py -c custom.yaml     # Use custom config file
        """
    )

    parser.add_argument(
        '-c', '--config',
        help='Path to config file (default: config.yaml)',
        default=None
    )
    parser.add_argument(
        '--skip-email',
        action='store_true',
        help='Skip sending email'
    )
    parser.add_argument(
        '--skip-archive',
        action='store_true',
        help='Skip saving to archive'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Collect items without processing (test mode)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        run(
            config_path=args.config,
            skip_email=args.skip_email,
            skip_archive=args.skip_archive,
            dry_run=args.dry_run
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
