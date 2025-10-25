import os
from typing import List, Dict, Optional

import requests

from logger import logger


class InvidiousClient:
    """Lightweight client for the public Invidious API."""

    def __init__(self) -> None:
        raw_enabled = os.getenv('USE_INVIDIOUS_SEARCH', 'false').lower()
        self.enabled = raw_enabled not in ('', '0', 'false', 'no', 'off', 'null')
        self.base_url = (os.getenv('INVIDIOUS_BASE_URL') or '').strip().rstrip('/')
        self.timeout = self._resolve_timeout()
        self.session = requests.Session()

        if self.enabled and not self.base_url:
            logger.warning("USE_INVIDIOUS_SEARCH is true but INVIDIOUS_BASE_URL is empty; disabling fallback search.")
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

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.base_url)

    def search_videos(self, query: str, expected_duration: Optional[int] = None, max_results: int = 15) -> Optional[List[Dict]]:
        if not self.is_enabled():
            return None

        url = f"{self.base_url}/api/v1/search"
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
            logger.warning("Invidious search failed for '%s': %s", query, exc)
            return None
        except ValueError as exc:
            logger.warning("Invidious search returned invalid JSON for '%s': %s", query, exc)
            return None

        if not isinstance(data, list):
            logger.warning("Invidious search expected a list but received %s", type(data))
            return None

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

        if candidates:
            logger.info(
                "Invidious returned %s candidate(s) for '%s'%s",
                len(candidates),
                query,
                f" at {self.base_url}" if self.base_url else "",
            )
            return candidates

        logger.warning("Invidious returned no candidates for '%s' with expected duration %s", query, expected_duration)
        return None


invidious_client: Optional[InvidiousClient] = None


def get_invidious_client() -> InvidiousClient:
    global invidious_client
    if invidious_client is None:
        invidious_client = InvidiousClient()
    return invidious_client
