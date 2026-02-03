"""Email Sender - Sends daily digest via Gmail API."""

import os
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
]


class EmailSender:
    """Sends daily digest emails via Gmail API."""

    def __init__(
        self,
        from_email: str,
        subscribers: list[str],
        subject_prefix: str = "AI News Summary",
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        twitter_accounts: Optional[list[str]] = None
    ):
        self.from_email = from_email
        self.subscribers = subscribers
        self.subject_prefix = subject_prefix
        self.twitter_accounts = twitter_accounts or []

        base_path = Path(__file__).parent.parent / 'credentials'
        self.credentials_path = credentials_path or str(base_path / 'gmail_credentials.json')
        self.token_path = token_path or str(base_path / 'gmail_token.json')

        self._service = None

    def _get_credentials(self) -> Optional['Credentials']:
        """Get or refresh Gmail API credentials."""
        if not GMAIL_API_AVAILABLE:
            raise RuntimeError("Gmail API libraries not installed")

        creds = None

        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    logger.error(f"Gmail credentials not found at {self.credentials_path}")
                    return None

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

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

    def send_digest(self, items: list[dict], daily_summary: str) -> bool:
        """Send the daily digest email to all subscribers."""
        if not self.subscribers:
            logger.warning("No subscribers configured")
            return False

        service = self._get_service()
        if not service:
            logger.error("Gmail service not available")
            return False

        # Check if we have any Twitter items
        has_twitter = any(item.get('source_type') == 'twitter' for item in items)

        # Format the email content
        subject = f"{self.subject_prefix} - {datetime.now().strftime('%b %d, %Y')}"
        html_body = self._format_email_html(items, daily_summary, include_twitter_fallback=not has_twitter)
        text_body = self._format_email_text(items, daily_summary, include_twitter_fallback=not has_twitter)

        try:
            # Create message
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = self.from_email
            message['To'] = self.subscribers[0]  # Primary recipient

            # BCC for additional subscribers (privacy)
            if len(self.subscribers) > 1:
                message['Bcc'] = ', '.join(self.subscribers[1:])

            # Attach both plain text and HTML versions
            message.attach(MIMEText(text_body, 'plain'))
            message.attach(MIMEText(html_body, 'html'))

            # Encode and send
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            service.users().messages().send(
                userId='me',
                body={'raw': raw}
            ).execute()

            logger.info(f"Sent digest to {len(self.subscribers)} subscribers")
            return True

        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False

    def _format_email_text(self, items: list[dict], daily_summary: str, include_twitter_fallback: bool = False) -> str:
        """Format email as plain text."""
        date_str = datetime.now().strftime('%B %d, %Y')

        lines = [
            "=" * 55,
            "            TODAY'S TOP AI NEWS",
            "=" * 55,
            "",
            "Quick Summary:",
            daily_summary,
            "",
            "-" * 55,
            "              DETAILED ITEMS",
            "-" * 55,
            "",
        ]

        # Group items by source type
        grouped = self._group_by_source(items)

        for source_type, type_items in grouped.items():
            icon = self._get_icon(source_type)
            lines.append(f"{icon} {source_type.upper()}")
            lines.append("")

            for i, item in enumerate(type_items, 1):
                title = item.get('title', 'No title')
                tldr = item.get('tldr', '')
                url = item.get('url', '')

                lines.append(f"{i}. {title}")
                if tldr:
                    lines.append(f"   TLDR: {tldr}")
                if url:
                    lines.append(f"   🔗 {url}")
                lines.append("")

            lines.append("")

        # Add Twitter fallback section if no tweets were collected
        if include_twitter_fallback and self.twitter_accounts:
            lines.extend([
                "-" * 55,
                "🐦 AI ACCOUNTS TO FOLLOW ON X/TWITTER",
                "-" * 55,
                "",
                "Twitter feed unavailable today. Here are accounts worth following:",
                "",
            ])
            for account in self.twitter_accounts:
                lines.append(f"  • @{account} - https://x.com/{account}")
            lines.append("")

        return "\n".join(lines)

    def _format_email_html(self, items: list[dict], daily_summary: str, include_twitter_fallback: bool = False) -> str:
        """Format email as HTML."""
        date_str = datetime.now().strftime('%B %d, %Y')

        # Group items by source type
        grouped = self._group_by_source(items)

        sections_html = ""
        for source_type, type_items in grouped.items():
            icon = self._get_icon(source_type)
            items_html = ""

            for item in type_items:
                title = item.get('title', 'No title')
                tldr = item.get('tldr', '')
                url = item.get('url', '')
                source = item.get('source', '')

                link_html = f'<a href="{url}" style="color: #0066cc;">{title}</a>' if url else title

                items_html += f"""
                <div style="margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 5px;">
                    <div style="font-weight: bold; margin-bottom: 5px;">{link_html}</div>
                    <div style="color: #666; font-size: 12px; margin-bottom: 5px;">{source}</div>
                    {f'<div style="color: #333;">{tldr}</div>' if tldr else ''}
                </div>
                """

            sections_html += f"""
            <div style="margin-bottom: 25px;">
                <h3 style="color: #333; border-bottom: 2px solid #ddd; padding-bottom: 5px;">
                    {icon} {source_type.upper()}
                </h3>
                {items_html}
            </div>
            """

        # Add Twitter fallback section if no tweets were collected
        twitter_fallback_html = ""
        if include_twitter_fallback and self.twitter_accounts:
            accounts_html = "".join([
                f'<a href="https://x.com/{acc}" style="display: inline-block; margin: 5px; padding: 8px 12px; background: #1DA1F2; color: white; text-decoration: none; border-radius: 20px; font-size: 14px;">@{acc}</a>'
                for acc in self.twitter_accounts
            ])
            twitter_fallback_html = f"""
            <div style="margin-bottom: 25px; padding: 15px; background: #f0f8ff; border-radius: 8px; border-left: 4px solid #1DA1F2;">
                <h3 style="color: #333; margin: 0 0 10px 0;">🐦 AI Accounts to Follow on X/Twitter</h3>
                <p style="color: #666; margin: 0 0 10px 0; font-size: 14px;">Twitter feed unavailable today. Here are accounts worth following for AI news:</p>
                <div>{accounts_html}</div>
            </div>
            """

        # Convert daily summary to HTML (handle bullet points)
        summary_html = daily_summary.replace('\n', '<br>').replace('•', '&#8226;')

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
            <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 10px; margin-bottom: 20px;">
                <h1 style="margin: 0; font-size: 24px;">🤖 AI News Summary</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">{date_str}</p>
            </div>

            <div style="background: #e8f4f8; padding: 15px; border-radius: 8px; margin-bottom: 25px;">
                <h2 style="margin: 0 0 10px 0; font-size: 16px; color: #333;">📋 Quick Summary</h2>
                <div style="color: #444; line-height: 1.6;">{summary_html}</div>
            </div>

            <div style="border-top: 2px solid #eee; padding-top: 20px;">
                <h2 style="color: #333; font-size: 18px;">📰 Detailed Items</h2>
                {sections_html}
            </div>

            {twitter_fallback_html}

            <div style="text-align: center; padding: 20px; color: #888; font-size: 12px; border-top: 1px solid #eee; margin-top: 20px;">
                Generated by AI News Summary Aggregator
            </div>
        </body>
        </html>
        """

        return html

    def _group_by_source(self, items: list[dict]) -> dict[str, list[dict]]:
        """Group items by source type."""
        grouped = {}
        order = ['youtube', 'twitter', 'newsletter', 'rss']

        for item in items:
            source_type = item.get('source_type', 'other')
            if source_type not in grouped:
                grouped[source_type] = []
            grouped[source_type].append(item)

        # Sort by preferred order
        sorted_grouped = {}
        for key in order:
            if key in grouped:
                sorted_grouped[key] = grouped[key]
        for key in grouped:
            if key not in sorted_grouped:
                sorted_grouped[key] = grouped[key]

        return sorted_grouped

    def _get_icon(self, source_type: str) -> str:
        """Get icon for source type."""
        icons = {
            'youtube': '📺',
            'twitter': '🐦',
            'newsletter': '📰',
            'rss': '📡',
        }
        return icons.get(source_type, '📄')
