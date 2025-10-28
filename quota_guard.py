import json
import os
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
    """Persisted circuit breaker when YouTube reports quotaExceeded."""

    def __init__(self) -> None:
        self.cooldown_seconds = self._resolve_cooldown()
        quota_path = os.getenv('YTT_QUOTA_GUARD_FILE', '/config/youtube_thumbs/quota_guard.json')
        self.state_file = Path(quota_path)
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("QuotaGuard could not create directory %s: %s", self.state_file.parent, exc)
        self._maybe_force_unlock()

    @staticmethod
    def _resolve_cooldown() -> int:
        raw = os.getenv('YTT_QUOTA_COOLDOWN_SECONDS', '43200')
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid YTT_QUOTA_COOLDOWN_SECONDS '%s'; defaulting to 43200", raw)
            return 43200
        return max(value, 60)

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
        logger.info("QuotaGuard reset: %s", reason or "manual request")

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
        blocked = bool(state and remaining > 0)
        if not blocked:
            return {
                "blocked": False,
                "blocked_until": None,
                "remaining_seconds": 0,
                "reason": None,
                "detail": None,
                "message": "YouTube quota available",
            }

        reason = state.get('reason', 'quotaExceeded')
        blocked_until = state.get('blocked_until_iso', 'unknown time')
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return {
            "blocked": True,
            "blocked_until": blocked_until,
            "remaining_seconds": remaining,
            "reason": reason,
            "detail": state.get('detail'),
            "message": (
                f"YouTube quota exhausted ({reason}). "
                f"Cooldown active for {hours}h{minutes:02d}m; access resumes at {blocked_until} UTC."
            ),
        }

    def trip(self, reason: str, context: Optional[str] = None, detail: Optional[str] = None) -> None:
        now = datetime.utcnow()
        block_until = now + timedelta(seconds=self.cooldown_seconds)
        existing = self._load_state() or {}
        existing_epoch = existing.get('blocked_until_epoch', 0)
        if existing_epoch and existing_epoch > block_until.timestamp():
            block_until = datetime.utcfromtimestamp(existing_epoch)

        block_duration = max(int(block_until.timestamp() - now.timestamp()), 0)

        state = {
            "reason": reason or "quotaExceeded",
            "context": context,
            "detail": detail,
            "blocked_until_epoch": block_until.timestamp(),
            "blocked_until_iso": block_until.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "cooldown_seconds": block_duration or self.cooldown_seconds,
            "set_at": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        self._save_state(state)
        logger.error(
            "YouTube quota exceeded (%s). Blocking API usage for %s seconds (until %s UTC). Context: %s | Detail: %s",
            state["reason"],
            state["cooldown_seconds"],
            state["blocked_until_iso"],
            context or "n/a",
            detail or "n/a",
        )


quota_guard = QuotaGuard()
