import fcntl
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from logger import logger
from constants import FALSE_VALUES


def _is_truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in FALSE_VALUES


class QuotaGuard:
    """Persisted circuit breaker when YouTube reports quotaExceeded with exponential backoff."""

    # Exponential backoff periods in seconds: 2h → 4h → 8h → 16h → 24h
    BACKOFF_PERIODS = [7200, 14400, 28800, 57600, 86400]  # 2h, 4h, 8h, 16h, 24h
    BASE_SUCCESS_THRESHOLD = 10  # Base number of successes before resetting attempts

    def _get_adaptive_threshold(self, attempt_number: int) -> int:
        """Calculate adaptive success threshold based on attempt number."""
        # Lower threshold for higher attempts to help recovery
        # Attempts 1-2: 10 successes
        # Attempts 3-4: 5 successes
        # Attempts 5+: 3 successes
        if attempt_number <= 2:
            return self.BASE_SUCCESS_THRESHOLD
        elif attempt_number <= 4:
            return 5
        else:
            return 3

    def __init__(self) -> None:
        self.base_cooldown_seconds = self._resolve_cooldown()
        quota_path = os.getenv('YTT_QUOTA_GUARD_FILE', '/config/youtube_thumbs/quota_guard.json')
        self.state_file = Path(quota_path)
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("QuotaGuard could not create directory %s: %s", self.state_file.parent, exc)
        self._maybe_force_unlock()
        self._lock = threading.Lock()
        self._last_probe_time = 0
        self._probe_interval = 3600  # Probe once per hour during cooldown

    @staticmethod
    def _resolve_cooldown() -> int:
        """Resolve base cooldown period from environment variable."""
        raw = os.getenv('YTT_QUOTA_COOLDOWN_SECONDS', '7200')  # Default to 2 hours
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid YTT_QUOTA_COOLDOWN_SECONDS '%s'; defaulting to 7200", raw)
            return 7200
        return max(value, 60)

    def _calculate_backoff_seconds(self, attempt_number: int) -> int:
        """Calculate exponential backoff based on attempt number."""
        if attempt_number <= 0:
            return self.base_cooldown_seconds

        # Use predefined backoff periods
        index = min(attempt_number - 1, len(self.BACKOFF_PERIODS) - 1)
        backoff_seconds = self.BACKOFF_PERIODS[index]

        # Allow override from environment
        if self.base_cooldown_seconds > backoff_seconds:
            return self.base_cooldown_seconds

        return backoff_seconds

    def _should_decay_attempts(self, state: Dict[str, Any]) -> bool:
        """Check if attempts should decay due to prolonged quiescence."""
        set_at = state.get('set_at')
        if not set_at:
            return False

        try:
            set_time = datetime.strptime(set_at, '%Y-%m-%dT%H:%M:%SZ')
            hours_since_set = (datetime.utcnow() - set_time).total_seconds() / 3600

            # Decay attempts if blocked for over 6 hours without new failures
            if hours_since_set > 6:
                return True

            # Auto-reset if blocked for over 48 hours
            if hours_since_set > 48:
                logger.info("Auto-resetting quota guard after 48 hours of lockout")
                return True

        except (ValueError, TypeError) as exc:
            logger.debug("Failed to parse set_at timestamp: %s", exc)

        return False

    def _apply_attempt_decay(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply attempt decay to reduce lockout duration over time."""
        if self._should_decay_attempts(state):
            current_attempts = state.get('attempt_number', 0)
            if current_attempts > 0:
                # Reduce by 1 attempt every 6 hours of inactivity
                set_time = datetime.strptime(state['set_at'], '%Y-%m-%dT%H:%M:%SZ')
                hours_elapsed = (datetime.utcnow() - set_time).total_seconds() / 3600
                decay_amount = int(hours_elapsed / 6)  # 1 attempt per 6 hours

                new_attempts = max(0, current_attempts - decay_amount)
                if new_attempts != current_attempts:
                    logger.info(
                        "Decaying attempt counter from %d to %d after %.1f hours of inactivity",
                        current_attempts, new_attempts, hours_elapsed
                    )
                    state['attempt_number'] = new_attempts

                # Full reset after 48 hours
                if hours_elapsed > 48:
                    state['attempt_number'] = 0
                    state['success_count'] = 0
                    logger.info("Auto-reset quota guard after 48 hours")

        return state

    def _load_state(self) -> Optional[Dict[str, Any]]:
        if not self.state_file.exists():
            return None
        try:
            with self.state_file.open('r', encoding='utf-8') as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("QuotaGuard failed to read state file %s: %s", self.state_file, exc)
            return None

    def _save_state(self, state: Dict[str, Any]) -> None:
        try:
            with self.state_file.open('w', encoding='utf-8') as handle:
                json.dump(state, handle, indent=2)
        except OSError as exc:
            logger.error("QuotaGuard failed to persist state: %s", exc)

    def _clear_state(self) -> None:
        try:
            if self.state_file.exists():
                self.state_file.unlink()
        except OSError:
            pass

    def reset(self, reason: Optional[str] = None) -> None:
        """Manually clear the cooldown file."""
        self._clear_state()
        with self._lock:
            self._last_probe_time = 0
        logger.info("QuotaGuard reset: %s", reason or "manual request")

    def should_probe_for_recovery(self) -> bool:
        """Check if we should attempt a probe to see if quota is restored."""
        if not self.is_blocked():
            return False

        now = time.time()
        with self._lock:
            time_since_last_probe = now - self._last_probe_time
            if time_since_last_probe >= self._probe_interval:
                self._last_probe_time = now
                return True
        return False

    def attempt_recovery_probe(self, probe_func) -> bool:
        """
        Attempt to probe YouTube API to check if quota is restored.

        Args:
            probe_func: Callable that returns True if API is accessible, False otherwise

        Returns:
            True if quota is restored and guard was cleared, False otherwise
        """
        if not self.is_blocked():
            return False

        logger.info("QuotaGuard: Probing YouTube API to check if quota is restored...")

        try:
            if probe_func():
                logger.info("QuotaGuard: Probe successful! Quota appears to be restored. Clearing cooldown.")
                self.reset(reason="quota_restored_via_probe")
                return True
            else:
                logger.info("QuotaGuard: Probe failed, quota still exceeded. Will retry in %d seconds.",
                           self._probe_interval)
                return False
        except Exception as exc:
            logger.warning("QuotaGuard: Probe failed with error: %s", exc)
            return False

    def _maybe_force_unlock(self) -> None:
        if _is_truthy(os.getenv('YTT_FORCE_QUOTA_UNLOCK')):
            if self.state_file.exists():
                self._clear_state()
                logger.warning(
                    "YTT_FORCE_QUOTA_UNLOCK detected; cleared quota guard file %s",
                    self.state_file,
                )
            else:
                logger.info("YTT_FORCE_QUOTA_UNLOCK set but no cooldown file present")

    def _state_with_remaining(self) -> Tuple[Optional[Dict[str, Any]], int]:
        state = self._load_state()
        if not state:
            return None, 0

        blocked_until = state.get('blocked_until_epoch')
        if not blocked_until:
            logger.warning(
                "QuotaGuard state missing 'blocked_until_epoch'; clearing %s",
                self.state_file,
            )
            self._clear_state()
            return None, 0

        remaining = int(blocked_until - time.time())
        if remaining <= 0:
            logger.info(
                "Quota cooldown expired at %s UTC; clearing guard file %s",
                state.get('blocked_until_iso', 'unknown'),
                self.state_file,
            )
            self._clear_state()
            return None, 0

        return state, remaining

    def is_blocked(self) -> bool:
        state, remaining = self._state_with_remaining()
        return bool(state and remaining > 0)

    def blocked_until_iso(self) -> Optional[str]:
        status = self.status()
        return status.get('blocked_until') if status.get('blocked') else None

    def remaining_seconds(self) -> int:
        return self.status().get('remaining_seconds', 0)

    def block_message(self) -> str:
        return self.status().get('message', "YouTube quota available")

    def describe_block(self) -> str:
        if not self.is_blocked():
            return "No quota cooldown in effect"
        status = self.status()
        remaining = status.get('remaining_seconds', 0)
        blocked_until = status.get('blocked_until')
        return f"Cooldown active until {blocked_until} UTC ({remaining // 3600}h remaining)."

    def status(self) -> Dict[str, Any]:
        state, remaining = self._state_with_remaining()

        # Apply attempt decay when checking status
        if state:
            state = self._apply_attempt_decay(state)

        blocked = bool(state and remaining > 0)
        if not blocked:
            return {
                "blocked": False,
                "blocked_until": None,
                "remaining_seconds": 0,
                "reason": None,
                "detail": None,
                "attempt_number": 0,
                "success_count": 0,
                "message": "YouTube quota available",
            }

        reason = state.get('reason', 'quotaExceeded')
        blocked_until = state.get('blocked_until_iso', 'unknown time')
        attempt_number = state.get('attempt_number', 1)
        success_count = state.get('success_count', 0)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return {
            "blocked": True,
            "blocked_until": blocked_until,
            "remaining_seconds": remaining,
            "reason": reason,
            "detail": state.get('detail'),
            "attempt_number": attempt_number,
            "success_count": success_count,
            "message": (
                f"YouTube quota exhausted ({reason}). "
                f"Attempt {attempt_number}, cooldown active for {hours}h{minutes:02d}m; "
                f"access resumes at {blocked_until} UTC."
            ),
        }

    def record_success(self) -> None:
        """Record a successful API call and potentially reset attempts."""
        if not self.state_file.exists():
            return

        try:
            with self.state_file.open('r+', encoding='utf-8') as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    handle.seek(0)
                    state = json.load(handle)

                    # Increment success count
                    success_count = state.get('success_count', 0) + 1
                    state['success_count'] = success_count

                    # Check if we should reset attempts using adaptive threshold
                    attempt_number = state.get('attempt_number', 0)
                    threshold = self._get_adaptive_threshold(attempt_number)
                    if success_count >= threshold:
                        logger.info(
                            "QuotaGuard: %d successful API calls recorded, resetting attempt counter from %d",
                            success_count,
                            state.get('attempt_number', 0)
                        )
                        # Reset attempts but keep state for monitoring
                        state['attempt_number'] = 0
                        state['success_count'] = 0

                    # Write back to file
                    handle.seek(0)
                    json.dump(state, handle, indent=2)
                    handle.truncate()
                except (json.JSONDecodeError, OSError) as e:
                    logger.error("Failed to update success count: %s", e)
                finally:
                    # Always release the lock
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            logger.error("Failed to record success: %s", exc)

    def trip(self, reason: str, context: Optional[str] = None, detail: Optional[str] = None) -> None:
        """Trip the circuit breaker with exponential backoff."""
        now = datetime.utcnow()
        existing = self._load_state() or {}

        # Apply attempt decay before processing new trip
        existing = self._apply_attempt_decay(existing)

        # Only increment attempt if previous cooldown has expired
        existing_epoch = existing.get('blocked_until_epoch', 0)
        if existing_epoch > now.timestamp():
            # Still in cooldown - don't increment attempt, just extend if needed
            attempt_number = existing.get('attempt_number', 1)
            logger.info(
                "Quota error during existing cooldown (attempt %d), maintaining backoff period",
                attempt_number
            )
        else:
            # Cooldown expired - this is a new failure
            attempt_number = existing.get('attempt_number', 0) + 1

        cooldown_seconds = self._calculate_backoff_seconds(attempt_number)

        block_until = now + timedelta(seconds=cooldown_seconds)
        existing_epoch = existing.get('blocked_until_epoch', 0)

        # If already blocked and the existing block is longer, keep it
        if existing_epoch and existing_epoch > block_until.timestamp():
            block_until = datetime.utcfromtimestamp(existing_epoch)
            cooldown_seconds = int(existing_epoch - now.timestamp())

        state = {
            "reason": reason or "quotaExceeded",
            "context": context,
            "detail": detail,
            "blocked_until_epoch": block_until.timestamp(),
            "blocked_until_iso": block_until.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "cooldown_seconds": cooldown_seconds,
            "attempt_number": attempt_number,
            "success_count": 0,  # Reset success count on failure
            "set_at": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        self._save_state(state)

        # Log with backoff information
        backoff_info = f" (attempt {attempt_number}, exponential backoff)" if attempt_number > 1 else ""
        logger.error(
            "YouTube quota exceeded (%s)%s. Blocking API usage for %s seconds (until %s UTC). Context: %s | Detail: %s",
            state["reason"],
            backoff_info,
            state["cooldown_seconds"],
            state["blocked_until_iso"],
            context or "n/a",
            detail or "n/a",
        )


# Thread-safe singleton implementation
_quota_guard_instance = None
_quota_guard_lock = threading.Lock()

def get_quota_guard() -> QuotaGuard:
    """Get the thread-safe singleton instance of QuotaGuard."""
    global _quota_guard_instance
    if _quota_guard_instance is None:
        with _quota_guard_lock:
            # Double-check locking pattern
            if _quota_guard_instance is None:
                _quota_guard_instance = QuotaGuard()
    return _quota_guard_instance

# For backwards compatibility, create the instance
quota_guard = get_quota_guard()
