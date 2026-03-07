#!/usr/bin/env python3
"""AI News Summary Aggregator - Main entry point."""

import argparse
import logging
import os
import random
import re
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

    # YouTube (optionally restricted to certain days of the week)
    youtube_config = config.get('sources', {}).get('youtube', {})
    youtube_days = youtube_config.get('youtube_days', [])
    today = datetime.now().weekday()
    if youtube_days and today not in youtube_days:
        logger.info(f"Skipping YouTube collection (today={today}, enabled days={youtube_days})")
    elif youtube_config.get('channels'):
        channels = youtube_config['channels']
        channels_per_run = youtube_config.get('channels_per_run')
        if channels_per_run and channels_per_run < len(channels):
            channels = random.sample(channels, channels_per_run)
            logger.info(f"YouTube rotation: selected {channels_per_run} of {len(youtube_config['channels'])} channels: {channels}")
        logger.info("Collecting from YouTube...")
        youtube_collector = YouTubeCollector(
            channels=channels,
            max_videos_per_channel=youtube_config.get('max_videos_per_channel', 3),
            fetch_transcripts=youtube_config.get('fetch_transcripts', True),
            max_age_hours=max_age
        )
        items = youtube_collector.collect()
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from YouTube")

    # Research feeds (OpenAI, Google AI)
    research_config = config.get('sources', {}).get('research_feeds', {})
    if research_config.get('feeds') and research_config.get('enabled', True):
        logger.info("Collecting from research feeds...")
        rss_collector = RSSCollector(
            feeds=research_config['feeds'],
            max_age_hours=max_age,
            max_items_per_feed=research_config.get('max_items_per_feed', 1)
        )
        items = rss_collector.collect()
        # Override source_type based on feed URL
        for item in items:
            url = item.get('url', '') + ' ' + item.get('source', '')
            if 'openai' in url.lower():
                item['source_type'] = 'openai_research'
            elif 'google' in url.lower() or 'deepmind' in url.lower():
                item['source_type'] = 'google_research'
        all_items.extend(items)
        logger.info(f"Collected {len(items)} items from research feeds")

    # Anthropic news (scraped)
    anthropic_config = config.get('sources', {}).get('anthropic', {})
    if anthropic_config.get('enabled', True):
        logger.info("Collecting from Anthropic news...")
        anthropic_collector = AnthropicCollector(
            max_articles=anthropic_config.get('max_articles', 3),
            max_research=anthropic_config.get('max_research', 3),
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

    # Ensure all research items have podcast segments (they should never be skipped)
    research_types = {'anthropic_research', 'openai_research', 'google_research'}
    research_missing_podcast = [
        item for item in items
        if item.get('source_type') in research_types
        and item.get('tldr')
        and not item.get('podcast_segment')
    ]
    if research_missing_podcast:
        logger.info(f"Generating podcast segments for {len(research_missing_podcast)} research items...")
        for item in research_missing_podcast:
            item['podcast_segment'] = summarizer.generate_podcast_segment(item)

    # Generate overall summary
    logger.info("Generating daily summary...")
    daily_summary = summarizer.generate_daily_summary(items)

    return items, daily_summary


def _title_words(title: str) -> set:
    """Extract significant words from a title for comparison."""
    stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
                  'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were',
                  'be', 'been', 'has', 'have', 'had', 'its', 'our', 'this', 'that'}
    words = set(re.findall(r'[a-z0-9]+', title.lower()))
    return words - stop_words


def _content_words(content: str) -> set:
    """Extract significant words from the first 500 chars of content for comparison."""
    stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
                  'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were',
                  'be', 'been', 'has', 'have', 'had', 'its', 'our', 'this', 'that',
                  'it', 'not', 'no', 'so', 'if', 'as', 'we', 'can', 'will', 'also',
                  'more', 'about', 'up', 'out', 'just', 'than', 'into', 'new'}
    words = set(re.findall(r'[a-z0-9]+', content[:500].lower()))
    return words - stop_words


def deduplicate_items(items: list[dict], threshold: float = 0.5) -> list[dict]:
    """Remove near-duplicate items covering the same story.

    Compares titles using word overlap, with a secondary content-based check
    for items with partially similar titles. When duplicates are found, keeps
    the item from the original source (e.g. anthropic_news over rss).
    """
    # Source priority: prefer original/primary sources
    source_priority = {
        'anthropic_news': 0,
        'anthropic_research': 0,
        'openai_research': 0,
        'google_research': 0,
        'newsletter': 1,
        'rss': 2,
        'youtube': 1,
        'twitter': 2,
    }

    kept = []
    for item in items:
        title_words = _title_words(item.get('title', ''))
        if not title_words:
            kept.append(item)
            continue

        duplicate_of = None
        for i, existing in enumerate(kept):
            existing_words = _title_words(existing.get('title', ''))
            if not existing_words:
                continue
            overlap = len(title_words & existing_words) / min(len(title_words), len(existing_words))
            if overlap >= threshold:
                duplicate_of = i
                break
            # Secondary check: titles somewhat related, compare content
            if overlap >= 0.25:
                cw = _content_words(item.get('content', ''))
                ecw = _content_words(existing.get('content', ''))
                if cw and ecw:
                    content_overlap = len(cw & ecw) / min(len(cw), len(ecw))
                    if content_overlap >= 0.4:
                        duplicate_of = i
                        break

        if duplicate_of is not None:
            existing = kept[duplicate_of]
            new_prio = source_priority.get(item.get('source_type', 'other'), 3)
            existing_prio = source_priority.get(existing.get('source_type', 'other'), 3)
            if new_prio < existing_prio:
                logger.info(f"Dedup: replacing '{existing.get('title', '')[:50]}' ({existing.get('source_type')}) with '{item.get('title', '')[:50]}' ({item.get('source_type')})")
                kept[duplicate_of] = item
            else:
                logger.info(f"Dedup: dropping '{item.get('title', '')[:50]}' ({item.get('source_type')}) - similar to '{existing.get('title', '')[:50]}'")
        else:
            kept.append(item)

    if len(kept) < len(items):
        logger.info(f"Deduplication: {len(items)} -> {len(kept)} items ({len(items) - len(kept)} duplicates removed)")
    return kept


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

    # Deduplicate items covering the same story across sources
    items = deduplicate_items(items)

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
