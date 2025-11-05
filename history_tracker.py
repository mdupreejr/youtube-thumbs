import threading
import time
from typing import Any, Callable, Dict, Optional

from logger import logger
from quota_guard import quota_guard
from video_helpers import prepare_video_upsert, is_youtube_content
from constants import MEDIA_INACTIVITY_TIMEOUT


MediaDict = Dict[str, Any]
VideoLookup = Callable[[MediaDict], Optional[Dict[str, Any]]]


class HistoryTracker:
    """Background worker that snapshots Home Assistant playback history."""

    def __init__(
        self,
        ha_api: Any,
        database: Any,
        find_cached_video: VideoLookup,
        search_and_match_video: VideoLookup,
        poll_interval: int = 30,
        enabled: bool = True,
    ) -> None:
        self.ha_api = ha_api
        self.db = database
        self.find_cached_video = find_cached_video
        self.search_and_match_video = search_and_match_video
        # Avoid overly aggressive polling and fall back to default on bad values.
        self.poll_interval = poll_interval if poll_interval and poll_interval > 0 else 30
        self.enabled = enabled
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="history-tracker", daemon=True)
        self._last_failed_key: Optional[str] = None
        self._active_media_key: Optional[str] = None
        self._last_media_time: float = 0  # Timestamp of last media activity
        self._poll_count = 0
        self._last_status_log = 0
        self._consecutive_failures = 0
        self.max_consecutive_failures = 10
        self._inactivity_timeout = MEDIA_INACTIVITY_TIMEOUT  # Clear tracking after 1 hour of no media

    def start(self) -> None:
        if not self.enabled:
            logger.info("History tracker disabled via configuration")
            return

        if self._thread.is_alive():
            logger.debug("History tracker thread already running")
            return

        # If thread died, create a new one
        if self._thread.ident is not None:  # Thread was started before but died
            logger.warning("History tracker thread died, creating new thread")
            self._stop_event.clear()  # Reset stop event
            self._consecutive_failures = 0  # Reset failure counter
            self._thread = threading.Thread(target=self._run, name="history-tracker", daemon=True)

        logger.info("Starting history tracker thread (interval: %ss)", self.poll_interval)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("History tracker stopped")

    def is_healthy(self) -> bool:
        """Check if the history tracker thread is healthy."""
        if not self.enabled:
            return True  # Disabled tracker is considered healthy
        return self._thread.is_alive()

    def ensure_running(self) -> None:
        """Ensure the history tracker is running, restart if needed."""
        if not self.enabled:
            return
        if not self.is_healthy():
            logger.warning("History tracker thread not healthy, attempting restart")
            self.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
                # Reset failure count on successful poll
                self._consecutive_failures = 0
            except Exception as exc:  # pragma: no cover - defensive logging
                self._consecutive_failures += 1
                logger.error(
                    "History tracker encountered an error (failure %d/%d): %s",
                    self._consecutive_failures, self.max_consecutive_failures, exc
                )

                # Exit thread after too many consecutive failures
                if self._consecutive_failures >= self.max_consecutive_failures:
                    logger.critical(
                        "History tracker failed %d times consecutively, shutting down. "
                        "Check logs for persistent errors.",
                        self._consecutive_failures
                    )
                    break  # Exit thread

                logger.debug("History tracker traceback", exc_info=True)
            finally:
                # Exponential backoff on failures (cap at 5 minutes)
                if self._consecutive_failures > 0:
                    wait_time = self.poll_interval * (2 ** min(self._consecutive_failures - 1, 5))
                    wait_time = min(wait_time, 300)  # Cap at 5 minutes
                else:
                    wait_time = self.poll_interval
                self._stop_event.wait(wait_time)

    def _poll_once(self) -> None:
        self._poll_count += 1

        # Log status every 10 polls (10 minutes by default)
        if self._poll_count % 10 == 0:
            logger.debug(
                "History tracker status: poll #%d, active for %d minutes",
                self._poll_count,
                (self._poll_count * self.poll_interval) // 60
            )

        media = self.ha_api.get_current_media()
        if not media:
            # Media stopped/paused - but DON'T reset _active_media_key immediately
            # This prevents counting pause/resume as a new play
            now = time.time()
            if self._active_media_key:
                # Clear tracking after extended inactivity (1 hour default)
                if self._last_media_time > 0 and (now - self._last_media_time) > self._inactivity_timeout:
                    logger.debug("History tracker: Clearing tracking after %d seconds of inactivity",
                                self._inactivity_timeout)
                    self._active_media_key = None
                    self._last_media_time = 0
                else:
                    logger.debug("History tracker: Media paused/stopped (tracking retained)")
            return

        # Skip non-YouTube content to save API calls
        if not is_youtube_content(media):
            title = media.get('title', 'unknown')
            app_name = media.get('app_name', 'unknown')
            if self._active_media_key and not self._active_media_key.startswith(f"non-yt|{app_name}"):
                logger.info(f"History tracker skipping non-YouTube content: '{title}' from app '{app_name}'")
            self._active_media_key = f"non-yt|{app_name}|{title}"
            return

        title = media.get('title')
        duration = self._normalize_duration(media.get('duration'))

        if not title or duration is None:
            logger.debug("History tracker skipping media with missing title/duration")
            return

        media_key = f"{title}|{duration}"
        now = time.time()
        self._last_media_time = now  # Update last activity timestamp

        # Only record play when a new song starts (not during continuous playback)
        is_new_song = self._active_media_key != media_key

        if is_new_song:
            logger.info(
                "History tracker detected new media: '%s' (%ss)",
                title,
                duration
            )
        else:
            # Same song still playing - don't increment play count
            logger.debug(
                "History tracker: '%s' still playing, skipping increment",
                title
            )
            return

        # Check if this search recently failed (Phase 3: Cache Negative Results)
        if self.db.is_recently_not_found(title, None, duration):
            logger.debug("History tracker skipping '%s' - recently not found on YouTube", title)
            self._last_failed_key = media_key
            return

        existing = self.db.find_by_title_and_duration(title, duration)
        if existing:
            self.db.record_play(existing['yt_video_id'])
            logger.debug("History tracker recorded play for '%s'", title)
            self._active_media_key = media_key
            self._last_failed_key = None
            return

        video = self.find_cached_video({
            'title': title,
            'artist': media.get('artist'),
            'app_name': media.get('app_name'),
            'duration': duration
        })
        if not video:
            video = self.search_and_match_video({
                'title': title,
                'artist': media.get('artist'),
                'app_name': media.get('app_name'),
                'duration': duration
            })

        if not video:
            should_skip, _ = quota_guard.check_quota_or_skip("track history video", title)
            if should_skip:
                pending_id = self.db.upsert_pending_media({
                    'title': title,
                    'artist': media.get('artist'),
                    'app_name': media.get('app_name'),
                    'duration': duration,
                }, reason='quota_exceeded')
                self.db.record_play(pending_id)
                logger.info(
                    "History tracker stored pending HA snapshot for '%s' (%s) due to YouTube cooldown: %s",
                    title,
                    pending_id,
                    quota_guard.describe_block(),
                )
                self._active_media_key = media_key
                self._last_failed_key = None
                return
            if self._last_failed_key != media_key:
                logger.warning(
                    "History tracker could not match '%s' (%ss) to a YouTube video",
                    title,
                    duration,
                )
            self._last_failed_key = media_key
            return

        yt_video_id = video['yt_video_id']

        # Use helper function to prepare video data
        ha_media = {
            'title': title,
            'artist': media.get('artist'),
            'app_name': media.get('app_name'),
            'duration': duration
        }
        video_data = prepare_video_upsert(video, ha_media, source='ha_live')
        self.db.upsert_video(video_data)
        self.db.record_play(yt_video_id)
        logger.info("History tracker stored '%s' (video %s)", title, yt_video_id)
        self._active_media_key = media_key
        self._last_failed_key = None

    @staticmethod
    def _normalize_duration(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None
