import os
import time
from typing import List, Dict, Optional, Tuple

import requests

from logger import logger


class InvidiousClient:
    """Lightweight client for the public Invidious API with instance rotation."""

    DISABLED_VALUES = {'', '0', 'false', 'no', 'off', 'null'}

    def __init__(self) -> None:
        raw_enabled = os.getenv('USE_INVIDIOUS_SEARCH', 'false').strip().lower()
        self.enabled = raw_enabled not in self.DISABLED_VALUES
        self.timeout = self._resolve_timeout()
        self.instance_backoff = self._resolve_instance_cooldown()
        self.session = requests.Session()
        self.instances = self._collect_instances()
        self._last_index = -1

        if self.enabled and not self.instances:
            logger.warning(
                "USE_INVIDIOUS_SEARCH is true but no INVIDIOUS_BASE_URL(S) were provided; disabling fallback search."
            )
            self.enabled = False

    @staticmethod
    def _resolve_timeout() -> float:
        raw = os.getenv('INVIDIOUS_TIMEOUT_SECONDS', '8')
        try:
            value = float(raw)
        except ValueError:
            logger.warning("Invalid INVIDIOUS_TIMEOUT_SECONDS '%s'; defaulting to 8 seconds", raw)
            return 8.0
        return max(value, 1.0)

    @staticmethod
    def _resolve_instance_cooldown() -> int:
        raw = os.getenv('INVIDIOUS_INSTANCE_COOLDOWN_SECONDS', '300')
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid INVIDIOUS_INSTANCE_COOLDOWN_SECONDS '%s'; defaulting to 300 seconds", raw)
            return 300
        return max(value, 30)

    def _collect_instances(self) -> List[Dict[str, float]]:
        urls: List[str] = []
        multi = os.getenv('INVIDIOUS_BASE_URLS')
        single = os.getenv('INVIDIOUS_BASE_URL')

        if multi:
            urls.extend(self._split_urls(multi))
        if single:
            urls.extend(self._split_urls(single))

        cleaned: List[str] = []
        for url in urls:
            normalized = url.strip().rstrip('/')
            if not normalized:
                continue
            if not normalized.startswith('http://') and not normalized.startswith('https://'):
                normalized = f"https://{normalized}"
            if normalized not in cleaned:
                cleaned.append(normalized)

        return [{"url": url, "backoff_until": 0.0} for url in cleaned]

    @staticmethod
    def _split_urls(raw: str) -> List[str]:
        parts: List[str] = []
        for segment in raw.replace('\n', ',').split(','):
            trimmed = segment.strip()
            if trimmed:
                parts.append(trimmed)
        return parts

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.instances)

    def search_videos(self, query: str, expected_duration: Optional[int] = None, max_results: int = 15) -> Optional[List[Dict]]:
        if not self.is_enabled():
            return None

        attempts = len(self.instances)
        index = self._last_index
        for _ in range(attempts):
            index = (index + 1) % len(self.instances)
            instance = self.instances[index]
            if instance['backoff_until'] > time.time():
                continue

            success, candidates = self._query_instance(instance, query, expected_duration, max_results)
            if success and candidates:
                self._last_index = index
                logger.info(
                    "Invidious (%s) returned %s candidate(s) for '%s'",
                    instance['url'],
                    len(candidates),
                    query,
                )
                return candidates

            if success:
                # No matches, try the next instance but do not penalize.
                continue

            # Failure: apply backoff and continue
            instance['backoff_until'] = time.time() + self.instance_backoff
            logger.warning(
                "Invidious instance %s back-off for %ss after failure",
                instance['url'],
                self.instance_backoff,
            )

        return None

    def _query_instance(
        self,
        instance: Dict[str, float],
        query: str,
        expected_duration: Optional[int],
        max_results: int,
    ) -> Tuple[bool, Optional[List[Dict]]]:
        url = f"{instance['url']}/api/v1/search"
        params = {
            'q': query,
            'type': 'video',
            'region': os.getenv('INVIDIOUS_REGION', 'US'),
            'page': 1,
            'sort_by': os.getenv('INVIDIOUS_SORT_BY', 'relevance'),
        }

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.warning("Invidious search failed for '%s' via %s: %s", query, instance['url'], exc)
            return False, None
        except ValueError as exc:
            logger.warning("Invidious search returned invalid JSON for '%s' via %s: %s", query, instance['url'], exc)
            return False, None

        if not isinstance(data, list):
            logger.warning("Invidious search expected a list but received %s from %s", type(data), instance['url'])
            return False, None

        candidates: List[Dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get('type') != 'video':
                continue

            duration_seconds = item.get('lengthSeconds')
            try:
                duration = int(duration_seconds) if duration_seconds is not None else None
            except (TypeError, ValueError):
                duration = None

            candidate = {
                'video_id': item.get('videoId'),
                'title': item.get('title'),
                'channel': item.get('author'),
                'artist': item.get('author'),
                'duration': duration,
            }

            if not candidate['video_id'] or not candidate['title']:
                continue

            if expected_duration is not None and duration is not None:
                if abs(duration - expected_duration) > 2:
                    continue

            candidates.append(candidate)

            if len(candidates) >= max_results:
                break

        return True, candidates if candidates else []


invidious_client: Optional[InvidiousClient] = None


def get_invidious_client() -> InvidiousClient:
    global invidious_client
    if invidious_client is None:
        invidious_client = InvidiousClient()
    return invidious_client
