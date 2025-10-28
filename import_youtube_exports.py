#!/usr/bin/env python3
"""Import YouTube watch-history HTML exports into the local database."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from database import get_database
from logger import logger

SOURCE_NAME = "yt_export"


def extract_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip('/')

    if 'youtu.be' in host and path:
        return path.split('/')[-1]

    if 'youtube.com' in host:
        if path == '/watch' or path == '/watch/':
            return parse_qs(parsed.query).get('v', [None])[0]
        if path.startswith('/shorts/'):
            return path.split('/shorts/')[-1]
    return None


def normalize_timestamp(raw: str) -> str:
    dt = date_parser.parse(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def parse_entries(html_path: Path) -> Iterable[Tuple[str, str, Optional[str], str, str]]:
    """Yield (video_id, title, channel, timestamp, url) tuples."""
    soup = BeautifulSoup(html_path.read_text(encoding='utf-8', errors='ignore'), 'html.parser')
    cells = soup.select('div.outer-cell div.content-cell.mdl-typography--body-1')

    for cell in cells:
        text_parts = list(cell.stripped_strings)
        if not text_parts:
            continue
        first = text_parts[0].lower()
        if not first.startswith('watched'):
            continue

        video_link = cell.find('a', href=lambda href: href and 'watch' in href or (href and 'youtu.be' in href))
        if not video_link or not video_link.get('href'):
            continue
        video_url = video_link['href']
        video_id = extract_video_id(video_url)
        if not video_id:
            continue

        title = video_link.get_text(strip=True) or f"Video {video_id}"

        channel_link = None
        links = cell.find_all('a')
        if len(links) > 1:
            for link in links[1:]:
                href = link.get('href', '')
                if 'channel' in href or 'user' in href:
                    channel_link = link
                    break
        channel = channel_link.get_text(strip=True) if channel_link else None

        timestamp_text = text_parts[-1]
        try:
            timestamp = normalize_timestamp(timestamp_text)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Skipping entry with unparseable timestamp '%s' (%s)", timestamp_text, exc)
            continue

        yield video_id, title, channel, timestamp, video_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--directory', '-d',
        default='youtube_exports',
        help='Directory containing the MyActivity/watch-history HTML files (default: youtube_exports)',
    )
    parser.add_argument(
        '--db-path',
        help='Override the SQLite path (defaults to YTT_DB_PATH or /config/youtube_thumbs/ratings.db)',
    )
    args = parser.parse_args()

    export_dir = Path(args.directory)
    if not export_dir.exists():
        logger.error("Directory %s does not exist", export_dir)
        return 1

    if args.db_path:
        os.environ['YTT_DB_PATH'] = args.db_path

    db = get_database()
    files = sorted(p for p in export_dir.glob('*.html'))
    if not files:
        logger.error("No .html exports found in %s", export_dir)
        return 1

    processed = skipped = deduped = 0
    for html_file in files:
        logger.info("Processing %s", html_file.name)
        for video_id, title, channel, timestamp, video_url in parse_entries(html_file):
            entry_key = f"{html_file.name}|{video_id}|{timestamp}"
            entry_id = hashlib.sha1(entry_key.encode('utf-8')).hexdigest()
            if db.import_entry_exists(entry_id):
                deduped += 1
                continue

            db.upsert_video(
                {
                    'yt_video_id': video_id,
                    'ha_title': title,
                    'ha_artist': None,
                    'yt_title': title,
                    'yt_channel': channel,
                    'yt_channel_id': None,
                    'yt_description': None,
                    'yt_published_at': None,
                    'yt_category_id': None,
                    'yt_live_broadcast': None,
                    'yt_location': None,
                    'yt_recording_date': None,
                    'ha_duration': None,
                    'yt_duration': None,
                    'yt_url': video_url,
                    'rating': 'none',
                    'source': SOURCE_NAME,
                },
                date_added=timestamp,
            )
            db.record_play(video_id, timestamp)
            db.log_import_entry(entry_id, SOURCE_NAME, video_id)
            processed += 1
        logger.info("Finished %s", html_file.name)

    logger.info(
        "Imported %s entries (%s deduplicated, %s files)",
        processed,
        deduped,
        len(files),
    )
    if processed == 0 and deduped == 0:
        logger.warning("Nothing new to import. Add fresh exports or delete import_history entries to re-run.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
