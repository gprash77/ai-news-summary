"""Gemini Summarizer - Generates TLDR summaries using Gemini API."""

import os
import re
import time
import warnings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def _extract_retry_delay(error_msg: str) -> int:
    """Extract retry delay from rate limit error message."""
    match = re.search(r'retry in (\d+)', str(error_msg), re.IGNORECASE)
    if match:
        return int(match.group(1)) + 2  # Add 2 seconds buffer
    return 60  # Default to 60 seconds if not found

# Suppress deprecation warning for google.generativeai
warnings.filterwarnings("ignore", message=".*google.generativeai.*deprecated.*")

# Optional import - try new SDK first, fall back to old
GEMINI_AVAILABLE = False
GEMINI_NEW_SDK = False

try:
    from google import genai as google_genai
    from google.genai import types
    GEMINI_AVAILABLE = True
    GEMINI_NEW_SDK = True
except ImportError:
    try:
        import google.generativeai as genai
        GEMINI_AVAILABLE = True
    except ImportError:
        pass


class GeminiSummarizer:
    """Generates summaries using Google's Gemini API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash-lite",
        max_tokens: int = 1024
    ):
        self.api_key = api_key or os.environ.get('GEMINI_API_KEY')
        self.model_name = model
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        """Get or create Gemini client."""
        if not GEMINI_AVAILABLE:
            raise RuntimeError("google-genai or google-generativeai not installed")
        if not self.api_key:
            raise ValueError("Gemini API key not configured")

        if not self._client:
            if GEMINI_NEW_SDK:
                self._client = google_genai.Client(api_key=self.api_key)
            else:
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel(self.model_name)

        return self._client

    def summarize_item(self, item: dict, max_retries: int = 2) -> tuple[str, str]:
        """Generate a TLDR summary and podcast segment for a single news item.

        Returns:
            (tldr, podcast_segment) — both are strings; podcast_segment may be
            empty string if the API call fails.
        """
        if not self.api_key:
            return self._fallback_summary(item), ""

        prompt = f"""You must produce BOTH a TLDR and a PODCAST segment for this content. Do NOT stop after the TLDR.

Title: {item.get('title', 'No title')}
Source: {item.get('source', 'Unknown')}
Content:
{item.get('content', '')[:1500]}

Respond in EXACTLY this format (both sections are REQUIRED):

TLDR: A 2-3 sentence concise summary.

