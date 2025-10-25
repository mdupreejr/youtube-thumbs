import threading
import time
from typing import Any, Callable, Dict, Optional

from logger import logger


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
        media = self.ha_api.get_current_media()
        if not media:
            return

        title = media.get('title')
        duration = self._normalize_duration(media.get('duration'))

        if not title or duration is None:
            logger.debug("History tracker skipping media with missing title/duration")
            return

        media_key = f"{title}|{duration}"

        existing = self.db.find_by_title_and_duration(title, duration)
        if existing:
            self.db.record_play(existing['video_id'])
            logger.debug("History tracker recorded repeat play for '%s'", title)
            self._last_failed_key = None
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
            'yt_title': video.get('title', title),
            'channel': video.get('channel'),
            'ha_duration': duration,
            'yt_duration': video.get('duration'),
            'youtube_url': f"https://www.youtube.com/watch?v={video_id}",
        })
        self.db.record_play(video_id)
        logger.info("History tracker stored '%s' (video %s)", title, video_id)
        self._last_failed_key = None

    @staticmethod
    def _normalize_duration(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None
