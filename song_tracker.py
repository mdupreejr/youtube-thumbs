"""
Automatic song tracking - polls Home Assistant every 30 seconds to build playback history.
Tracks all songs played and increments play count (max 1x per hour per song).
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


class SongTracker:
    """Automatically tracks songs playing on Home Assistant media player."""

    def __init__(self, ha_api, db, poll_interval=30):
        """
        Initialize song tracker.

        Args:
            ha_api: Home Assistant API instance
            db: Database instance
            poll_interval: How often to poll in seconds (default: 30)
        """
        self.ha_api = ha_api
        self.db = db
        self.poll_interval = poll_interval
        self._thread = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_tracked = {}  # Track last play count increment per song

    def start(self):
        """Start the background song tracking thread."""
        if self._running:
            logger.warning("Song tracker already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._thread.start()
        logger.info(f"Song tracker started (polling every {self.poll_interval}s)")

    def stop(self):
        """Stop the background song tracking thread."""
        if not self._running:
            return

        logger.info("Stopping song tracker...")
        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("Song tracker stopped")

    def _tracking_loop(self):
        """Main loop that polls HA and tracks songs."""
        # Wait one poll interval before first check to avoid duplicate startup fetch
        # (startup health checks already fetch current media)
        if self._stop_event.wait(timeout=self.poll_interval):
            return

        while self._running:
            try:
                self._check_and_track_song()
            except Exception as e:
                logger.error(f"Error in song tracking loop: {e}", exc_info=True)

            # Wait for poll interval or stop event
            if self._stop_event.wait(timeout=self.poll_interval):
                break

    def _check_and_track_song(self):
        """Poll HA for current media and track if needed."""
        try:
            # Get current media from Home Assistant
            media = self.ha_api.get_current_media()

            if not media:
                # Nothing playing or error
                logger.debug("Song tracker poll: No media playing")
                return

            # Only track YouTube content
            if media.get('app_name') != 'YouTube':
                logger.debug(f"Song tracker poll: Non-YouTube app ({media.get('app_name')}), skipping")
                return

            title = media.get('title')
            duration = media.get('duration')

            if not title or not duration:
                logger.debug("Missing title or duration, skipping track")
                return

            # Calculate content hash for deduplication (throttling purposes)
            from helpers.video_helpers import get_content_hash
            content_hash = get_content_hash(
                title=title,
                duration=duration,
                artist=media.get('artist')
            )

            # Check if we should increment play count (max 1x per hour)
            if not self._should_increment_play_count(content_hash):
                logger.debug(f"Song tracker poll: '{title}' already tracked recently (throttled)")
                return

            # Use same cache lookup logic as rating endpoints
            # This checks BOTH content_hash AND title+duration matching
            from helpers.cache_helpers import find_cached_video
            cached_video = find_cached_video(self.db, media)

            if cached_video and cached_video.get('yt_video_id'):
                # Song found in cache - increment play count
                yt_video_id = cached_video['yt_video_id']
                self._increment_play_count(yt_video_id, content_hash)
                artist = media.get('artist', 'Unknown')
                logger.info(f"Tracked play: '{title}' by '{artist}' ({duration}s) | ID: {yt_video_id} | play_count +1")
            else:
                # Not in cache - queue YouTube search (same as rating endpoints)
                # This uses the established queue logic and caching strategy
                # v4.2.5: enqueue_search() now returns None if recently failed search exists
                search_id = self.db.enqueue_search(media)
                if search_id is None:
                    logger.debug(f"Skipping search for '{title}' - recent failed search found (quota protection)")
                else:
                    artist = media.get('artist', 'Unknown')
                    logger.info(f"New song detected: '{title}' by '{artist}' ({duration}s) - queued for YouTube search (queue_id: {search_id})")

        except Exception as e:
            logger.error(f"Error checking/tracking song: {e}", exc_info=True)

    def _should_increment_play_count(self, content_hash: str) -> bool:
        """
        Check if we should increment play count for this song.
        Returns True if song hasn't been tracked in the last hour.

        Args:
            content_hash: Content hash of the song

        Returns:
            True if play count should be incremented
        """
        now = datetime.now(timezone.utc)

        # Check last tracking time for this song
        last_tracked = self._last_tracked.get(content_hash)

        if not last_tracked:
            # Never tracked before
            self._last_tracked[content_hash] = now
            return True

        # Check if at least 1 hour has passed
        time_since_last = now - last_tracked

        if time_since_last >= timedelta(hours=1):
            self._last_tracked[content_hash] = now
            return True

        # Too soon - skip
        return False

    def _increment_play_count(self, yt_video_id: str, content_hash: str):
        """
        Increment play count and update last played timestamp.

        Args:
            yt_video_id: YouTube video ID
            content_hash: Content hash for the song
        """
        try:
            with self.db._lock:
                self.db._conn.execute(
                    """
                    UPDATE video_ratings
                    SET play_count = play_count + 1,
                        date_last_played = CURRENT_TIMESTAMP
                    WHERE yt_video_id = ?
                    """,
                    (yt_video_id,)
                )
                self.db._conn.commit()
        except Exception as e:
            logger.error(f"Failed to increment play count for {yt_video_id}: {e}")