PODCAST: A 200-250 word conversational segment that a podcast host would read aloud. Write in flowing prose, no bullet points. Explain why this matters and what it means for the AI community."""

        for attempt in range(max_retries):
            try:
                client = self._get_client()

                if GEMINI_NEW_SDK:
                    response = client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            max_output_tokens=700,
                            temperature=0.3
                        )
                    )
                    result = response.text.strip()
                else:
                    response = client.generate_content(
                        prompt,
                        generation_config=genai.GenerationConfig(
                            max_output_tokens=700,
                            temperature=0.3
                        )
                    )
                    result = response.text.strip()

                time.sleep(4)  # Rate limit: 15 RPM = 1 request every 4 seconds

                tldr, podcast_segment = self._parse_dual_output(result)

                if len(tldr) >= 30:
                    return tldr, podcast_segment

                logger.warning(f"Short TLDR result, attempt {attempt+1}")

            except Exception as e:
                error_str = str(e)
                logger.error(f"Error summarizing item (attempt {attempt+1}): {e}")

                # Check for quota exhaustion (daily limit)
                if '429' in error_str and 'RESOURCE_EXHAUSTED' in error_str:
                    if 'GenerateRequestsPerDayPerProjectPerModel' in error_str:
                        logger.warning("Daily quota exhausted, using fallback for remaining items")
                        break  # No point retrying, quota is gone for the day
                    else:
                        # Per-minute rate limit, wait and retry
                        wait_time = _extract_retry_delay(error_str)
                        logger.info(f"Rate limited, waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        continue

                if attempt < max_retries - 1:
                    time.sleep(3)

        return self._fallback_summary(item), ""

    def _parse_dual_output(self, text: str) -> tuple[str, str]:
        """Parse response with TLDR: and PODCAST: sections."""
        tldr = ""
        podcast_segment = ""

        # Try multiple patterns the model might use
        podcast_match = re.search(r'\n+\**\s*PODCAST\s*:?\**\s*', text, re.IGNORECASE)
        if podcast_match:
            tldr_part = text[:podcast_match.start()]
            podcast_segment = text[podcast_match.end():].strip()
        else:
            logger.debug(f"No PODCAST section found in response: {text[:200]}...")
            tldr_part = text

        # Strip "TLDR:" prefix if present
        tldr_clean = re.sub(r'^\**\s*TLDR\s*:?\**\s*', '', tldr_part, flags=re.IGNORECASE).strip()
        tldr = tldr_clean if tldr_clean else tldr_part.strip()

        return tldr, podcast_segment

    def generate_daily_summary(self, items: list[dict], max_retries: int = 3) -> str:
        """Generate an overall summary of the day's news."""
        if not items:
            return "No AI news items collected today."

        if not self.api_key:
            return self._generate_bullet_summary(items)

        # Select balanced items: 2 YouTube, 2 newsletter, 1 RSS
        selected_items = self._select_balanced_items(items)

        # Prepare concise content for summary
        items_text = "\n".join([
            f"{i+1}. {item.get('title', 'No title')} | URL: {item.get('url', 'no link')}"
            for i, item in enumerate(selected_items)
        ])

        prompt = f"""Create exactly {len(selected_items)} bullet points for these AI news items.

Format each bullet EXACTLY like this:
• [Title](full_url_here)

Items:
{items_text}

Output {len(selected_items)} bullets, each with a markdown link:"""

        for attempt in range(max_retries):
            try:
                client = self._get_client()

                if GEMINI_NEW_SDK:
                    response = client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            max_output_tokens=1500,
                            temperature=0.2
                        )
                    )
                    result = response.text.strip()
                else:
                    response = client.generate_content(
                        prompt,
                        generation_config=genai.GenerationConfig(
                            max_output_tokens=1500,
                            temperature=0.2
                        )
                    )
                    result = response.text.strip()

                # Verify we got complete output (has all URLs)
                if result.count('](http') >= len(selected_items) - 1:
                    return result

                logger.warning(f"Incomplete summary (attempt {attempt+1}), retrying...")
                time.sleep(2)

            except Exception as e:
                logger.error(f"Error generating daily summary (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)

        # Fallback to non-AI summary
        logger.warning("Using fallback summary after retries failed")
        return self._generate_bullet_summary(items)

    def generate_podcast_script(self, items: list[dict], max_retries: int = 2) -> str:
        """Stitch per-item podcast segments into a full ~20-minute podcast script.

        Only items that have a 'podcast_segment' key are included.
        Returns the full script string, or empty string on failure.
        """
        segments = [item for item in items if item.get('podcast_segment')]
        if not segments:
            logger.info("No podcast segments found — skipping podcast script generation")
            return ""

        segments_text = ""
        for i, item in enumerate(segments, 1):
            title = item.get('title', 'Untitled')
            source = item.get('source', 'Unknown')
            segment = item['podcast_segment']
            segments_text += f"\n--- Story {i}: {title} (Source: {source}) ---\n{segment}\n"

        prompt = f"""You are producing a daily AI news podcast called "AI News Daily".
Write a complete, natural-sounding podcast script using the story segments below.

Requirements:
- Open with: "Welcome to AI News Daily, your daily briefing on artificial intelligence."
- Include a brief (1-2 sentence) transition between each story
- Insert each story segment VERBATIM — do not rewrite or shorten them
- Close with a friendly outro
- The tone should be warm, informative, and conversational
- Do NOT add bullet points, headers, or stage directions

Story segments to include (use verbatim):
{segments_text}

Write the complete podcast script now:"""

        for attempt in range(max_retries):
            try:
                client = self._get_client()

                if GEMINI_NEW_SDK:
                    response = client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            max_output_tokens=2000,
                            temperature=0.4
                        )
                    )
                    result = response.text.strip()
                else:
                    response = client.generate_content(
                        prompt,
                        generation_config=genai.GenerationConfig(
                            max_output_tokens=2000,
                            temperature=0.4
                        )
                    )
                    result = response.text.strip()

                time.sleep(4)

                if len(result) > 200:
                    logger.info(f"Podcast script generated ({len(result)} chars, {len(segments)} stories)")
                    return result

                logger.warning(f"Short podcast script on attempt {attempt+1}")

            except Exception as e:
                error_str = str(e)
                logger.error(f"Error generating podcast script (attempt {attempt+1}): {e}")
                if '429' in error_str and 'RESOURCE_EXHAUSTED' in error_str:
                    if 'GenerateRequestsPerDayPerProjectPerModel' in error_str:
                        break
                    wait_time = _extract_retry_delay(error_str)
                    logger.info(f"Rate limited, waiting {wait_time}s before retry")
                    time.sleep(wait_time)
                    continue
                if attempt < max_retries - 1:
                    time.sleep(5)

        return ""

    def _fallback_summary(self, item: dict) -> str:
        """Generate a simple summary when API is unavailable."""
        content = item.get('content', '')
        if len(content) > 400:
            # Find a good break point (end of sentence or space)
            truncated = content[:400]
            # Try to break at sentence end
            for sep in ['. ', '! ', '? ']:
                if sep in truncated[200:]:
                    return truncated[:truncated.rfind(sep, 200) + 1]
            # Fall back to word boundary
            return truncated.rsplit(' ', 1)[0] + '...'
        return content or item.get('title', 'No summary available')

    def _generate_bullet_summary(self, items: list[dict]) -> str:
        """Generate bullet point summary without AI, with links."""
        # Use balanced selection: 2 YouTube, 2 newsletter, 1 RSS
        selected = self._select_balanced_items(items)
        bullets = []
        for item in selected:
            title = item.get('title', 'No title')
            url = item.get('url', '')
            source_type = item.get('source_type', '')

            # Format with link if available
            if url:
                bullets.append(f"• [{title}]({url})")
            else:
                bullets.append(f"• {title}")
        return "\n".join(bullets)

    def _select_balanced_items(self, items: list[dict], youtube_count: int = 2, newsletter_count: int = 3, rss_count: int = 1) -> list[dict]:
        """Select items balanced across source types: 2 YouTube, 3 newsletter, 1 RSS."""
        by_type = {}
        for item in items:
            source_type = item.get('source_type', 'other')
            if source_type not in by_type:
                by_type[source_type] = []
            by_type[source_type].append(item)

        selected = []
        # Add items in specific order with specific counts
        if 'youtube' in by_type:
            selected.extend(by_type['youtube'][:youtube_count])
        if 'newsletter' in by_type:
            selected.extend(by_type['newsletter'][:newsletter_count])
        if 'rss' in by_type:
            selected.extend(by_type['rss'][:rss_count])
        if 'twitter' in by_type:
            selected.extend(by_type['twitter'][:1])

        return selected

    def is_ai_related(self, item: dict) -> bool:
        """Check if content is AI-related using Gemini."""
        if not self.api_key:
            # Fallback: keyword matching
            return self._keyword_ai_check(item)

        try:
            client = self._get_client()

            text = f"{item.get('title', '')} {item.get('content', '')[:500]}"

            prompt = f"""Is this content about AI, machine learning, LLMs, or artificial intelligence?
Answer only "yes" or "no".

Content: {text}

Answer:"""

            if GEMINI_NEW_SDK:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=10,
                        temperature=0
                    )
                )
                answer = response.text.strip().lower()
            else:
                response = client.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        max_output_tokens=10,
                        temperature=0
                    )
                )
                answer = response.text.strip().lower()

            return answer.startswith('yes')

        except Exception as e:
            logger.debug(f"Error checking AI relevance: {e}")
            return self._keyword_ai_check(item)

    def _keyword_ai_check(self, item: dict) -> bool:
        """Check for AI keywords in title or content."""
        keywords = ['ai', 'artificial intelligence', 'machine learning', 'llm',
                    'gpt', 'claude', 'gemini', 'openai', 'anthropic', 'deepmind',
                    'neural', 'chatbot', 'language model', 'deep learning', 'cursor',
                    'copilot', 'agent', 'agentic', 'llama', 'mistral']

        title = item.get('title', '').lower()
        content = item.get('content', '').lower()

        # Check title + content for all source types
        return any(kw in title or kw in content for kw in keywords)
