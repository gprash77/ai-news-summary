"""Archiver - Saves daily digests to local files."""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Archiver:
    """Saves daily digests to local archive."""

    def __init__(
        self,
        archive_path: str = "./archive",
        format: str = "markdown"
    ):
        self.archive_path = Path(archive_path)
        self.format = format
        self.archive_path.mkdir(parents=True, exist_ok=True)

    def save(self, items: list[dict], daily_summary: str) -> str:
        """Save the daily digest to archive."""
        date_str = datetime.now().strftime('%Y-%m-%d')

        if self.format == 'json':
            return self._save_json(items, daily_summary, date_str)
        else:
            return self._save_markdown(items, daily_summary, date_str)

    def _save_markdown(self, items: list[dict], daily_summary: str, date_str: str) -> str:
        """Save digest as Markdown file."""
        filepath = self.archive_path / f"{date_str}.md"

        lines = [
            f"# AI News Summary - {datetime.now().strftime('%B %d, %Y')}",
            "",
            "## Quick Summary",
            "",
            daily_summary,
            "",
            "---",
            "",
            "## Detailed Items",
            "",
        ]

        # Group by source type
        grouped = self._group_by_source(items)

        for source_type, type_items in grouped.items():
            icon = self._get_icon(source_type)
            lines.append(f"### {icon} {source_type.upper()}")
            lines.append("")

            for item in type_items:
                title = item.get('title', 'No title')
                source = item.get('source', '')
                tldr = item.get('tldr', '')
                url = item.get('url', '')
                published = item.get('published', '')

                if url:
                    lines.append(f"#### [{title}]({url})")
                else:
                    lines.append(f"#### {title}")

                lines.append(f"*Source: {source}*")
                if published:
                    lines.append(f"*Published: {published}*")
                lines.append("")

                if tldr:
                    lines.append(f"**TLDR:** {tldr}")
                    lines.append("")

                # Add original content as collapsible
                content = item.get('content', '')
                if content and len(content) > 100:
                    lines.append("<details>")
                    lines.append("<summary>Original content</summary>")
                    lines.append("")
                    lines.append(content[:1000])
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")

                lines.append("---")
                lines.append("")

        # Stats
        lines.extend([
            "",
            "## Statistics",
            "",
            f"- **Total items:** {len(items)}",
            f"- **YouTube:** {len(grouped.get('youtube', []))}",
            f"- **Twitter/X:** {len(grouped.get('twitter', []))}",
            f"- **Newsletters:** {len(grouped.get('newsletter', []))}",
            f"- **RSS:** {len(grouped.get('rss', []))}",
            f"- **Generated:** {datetime.now().isoformat()}",
        ])

        content = "\n".join(lines)
        filepath.write_text(content)
        logger.info(f"Saved archive to {filepath}")
        return str(filepath)

    def _save_json(self, items: list[dict], daily_summary: str, date_str: str) -> str:
        """Save digest as JSON file."""
        filepath = self.archive_path / f"{date_str}.json"

        data = {
            'date': date_str,
            'generated_at': datetime.now().isoformat(),
            'summary': daily_summary,
            'items': items,
            'stats': {
                'total': len(items),
                'by_source': {}
            }
        }

        # Count by source type
        for item in items:
            source_type = item.get('source_type', 'other')
            data['stats']['by_source'][source_type] = data['stats']['by_source'].get(source_type, 0) + 1

        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"Saved archive to {filepath}")
        return str(filepath)

    def _group_by_source(self, items: list[dict]) -> dict[str, list[dict]]:
        """Group items by source type."""
        grouped = {}
        order = ['youtube', 'twitter', 'newsletter', 'rss']

        for item in items:
            source_type = item.get('source_type', 'other')
            if source_type not in grouped:
                grouped[source_type] = []
            grouped[source_type].append(item)

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

    def get_recent_archives(self, days: int = 7) -> list[str]:
        """Get list of recent archive files."""
        files = sorted(self.archive_path.glob(f"*.{self.format.replace('markdown', 'md')}"))
        return [str(f) for f in files[-days:]]
