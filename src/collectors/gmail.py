"""Gmail Collector - Fetches newsletters from Gmail via API."""

import os
import base64
import re
from urllib.parse import unquote
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# bs4 imported inside functions to allow graceful fallback


TLDR_SECTION_NAMES = {
    '🚀': 'Headlines & Launches',
    '🧠': 'Research & Innovation',
    '🎁': 'Miscellaneous',
}


def _clean_tracking_url(url: str) -> str:
    """Extract actual URL from tracking/redirect wrappers."""
    if not url:
        return url

    # TLDR tracking URL pattern: https://tracking.tldrnewsletter.com/CL0/https%3A%2F%2F.../1/tracking-id
    if 'tracking.tldrnewsletter.com' in url:
        match = re.search(r'/CL0/([^/]+)', url)
        if match:
            return unquote(match.group(1))

    return url


def _parse_tldr_articles(html_content: str) -> list[dict]:
    """Parse TLDR newsletter HTML to extract individual articles with links.

    Each article in TLDR is in a <td class="container"> with:
    - <a><strong>Title (X minute read)</strong></a>
    - <span>Description text</span>

    Section headers are emoji-only cells: 🚀, 🧠, 🎁
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, 'lxml')
    articles = []
    current_section = ''

    for td in soup.find_all('td', class_='container'):
        text_block = td.find('div', class_='text-block')
        if not text_block:
            continue

        cell_text = text_block.get_text(strip=True)

        # Check if this is a section header (just an emoji)
        if cell_text in TLDR_SECTION_NAMES:
            current_section = TLDR_SECTION_NAMES[cell_text]
            continue

        # Check if this cell contains an article link
        link = text_block.find('a', href=True)
        if not link:
            continue

        link_text = link.get_text(strip=True)

        # Article links have "minute read" or "GitHub Repo" in the text
        if 'minute read' not in link_text.lower() and 'github repo' not in link_text.lower():
            continue

        # Extract the URL
        url = _clean_tracking_url(link['href'])

        # Extract description: text in the cell that's not the link title
        # The description is in a <span> sibling after <br> tags
        desc_parts = []
        for span in text_block.find_all('span'):
            span_text = span.get_text(strip=True)
            # Skip the title span (it's inside the link)
            if span_text and span_text != link_text and link_text not in span_text:
                desc_parts.append(span_text)

        description = ' '.join(desc_parts).strip()

        articles.append({
            'title': link_text,
            'url': url,
            'description': description,
            'section': current_section,
        })

    return articles

# Optional imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

# Gmail API scopes needed (gmail.modify implies read access)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',  # Read + mark as read
    'https://www.googleapis.com/auth/gmail.send',    # For sending emails
    'https://www.googleapis.com/auth/drive.file',    # Upload podcast audio to Drive
]


class GmailCollector:
    """Collects newsletters from Gmail via API."""

    def __init__(
        self,
        label: str = "AI-News",
        mark_as_read: bool = True,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        max_newsletters: int = 1,
        allowed_senders: Optional[list[str]] = None,
        subject_must_contain: Optional[str] = None,
        from_name_contains: Optional[str] = None
    ):
        self.label = label
        self.mark_as_read = mark_as_read
        self.max_newsletters = max_newsletters
        self.allowed_senders = allowed_senders
        self.subject_must_contain = subject_must_contain
        self.from_name_contains = from_name_contains

        # Default paths
        base_path = Path(__file__).parent.parent.parent / 'credentials'
        self.credentials_path = credentials_path or str(base_path / 'gmail_credentials.json')
        self.token_path = token_path or str(base_path / 'gmail_token.json')

        self._service = None

    def _get_credentials(self) -> Optional['Credentials']:
        """Get or refresh Gmail API credentials."""
        if not GMAIL_API_AVAILABLE:
            raise RuntimeError("Gmail API libraries not installed")

        creds = None

        # Load existing token
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    logger.error(
                        f"Gmail credentials not found at {self.credentials_path}. "
                        "Please download from Google Cloud Console."
                    )
                    return None

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save the token for next run
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())

        return creds

    def _get_service(self):
        """Get or create Gmail API service."""
        if not self._service:
            creds = self._get_credentials()
            if not creds:
                return None
            self._service = build('gmail', 'v1', credentials=creds)
        return self._service

    def collect(self) -> list[dict]:
        """Fetch unread newsletters from configured Gmail label."""
        if not GMAIL_API_AVAILABLE:
            logger.warning("Gmail API not available - skipping newsletter collection")
            return []

        service = self._get_service()
        if not service:
            logger.warning("Gmail service not available - skipping newsletter collection")
            return []

        try:
            # Find the label ID
            label_id = self._get_label_id(service)
            if not label_id:
                logger.warning(f"Gmail label '{self.label}' not found")
                return []

            # Get unread messages with this label
            query = f"label:{self.label} is:unread"
            # Add sender filter if specified
            if self.allowed_senders:
                sender_query = " OR ".join([f"from:{s}" for s in self.allowed_senders])
                query = f"({query}) AND ({sender_query})"
            # Add from name filter (e.g., "TLDR AI" to match display name)
            if self.from_name_contains:
                query = f'({query}) AND from:"{self.from_name_contains}"'
            # Add subject filter if specified
            if self.subject_must_contain:
                query = f"({query}) AND subject:{self.subject_must_contain}"

            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=self.max_newsletters
            ).execute()

            messages = results.get('messages', [])
            if not messages:
                logger.info("No unread newsletters found")
                return []

            newsletters = []
            for msg in messages:
                try:
                    items = self._fetch_message(service, msg['id'])
                    if items:
                        newsletters.extend(items)

                        # Mark as read if configured
                        if self.mark_as_read:
                            self._mark_as_read(service, msg['id'])

                except Exception as e:
                    logger.error(f"Error processing message {msg['id']}: {e}")

            logger.info(f"Fetched {len(newsletters)} newsletter items")
            return newsletters

        except Exception as e:
            logger.error(f"Error fetching newsletters: {e}")
            return []

    def _get_label_id(self, service) -> Optional[str]:
        """Get label ID by name."""
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        for label in labels:
            if label['name'].lower() == self.label.lower():
                return label['id']
        return None

    def _fetch_message(self, service, message_id: str) -> list[dict]:
        """Fetch and parse a single email message. Returns list of items.

        For TLDR newsletters, parses HTML to extract individual articles.
        For other newsletters, returns a single item with the full content.
        """
        msg = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()

        headers = {h['name']: h['value'] for h in msg['payload']['headers']}

        # Parse date
        date_str = headers.get('Date', '')
        published = None
        if date_str:
            try:
                from dateutil import parser as date_parser
                published = date_parser.parse(date_str)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        published_str = published.isoformat() if published else None
        source = headers.get('From', 'Unknown')

        # For TLDR newsletters, parse HTML to extract individual articles
        if 'tldr' in source.lower():
            html_content = self._get_html_content(msg['payload'])
            if html_content:
                articles = _parse_tldr_articles(html_content)
                if articles:
                    # Cap articles per newsletter (prioritizes Headlines first since they're parsed in order)
                    articles = articles[:8]
                    items = []
                    for article in articles:
                        items.append({
                            'source_type': 'newsletter',
                            'source': f"TLDR AI - {article['section']}" if article['section'] else 'TLDR AI',
                            'title': article['title'],
                            'url': article['url'],
                            'content': article['description'],
                            'tldr': article['description'],  # Already summarized, skip Gemini
                            'published': published_str,
                            'author': source,
                            'message_id': message_id,
                        })
                    logger.info(f"Parsed {len(items)} articles from TLDR newsletter")
                    return items

        # Fallback: return single item with full content
        body, web_url = self._extract_body_and_url(msg['payload'])

        return [{
            'source_type': 'newsletter',
            'source': source,
            'title': headers.get('Subject', 'No subject'),
            'url': web_url,
            'content': body[:3000],
            'published': published_str,
            'author': source,
            'message_id': message_id,
        }]

    def _extract_body_and_url(self, payload: dict) -> tuple[str, str]:
        """Extract email body and web view URL."""
        body = ''
        web_url = ''

        # Try to get HTML first to extract links
        html_content = self._get_html_content(payload)
        if html_content:
            from bs4 import BeautifulSoup
            import re
            soup = BeautifulSoup(html_content, 'lxml')

            # Look for "View Online" or "View in browser" link
            for link in soup.find_all('a', href=True):
                link_text = link.get_text().lower()
                if any(phrase in link_text for phrase in ['view online', 'view in browser', 'web version', 'read online']):
                    web_url = link['href']
                    break

            # Also check for TLDR's tracking link pattern
            if not web_url:
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if 'tldr.tech' in href and '/ai/' in href:
                        web_url = href
                        break

            body = soup.get_text(separator=' ', strip=True)
        else:
            body = self._extract_body(payload)

        # Clean up tracking URLs
        web_url = _clean_tracking_url(web_url)

        return body, web_url

    def _get_html_content(self, payload: dict) -> str:
        """Extract HTML content from email."""
        if 'body' in payload and payload['body'].get('data'):
            if payload.get('mimeType') == 'text/html':
                return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')

        if 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')
                if mime_type == 'text/html' and part['body'].get('data'):
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                elif 'parts' in part:
                    html = self._get_html_content(part)
                    if html:
                        return html
        return ''

    def _extract_body(self, payload: dict) -> str:
        """Extract email body, preferring plain text."""
        body = ''

        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        elif 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')
                if mime_type == 'text/plain' and part['body'].get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break
                elif mime_type == 'text/html' and part['body'].get('data'):
                    html = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'lxml')
                    body = soup.get_text(separator=' ', strip=True)
                elif 'parts' in part:
                    # Nested multipart
                    body = self._extract_body(part)
                    if body:
                        break

        return body

    def _mark_as_read(self, service, message_id: str):
        """Mark a message as read."""
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()
