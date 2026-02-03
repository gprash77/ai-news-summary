"""Gmail Collector - Fetches newsletters from Gmail via API."""

import os
import base64
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Optional imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

# Gmail API scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',  # For marking as read
    'https://www.googleapis.com/auth/gmail.send',    # For sending emails
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
                    newsletter = self._fetch_message(service, msg['id'])
                    if newsletter:
                        newsletters.append(newsletter)

                        # Mark as read if configured
                        if self.mark_as_read:
                            self._mark_as_read(service, msg['id'])

                except Exception as e:
                    logger.error(f"Error processing message {msg['id']}: {e}")

            logger.info(f"Fetched {len(newsletters)} newsletters")
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

    def _fetch_message(self, service, message_id: str) -> Optional[dict]:
        """Fetch and parse a single email message."""
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

        # Extract body
        body = self._extract_body(msg['payload'])

        return {
            'source_type': 'newsletter',
            'source': headers.get('From', 'Unknown'),
            'title': headers.get('Subject', 'No subject'),
            'url': '',
            'content': body[:3000],
            'published': published.isoformat() if published else None,
            'author': headers.get('From', ''),
            'message_id': message_id,
        }

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
