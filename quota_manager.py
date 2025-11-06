"""
Unified YouTube API Quota Manager

Simple quota management system that:
- Blocks all API calls when quota is exceeded
- Checks once per hour if quota is restored (minimal 1-unit API call)
- Automatically resumes when quota available
- No exponential backoff, no cooldown periods - just hourly checks
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from logger import logger
from constants import FALSE_VALUES


def _is_truthy(value: Optional[str]) -> bool:
    """Check if environment variable is truthy."""
    if value is None:
        return False
    return value.strip().lower() not in FALSE_VALUES


class QuotaManager:
    """Simple quota manager with hourly recovery checks."""

    def __init__(
        self,
        youtube_api_getter: Callable,
        db: Optional[Any] = None,
        search_wrapper: Optional[Callable] = None,
        retry_enabled: bool = True,
        retry_batch_size: int = 50,
        metrics_tracker: Optional[Any] = None,
        check_interval: int = 1800,  # Check every 30 minutes
        probe_interval: int = 3600,  # Probe every hour
    ) -> None:
        """
        Initialize quota manager.

        Args:
            youtube_api_getter: Function that returns YouTube API instance
            db: Database instance for pending video retry
            search_wrapper: Function to search YouTube for pending videos
            retry_enabled: Whether to retry pending videos after recovery
            retry_batch_size: Max pending videos to retry per recovery
            metrics_tracker: MetricsTracker instance for recording stats
            check_interval: How often thread wakes to check if should probe (seconds)
            probe_interval: How often to actually probe YouTube API (seconds)
        """
        self.youtube_api_getter = youtube_api_getter
        self.db = db
        self.search_wrapper = search_wrapper
        self.retry_enabled = retry_enabled
        self.retry_batch_size = retry_batch_size
        self.metrics_tracker = metrics_tracker
        self.check_interval = check_interval
        self.probe_interval = probe_interval
        self.enabled = True  # For backwards compatibility with quota_prober

        # State file for persistence
        quota_path = os.getenv('YTT_QUOTA_GUARD_FILE', '/config/youtube_thumbs/quota_guard.json')
        self.state_file = Path(quota_path)
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("QuotaManager could not create directory %s: %s", self.state_file.parent, exc)

        # Thread-safe lock
        self._lock = threading.Lock()
        self._last_probe_time = 0

        # Background thread
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="quota-manager", daemon=True)

        # Maybe force unlock on startup
        self._maybe_force_unlock()

        logger.info("QuotaManager initialized (probe every %ds with minimal API call)", probe_interval)

    def _load_state(self) -> Optional[Dict[str, Any]]:
        """Load state from disk."""
        if not self.state_file.exists():
            return None
        try:
            with self.state_file.open('r', encoding='utf-8') as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("QuotaManager failed to read state file %s: %s", self.state_file, exc)
            return None

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save state to disk."""
        try:
            with self.state_file.open('w', encoding='utf-8') as handle:
                json.dump(state, handle, indent=2)
        except OSError as exc:
            logger.error("QuotaManager failed to persist state: %s", exc)

    def _clear_state(self) -> None:
        """Clear state file."""
        try:
            if self.state_file.exists():
                self.state_file.unlink()
        except OSError:
            pass

    def _maybe_force_unlock(self) -> None:
        """Force unlock if environment variable is set."""
        if _is_truthy(os.getenv('YTT_FORCE_QUOTA_UNLOCK')):
            if self.state_file.exists():
                self._clear_state()
                logger.warning(
                    "YTT_FORCE_QUOTA_UNLOCK detected; cleared quota state file %s",
                    self.state_file,
                )
            else:
                logger.info("YTT_FORCE_QUOTA_UNLOCK set but no state file present")

    def _probe_youtube_api(self) -> bool:
        """
        Lightweight probe to test if YouTube API is accessible.

        Uses videos().list() with a known video ID - only 1 quota unit.

        Returns:
            True if quota is available, False if still exceeded
        """
        try:
            api = self.youtube_api_getter()
            if not api:
                logger.warning("YouTube API not available for probing")
                return False

            # Make minimal API call (1 quota unit)
            request = api.youtube.videos().list(
                part='id',
                id='dQw4w9WgXcQ',  # Rick Astley - known to exist
                maxResults=1
            )
            request.execute()

            logger.info("YouTube API probe successful - quota available")
            return True

        except Exception as e:
            error_str = str(e).lower()
            if 'quota' in error_str or 'exceeded' in error_str:
                logger.debug("YouTube API probe failed - quota still exceeded")
                return False
            else:
                # Some other error - assume quota is available
                logger.warning("YouTube API probe failed with non-quota error: %s", e)
                return True

    def _retry_pending_videos(self) -> None:
        """Retry pending videos that failed due to quota exhaustion."""
        if not self.retry_enabled:
            logger.debug("Pending video retry disabled via configuration")
            return

        if not self.db or not self.search_wrapper:
            logger.warning("Pending video retry enabled but db or search_wrapper not provided")
            return

        try:
            # Get pending videos that failed due to quota (1 at a time for safety)
            pending = self.db.get_pending_videos(
                limit=1,
                reason_filter='quota_exceeded'
            )

            if not pending:
                logger.info("No pending videos to retry after quota recovery")
                return

            logger.info("Found %d pending video(s) to retry after quota recovery", len(pending))

            success_count = 0
            not_found_count = 0
            error_count = 0

            for idx, video in enumerate(pending):
                # Rate limit: Add 60 second delay between retries (except first one)
                if idx > 0:
                    logger.info("Waiting 60 seconds before next retry to avoid quota exhaustion...")
                    time.sleep(60)

                ha_content_id = video.get('ha_content_id')
                ha_title = video.get('ha_title', 'Unknown')
                ha_duration = video.get('ha_duration')
                ha_artist = video.get('ha_artist')

                try:
                    logger.info("Retrying match for: %s (duration: %s) [%d/%d]",
                               ha_title[:50], ha_duration, idx + 1, len(pending))

                    # Search YouTube for this video
                    ha_media = {
                        'title': ha_title,
                        'artist': ha_artist,
                        'app_name': video.get('ha_app_name', 'YouTube'),
                        'duration': ha_duration
                    }
                    result = self.search_wrapper(ha_media)

                    if result:
                        # Found a match - resolve the pending video
                        youtube_data = {
                            'yt_video_id': result.get('yt_video_id'),
                            'title': result.get('title'),
                            'channel': result.get('channel'),
                            'channel_id': result.get('channel_id'),
                            'description': result.get('description'),
                            'published_at': result.get('published_at'),
                            'category_id': result.get('category_id'),
                            'live_broadcast': result.get('live_broadcast'),
                            'location': result.get('location'),
                            'recording_date': result.get('recording_date'),
                            'duration': result.get('duration'),
                            'url': result.get('url'),
                        }
                        self.db.resolve_pending_video(ha_content_id, youtube_data)
                        logger.info("✓ Successfully matched: %s → %s", ha_title[:50], result.get('yt_video_id'))
                        success_count += 1
                    else:
                        # No match found - mark as not found
                        self.db.mark_pending_not_found(ha_content_id)
                        self.db.record_not_found(ha_title, ha_artist, ha_duration, search_query=ha_title)
                        logger.info("✗ No match found for: %s", ha_title[:50])
                        not_found_count += 1

                except Exception as exc:
                    logger.error("Failed to retry pending video %s: %s", ha_content_id, exc)
                    error_count += 1

            logger.info(
                "Pending video retry complete: %d matched, %d not found, %d errors",
                success_count, not_found_count, error_count
            )

            # Record metrics
            if self.metrics_tracker:
                self.metrics_tracker.record_pending_retry(
                    total=len(pending),
                    matched=success_count,
                    not_found=not_found_count,
                    errors=error_count
                )

        except Exception as exc:
            logger.error("Failed to retry pending videos: %s", exc, exc_info=True)

    def _run(self) -> None:
        """Main background loop that periodically probes for quota restoration."""
        while not self._stop_event.is_set():
            try:
                # Check if we should probe
                if self.is_blocked():
                    now = time.time()
                    with self._lock:
                        time_since_last_probe = now - self._last_probe_time
                        should_probe = time_since_last_probe >= self.probe_interval

                        if should_probe:
                            self._last_probe_time = now

                    if should_probe:
                        logger.info("QuotaManager: Testing if YouTube quota is restored...")

                        if self._probe_youtube_api():
                            logger.info("✅ Quota restored! Clearing block and resuming operations")
                            self.reset(reason="quota_restored_via_probe")

                            # Retry pending videos
                            logger.info("Starting automatic retry of pending videos...")
                            self._retry_pending_videos()
                        else:
                            logger.info("❌ Quota still exceeded. Will retry in %d seconds", self.probe_interval)

            except Exception as exc:
                logger.error("QuotaManager background loop error: %s", exc, exc_info=True)

            # Wait before next check
            self._stop_event.wait(self.check_interval)

        logger.info("QuotaManager background thread exiting")

    # ============================================================================
    # PUBLIC API
    # ============================================================================

    def start(self) -> None:
        """Start the background quota management thread."""
        if self._thread.is_alive():
            logger.debug("QuotaManager thread already running")
            return

        # If thread died, create a new one
        if self._thread.ident is not None:
            logger.warning("QuotaManager thread died, creating new thread")
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="quota-manager", daemon=True)

        logger.info("Starting QuotaManager background thread")
        self._thread.start()

    def stop(self) -> None:
        """Stop the background quota management thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("QuotaManager stopped")

    def is_healthy(self) -> bool:
        """Check if the quota manager thread is healthy."""
        return self._thread.is_alive()

    def ensure_running(self) -> None:
        """Ensure the quota manager is running, restart if needed."""
        if not self.is_healthy():
            logger.warning("QuotaManager thread not healthy, attempting restart")
            self.start()

    def is_blocked(self) -> bool:
        """Check if quota is currently blocked."""
        state = self._load_state()
        return state is not None and state.get('blocked', False)

    def blocked_until_iso(self) -> Optional[str]:
        """Get ISO timestamp when quota block expires (always None - no time-based blocks)."""
        return None

    def remaining_seconds(self) -> int:
        """Get remaining cooldown seconds (always 0 - no time-based cooldown)."""
        return 0

    def block_message(self) -> str:
        """Get human-readable block message."""
        if self.is_blocked():
            return "YouTube quota exceeded. Checking hourly for restoration."
        return "YouTube quota available"

    def describe_block(self) -> str:
        """Get detailed block description."""
        if not self.is_blocked():
            return "No quota block in effect"
        return "YouTube quota exceeded. Checking hourly for restoration."

    def check_quota_or_skip(self, operation_name: str, *args) -> tuple:
        """
        Check if quota is blocked and log skip message if so.

        Returns:
            Tuple of (should_skip: bool, skip_reason: str)
            - (False, "") if quota is available (proceed with operation)
            - (True, reason) if quota is blocked (skip operation)
        """
        if self.is_blocked():
            logger.info("Quota blocked; skipping %s: %s", operation_name, self.describe_block())
            return True, self.describe_block()
        return False, ""

    def status(self) -> Dict[str, Any]:
        """Get current quota status."""
        blocked = self.is_blocked()
        if not blocked:
            return {
                "blocked": False,
                "blocked_until": None,
                "remaining_seconds": 0,
                "reason": None,
                "detail": None,
                "message": "YouTube quota available",
            }

        state = self._load_state()
        return {
            "blocked": True,
            "blocked_until": None,  # No time-based blocks
            "remaining_seconds": 0,  # No countdown
            "reason": state.get('reason', 'quotaExceeded'),
            "detail": state.get('detail'),
            "message": "YouTube quota exceeded. Checking hourly for restoration.",
        }

    def record_success(self) -> None:
        """Record a successful API call (no-op in simplified version)."""
        pass

    def trip(self, reason: str, context: Optional[str] = None, detail: Optional[str] = None) -> None:
        """Block API calls due to quota exceeded."""
        now = datetime.now(timezone.utc)

        state = {
            "blocked": True,
            "reason": reason or "quotaExceeded",
            "context": context,
            "detail": detail,
            "blocked_at": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        self._save_state(state)

        logger.error(
            "YouTube quota exceeded (%s). Blocking API calls and checking hourly for restoration. Context: %s | Detail: %s",
            state["reason"],
            context or "n/a",
            detail or "n/a",
        )

    def reset(self, reason: Optional[str] = None) -> None:
        """Clear the quota block."""
        self._clear_state()
        with self._lock:
            self._last_probe_time = 0
        logger.info("QuotaManager reset: %s", reason or "manual request")


# Thread-safe singleton implementation
_quota_manager_instance = None
_quota_manager_lock = threading.Lock()


def get_quota_manager() -> QuotaManager:
    """Get the thread-safe singleton instance of QuotaManager."""
    global _quota_manager_instance
    if _quota_manager_instance is None:
        with _quota_manager_lock:
            if _quota_manager_instance is None:
                raise RuntimeError("QuotaManager not initialized. Call init_quota_manager() first.")
    return _quota_manager_instance


def init_quota_manager(
    youtube_api_getter: Callable,
    db: Optional[Any] = None,
    search_wrapper: Optional[Callable] = None,
    retry_enabled: bool = True,
    retry_batch_size: int = 50,
    metrics_tracker: Optional[Any] = None,
) -> QuotaManager:
    """
    Initialize the global QuotaManager instance.

    Must be called once during application startup before get_quota_manager().
    """
    global _quota_manager_instance
    if _quota_manager_instance is None:
        with _quota_manager_lock:
            if _quota_manager_instance is None:
                _quota_manager_instance = QuotaManager(
                    youtube_api_getter=youtube_api_getter,
                    db=db,
                    search_wrapper=search_wrapper,
                    retry_enabled=retry_enabled,
                    retry_batch_size=retry_batch_size,
                    metrics_tracker=metrics_tracker,
                )
    return _quota_manager_instance


# For backwards compatibility with quota_guard.quota_guard
quota_guard = None  # Will be set after init_quota_manager() is called


def set_quota_guard_compat():
    """Set the global quota_guard variable for backwards compatibility."""
    global quota_guard
    quota_guard = get_quota_manager()
