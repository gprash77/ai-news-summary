"""AudioGenerator - TTS via edge-tts + upload to Google Drive."""

import asyncio
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts not installed. Run: pip install edge-tts")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    DRIVE_AVAILABLE = True
except ImportError:
    DRIVE_AVAILABLE = False
    logger.warning("google-api-python-client not installed for Drive upload")


class AudioGenerator:
    """Generates podcast MP3 via edge-tts and uploads to Google Drive."""

    def __init__(
        self,
        creds=None,
        audio_path: str = "./audio",
        voice: str = "en-US-GuyNeural",
    ):
        self.creds = creds
        self.audio_path = Path(audio_path)
        self.voice = voice

    def generate(self, script: str) -> Optional[str]:
        """Generate TTS audio from script, upload to Drive, return share URL.

        Returns:
            Google Drive share URL string, or None on failure.
        """
        if not EDGE_TTS_AVAILABLE:
            logger.error("edge-tts not available — cannot generate audio")
            return None

        if not script:
            logger.warning("Empty script — skipping audio generation")
            return None

        # Save MP3 to disk
        mp3_path = self._save_audio(script)
        if not mp3_path:
            return None

        # Upload to Drive
        if not DRIVE_AVAILABLE or not self.creds:
            logger.info(f"Audio saved locally at {mp3_path} (Drive upload skipped — no credentials)")
            return None

        return self._upload_to_drive(mp3_path)

    def _save_audio(self, script: str) -> Optional[Path]:
        """Run edge-tts and save MP3 file. Returns path or None."""
        try:
            self.audio_path.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now().strftime("%Y-%m-%d")
            mp3_path = self.audio_path / f"ai-news-{date_str}.mp3"

            asyncio.run(self._tts(script, str(mp3_path)))
            logger.info(f"Audio saved: {mp3_path} ({mp3_path.stat().st_size // 1024} KB)")
            return mp3_path
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return None

    async def _tts(self, text: str, output_path: str):
        """Async edge-tts call."""
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(output_path)

    def _upload_to_drive(self, mp3_path: Path) -> Optional[str]:
        """Upload MP3 to Google Drive and return shareable URL."""
        try:
            service = build("drive", "v3", credentials=self.creds)

            file_metadata = {
                "name": mp3_path.name,
                "mimeType": "audio/mpeg",
            }
            media = MediaFileUpload(str(mp3_path), mimetype="audio/mpeg", resumable=False)

            uploaded = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()

            file_id = uploaded.get("id")
            if not file_id:
                logger.error("Drive upload returned no file ID")
                return None

            # Make publicly readable
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()

            url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            logger.info(f"Audio uploaded to Drive: {url}")
            return url

        except Exception as e:
            logger.error(f"Drive upload failed: {e}")
            return None
