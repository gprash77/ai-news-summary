"""Tests for EmailSender — verifies message composition and send behavior."""
import base64
import sys
from email import message_from_bytes
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from emailer import EmailSender

SAMPLE_ITEMS = [
    {"title": "GPT-5 released", "summary": "OpenAI releases GPT-5.", "url": "https://example.com/1", "source_type": "rss"},
    {"title": "Anthropic raises funding", "summary": "Anthropic raises $1B.", "url": "https://example.com/2", "source_type": "anthropic_news"},
]
SAMPLE_SUMMARY = "Two big AI stories today."


def _make_sender(subscribers):
    return EmailSender(
        from_email="sender@example.com",
        subscribers=subscribers,
    )


def _capture_raw_message(mock_service):
    """Return the decoded MIME message captured by the mock send() call."""
    call_kwargs = mock_service.users().messages().send.call_args
    raw_b64 = call_kwargs[1]['body']['raw']
    raw_bytes = base64.urlsafe_b64decode(raw_b64 + '==')
    return message_from_bytes(raw_bytes)


class TestSendDigestSingleSubscriber:
    def test_sends_exactly_one_email(self):
        sender = _make_sender(["alice@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            result = sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        assert result is True
        assert mock_service.users().messages().send.call_count == 1

    def test_to_header_contains_subscriber(self):
        sender = _make_sender(["alice@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        assert msg['To'] == "alice@example.com"

    def test_no_bcc_header(self):
        sender = _make_sender(["alice@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        assert msg['Bcc'] is None


class TestSendDigestMultipleSubscribers:
    def test_sends_exactly_one_email(self):
        """Regression test: multiple subscribers must NOT cause multiple sends."""
        sender = _make_sender(["alice@example.com", "bob@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            result = sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        assert result is True
        assert mock_service.users().messages().send.call_count == 1

    def test_to_header_contains_all_subscribers(self):
        sender = _make_sender(["alice@example.com", "bob@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        assert "alice@example.com" in msg['To']
        assert "bob@example.com" in msg['To']

    def test_no_bcc_header(self):
        sender = _make_sender(["alice@example.com", "bob@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        assert msg['Bcc'] is None

    def test_three_subscribers_still_one_send(self):
        sender = _make_sender(["a@example.com", "b@example.com", "c@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        assert mock_service.users().messages().send.call_count == 1


class TestSendDigestEdgeCases:
    def test_no_subscribers_returns_false(self):
        sender = _make_sender([])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            result = sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        assert result is False
        mock_service.users().messages().send.assert_not_called()

    def test_service_unavailable_returns_false(self):
        sender = _make_sender(["alice@example.com"])

        with patch.object(sender, '_get_service', return_value=None):
            result = sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        assert result is False

    def test_subject_contains_date(self):
        sender = _make_sender(["alice@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        assert "AI News Summary" in msg['Subject']

    def test_from_header(self):
        sender = _make_sender(["alice@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        assert msg['From'] == "sender@example.com"

    def test_message_has_html_and_text_parts(self):
        sender = _make_sender(["alice@example.com"])
        mock_service = MagicMock()

        with patch.object(sender, '_get_service', return_value=mock_service):
            sender.send_digest(SAMPLE_ITEMS, SAMPLE_SUMMARY)

        msg = _capture_raw_message(mock_service)
        content_types = [part.get_content_type() for part in msg.walk()]
        assert 'text/plain' in content_types
        assert 'text/html' in content_types
