import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from logger import logger
from quota_guard import quota_guard


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
        self._play_window_seconds = self._resolve_play_window()
        self._last_play_timestamps: Dict[str, float] = {}
        self._poll_count = 0
        self._last_status_log = 0

    def start(self) -> None:
        if not self.enabled:
            logger.info("History tracker disabled via configuration")
            return

        if self._thread.is_alive():
            logger.debug("History tracker thread already running")
            return

        logger.info("Starting history tracker thread (interval: %ss)", self.poll_interval)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("History tracker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("History tracker encountered an error: %s", exc)
                logger.debug("History tracker traceback", exc_info=True)
            finally:
                self._stop_event.wait(self.poll_interval)

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
            # Log when media stops playing (transition from active to none)
            if self._active_media_key:
                logger.debug("History tracker: Media stopped playing")
            self._active_media_key = None
            return

        title = media.get('title')
        duration = self._normalize_duration(media.get('duration'))

        if not title or duration is None:
            logger.debug("History tracker skipping media with missing title/duration")
            return

        media_key = f"{title}|{duration}"
        now = time.time()

        # Log when new media starts playing
        if self._active_media_key != media_key:
            logger.info(
                "History tracker detected new media: '%s' (%ss)",
                title,
                duration
            )

        if not self._can_record_play(media_key, now):
            logger.debug(
                "History tracker throttled '%s' (play recorded %.0fs ago)",
                title,
                now - self._last_play_timestamps.get(media_key, 0),
            )
            self._active_media_key = media_key
            return

        existing = self.db.find_by_title_and_duration(title, duration)
        if existing:
            self.db.record_play(existing['video_id'])
            logger.debug("History tracker recorded repeat play for '%s'", title)
            self._active_media_key = media_key
            self._last_failed_key = None
            self._mark_play_recorded(media_key, now)
            return

        video = self.find_cached_video({
            'title': title,
            'artist': media.get('artist'),
            'duration': duration
        })
        if not video:
            video = self.search_and_match_video({
                'title': title,
                'artist': media.get('artist'),
                'duration': duration
            })

        if not video:
            if quota_guard.is_blocked():
                pending_id = self.db.upsert_pending_media({
                    'title': title,
                    'artist': media.get('artist'),
                    'duration': duration,
                })
                self.db.record_play(pending_id)
                logger.info(
                    "History tracker stored pending HA snapshot for '%s' (%s) due to YouTube cooldown: %s",
                    title,
                    pending_id,
                    quota_guard.describe_block(),
                )
                self._active_media_key = media_key
                self._last_failed_key = None
                self._mark_play_recorded(media_key, now)
                return
            if self._last_failed_key != media_key:
                logger.warning(
                    "History tracker could not match '%s' (%ss) to a YouTube video",
                    title,
                    duration,
                )
            self._last_failed_key = media_key
            return

        video_id = video['video_id']
        self.db.upsert_video({
            'video_id': video_id,
            'ha_title': title,
            'ha_artist': media.get('artist'),
            'yt_title': video.get('title', title),
            'yt_channel': video.get('channel'),
            'yt_channel_id': video.get('channel_id'),
            'yt_description': video.get('description'),
            'yt_published_at': video.get('published_at'),
            'yt_category_id': video.get('category_id'),
            'yt_live_broadcast': video.get('live_broadcast'),
            'yt_location': video.get('location'),
            'yt_recording_date': video.get('recording_date'),
            'ha_duration': duration,
            'yt_duration': video.get('duration'),
            'youtube_url': f"https://www.youtube.com/watch?v={video_id}",
            'source': 'ha_live',
        })
        self.db.record_play(video_id)
        logger.info("History tracker stored '%s' (video %s)", title, video_id)
        self._active_media_key = media_key
        self._last_failed_key = None
        self._mark_play_recorded(media_key, now)

    @staticmethod
    def _normalize_duration(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    def _resolve_play_window(self) -> int:
        raw = os.getenv('HISTORY_PLAY_WINDOW_SECONDS', '3600')
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid HISTORY_PLAY_WINDOW_SECONDS '%s'; defaulting to 3600", raw)
            return 3600
        if value < 60:
            logger.warning("HISTORY_PLAY_WINDOW_SECONDS too low (%s); enforcing minimum 60", value)
            return 60
        return value

    def _can_record_play(self, media_key: str, now: float) -> bool:
        last = self._last_play_timestamps.get(media_key)
        if not last:
            return True
        return (now - last) >= self._play_window_seconds

    def _mark_play_recorded(self, media_key: str, now: float) -> None:
        self._last_play_timestamps[media_key] = now
