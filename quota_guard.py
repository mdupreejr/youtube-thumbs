import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from logger import logger


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

    @staticmethod
    def _resolve_cooldown() -> int:
        raw = os.getenv('YTT_QUOTA_COOLDOWN_SECONDS', '86400')
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid YTT_QUOTA_COOLDOWN_SECONDS '%s'; defaulting to 86400", raw)
            return 86400
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

    def is_blocked(self) -> bool:
        state = self._load_state()
        if not state:
            return False

        blocked_until = state.get('blocked_until_epoch')
        if not blocked_until:
            self._clear_state()
            return False

        if time.time() >= blocked_until:
            self._clear_state()
            return False

        return True

    def blocked_until_iso(self) -> Optional[str]:
        state = self._load_state()
        if not state:
            return None
        return state.get('blocked_until_iso')

    def remaining_seconds(self) -> int:
        state = self._load_state()
        if not state:
            return 0
        blocked_until = state.get('blocked_until_epoch', 0)
        remaining = int(blocked_until - time.time())
        if remaining <= 0:
            self._clear_state()
            return 0
        return remaining

    def block_message(self) -> str:
        state = self._load_state()
        if not state:
            return "YouTube quota available"

        reason = state.get('reason', 'quotaExceeded')
        blocked_until = state.get('blocked_until_iso', 'unknown time')
        remaining = self.remaining_seconds()
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return (
            f"YouTube quota exhausted ({reason}). "
            f"Cooldown active for {hours}h{minutes:02d}m; access resumes at {blocked_until} UTC."
        )

    def describe_block(self) -> str:
        if not self.is_blocked():
            return "No quota cooldown in effect"
        remaining = self.remaining_seconds()
        blocked_until = self.blocked_until_iso()
        return f"Cooldown active until {blocked_until} UTC ({remaining // 3600}h remaining)."

    def trip(self, reason: str, context: Optional[str] = None, detail: Optional[str] = None) -> None:
        block_until = datetime.utcnow() + timedelta(seconds=self.cooldown_seconds)
        state = {
            "reason": reason or "quotaExceeded",
            "context": context,
            "detail": detail,
            "blocked_until_epoch": block_until.timestamp(),
            "blocked_until_iso": block_until.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "cooldown_seconds": self.cooldown_seconds,
            "set_at": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        self._save_state(state)
        logger.error(
            "YouTube quota exceeded (%s). Blocking API usage for %s seconds (until %s UTC). Context: %s",
            state["reason"],
            self.cooldown_seconds,
            state["blocked_until_iso"],
            context or "n/a",
        )


quota_guard = QuotaGuard()
