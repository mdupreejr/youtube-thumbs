"""
Metrics tracking for YouTube Thumbs addon.
Tracks API usage, cache performance, and system health metrics.
"""
import time
import threading
from datetime import datetime, timedelta
from collections import deque, defaultdict
from typing import Dict, Any, Optional, List, Tuple
from logger import logger


class MetricsTracker:
    """Tracks and reports application metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()

        # API call tracking
        self._api_calls = deque(maxlen=10000)  # Store last 10k API calls
        self._api_calls_by_type = defaultdict(deque)

        # Cache performance tracking
        self._cache_hits = deque(maxlen=10000)
        self._cache_misses = deque(maxlen=10000)
        self._fuzzy_matches = deque(maxlen=1000)

        # Failed searches tracking
        self._failed_searches = deque(maxlen=1000)
        self._not_found_cache_hits = deque(maxlen=1000)

        # Rating operations tracking
        self._ratings_success = deque(maxlen=1000)
        self._ratings_failed = deque(maxlen=1000)
        self._ratings_queued = deque(maxlen=1000)

        # Quota tracking
        self._quota_trips = deque(maxlen=100)
        self._quota_recoveries = deque(maxlen=100)

        # YouTube search tracking
        self._search_queries = deque(maxlen=1000)
        self._search_results_count = defaultdict(int)

        # Batch operations tracking
        self._batch_operations = deque(maxlen=100)

    def record_api_call(self, api_type: str, success: bool = True, duration_ms: Optional[float] = None):
        """Record an API call."""
        with self._lock:
            timestamp = time.time()
            call_data = {
                'timestamp': timestamp,
                'type': api_type,
                'success': success,
                'duration_ms': duration_ms
            }
            self._api_calls.append(call_data)
            self._api_calls_by_type[api_type].append(call_data)

    def record_cache_hit(self, cache_type: str = 'exact'):
        """Record a cache hit."""
        with self._lock:
            self._cache_hits.append({
                'timestamp': time.time(),
                'type': cache_type
            })

    def record_cache_miss(self):
        """Record a cache miss."""
        with self._lock:
            self._cache_misses.append({
                'timestamp': time.time()
            })

    def record_fuzzy_match(self, query: str, matched_title: str, similarity: float):
        """Record a fuzzy match."""
        with self._lock:
            self._fuzzy_matches.append({
                'timestamp': time.time(),
                'query': query,
                'matched': matched_title,
                'similarity': similarity
            })

    def record_failed_search(self, title: str, artist: Optional[str] = None, reason: str = 'not_found'):
        """Record a failed search."""
        with self._lock:
            self._failed_searches.append({
                'timestamp': time.time(),
                'title': title,
                'artist': artist,
                'reason': reason
            })

    def record_not_found_cache_hit(self, title: str):
        """Record when a search is skipped due to not-found cache."""
        with self._lock:
            self._not_found_cache_hits.append({
                'timestamp': time.time(),
                'title': title
            })

    def record_rating(self, success: bool, queued: bool = False):
        """Record a rating operation."""
        with self._lock:
            timestamp = time.time()
            if queued:
                self._ratings_queued.append({'timestamp': timestamp})
            elif success:
                self._ratings_success.append({'timestamp': timestamp})
            else:
                self._ratings_failed.append({'timestamp': timestamp})

    def record_quota_trip(self, context: str, detail: str):
        """Record a quota trip event."""
        with self._lock:
            self._quota_trips.append({
                'timestamp': time.time(),
                'context': context,
                'detail': detail
            })

    def record_quota_recovery(self):
        """Record successful quota recovery."""
        with self._lock:
            self._quota_recoveries.append({
                'timestamp': time.time()
            })

    def record_search_query(self, query: str, results_count: int):
        """Record a search query and results count."""
        with self._lock:
            self._search_queries.append({
                'timestamp': time.time(),
                'query': query,
                'results': results_count
            })
            self._search_results_count[results_count] += 1

    def record_batch_operation(self, batch_size: int, success_count: int):
        """Record a batch operation."""
        with self._lock:
            self._batch_operations.append({
                'timestamp': time.time(),
                'batch_size': batch_size,
                'success_count': success_count,
                'success_rate': success_count / batch_size if batch_size > 0 else 0
            })

    def _count_recent(self, data_queue: deque, seconds: int) -> int:
        """Count items in queue within the last N seconds."""
        cutoff = time.time() - seconds
        count = 0
        for item in reversed(data_queue):
            if item.get('timestamp', 0) < cutoff:
                break
            count += 1
        return count

    def _get_rate(self, data_queue: deque, period_seconds: int) -> float:
        """Calculate rate per minute for items in the last period."""
        count = self._count_recent(data_queue, period_seconds)
        return (count / period_seconds) * 60 if period_seconds > 0 else 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        with self._lock:
            total_hits = len(self._cache_hits)
            total_misses = len(self._cache_misses)
            total_requests = total_hits + total_misses

            # Calculate hit rates for different time periods
            hits_1h = self._count_recent(self._cache_hits, 3600)
            misses_1h = self._count_recent(self._cache_misses, 3600)
            total_1h = hits_1h + misses_1h

            hits_24h = self._count_recent(self._cache_hits, 86400)
            misses_24h = self._count_recent(self._cache_misses, 86400)
            total_24h = hits_24h + misses_24h

            return {
                'total': {
                    'hits': total_hits,
                    'misses': total_misses,
                    'requests': total_requests,
                    'hit_rate': (total_hits / total_requests * 100) if total_requests > 0 else 0
                },
                'last_hour': {
                    'hits': hits_1h,
                    'misses': misses_1h,
                    'requests': total_1h,
                    'hit_rate': (hits_1h / total_1h * 100) if total_1h > 0 else 0
                },
                'last_24h': {
                    'hits': hits_24h,
                    'misses': misses_24h,
                    'requests': total_24h,
                    'hit_rate': (hits_24h / total_24h * 100) if total_24h > 0 else 0
                },
                'fuzzy_matches': {
                    'total': len(self._fuzzy_matches),
                    'last_hour': self._count_recent(self._fuzzy_matches, 3600)
                },
                'not_found_cache_hits': {
                    'total': len(self._not_found_cache_hits),
                    'last_hour': self._count_recent(self._not_found_cache_hits, 3600)
                }
            }

    def get_api_stats(self) -> Dict[str, Any]:
        """Get API usage statistics."""
        with self._lock:
            # Overall API stats
            total_calls = len(self._api_calls)
            calls_1m = self._count_recent(self._api_calls, 60)
            calls_1h = self._count_recent(self._api_calls, 3600)
            calls_24h = self._count_recent(self._api_calls, 86400)

            # Success rate calculation
            success_count = sum(1 for call in self._api_calls if call.get('success', False))
            success_rate = (success_count / total_calls * 100) if total_calls > 0 else 0

            # API calls by type
            by_type = {}
            for api_type, calls in self._api_calls_by_type.items():
                type_total = len(calls)
                if type_total > 0:
                    by_type[api_type] = {
                        'total': type_total,
                        'last_hour': self._count_recent(calls, 3600),
                        'rate_per_minute': self._get_rate(calls, 3600)
                    }

            return {
                'total_calls': total_calls,
                'calls_per_minute': calls_1m,
                'calls_per_hour': calls_1h,
                'calls_last_24h': calls_24h,
                'success_rate': success_rate,
                'by_type': by_type,
                'quota': {
                    'trips': len(self._quota_trips),
                    'recoveries': len(self._quota_recoveries),
                    'last_trip': self._quota_trips[-1] if self._quota_trips else None,
                    'last_recovery': self._quota_recoveries[-1] if self._quota_recoveries else None
                }
            }

    def get_rating_stats(self) -> Dict[str, Any]:
        """Get rating operation statistics."""
        with self._lock:
            return {
                'success': {
                    'total': len(self._ratings_success),
                    'last_hour': self._count_recent(self._ratings_success, 3600),
                    'rate_per_minute': self._get_rate(self._ratings_success, 3600)
                },
                'failed': {
                    'total': len(self._ratings_failed),
                    'last_hour': self._count_recent(self._ratings_failed, 3600)
                },
                'queued': {
                    'total': len(self._ratings_queued),
                    'last_hour': self._count_recent(self._ratings_queued, 3600)
                },
                'total_operations': len(self._ratings_success) + len(self._ratings_failed) + len(self._ratings_queued)
            }

    def get_search_stats(self) -> Dict[str, Any]:
        """Get search operation statistics."""
        with self._lock:
            failed_by_reason = defaultdict(int)
            for search in self._failed_searches:
                failed_by_reason[search.get('reason', 'unknown')] += 1

            # Get most common failed searches
            failed_titles = defaultdict(int)
            for search in self._failed_searches:
                failed_titles[search.get('title', '')] += 1

            top_failed = sorted(
                failed_titles.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]

            return {
                'total_searches': len(self._search_queries),
                'failed_searches': {
                    'total': len(self._failed_searches),
                    'last_hour': self._count_recent(self._failed_searches, 3600),
                    'by_reason': dict(failed_by_reason),
                    'top_failed_titles': [
                        {'title': title, 'count': count}
                        for title, count in top_failed
                    ]
                },
                'results_distribution': dict(self._search_results_count),
                'batch_operations': {
                    'total': len(self._batch_operations),
                    'average_batch_size': sum(op['batch_size'] for op in self._batch_operations) / len(self._batch_operations) if self._batch_operations else 0,
                    'average_success_rate': sum(op['success_rate'] for op in self._batch_operations) / len(self._batch_operations) if self._batch_operations else 0
                }
            }

    def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        uptime_seconds = time.time() - self._start_time
        uptime_hours = uptime_seconds / 3600
        uptime_days = uptime_hours / 24

        return {
            'uptime': {
                'seconds': int(uptime_seconds),
                'hours': round(uptime_hours, 2),
                'days': round(uptime_days, 2)
            },
            'start_time': datetime.fromtimestamp(self._start_time).isoformat()
        }

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics in a single call."""
        return {
            'timestamp': datetime.now().isoformat(),
            'cache': self.get_cache_stats(),
            'api': self.get_api_stats(),
            'ratings': self.get_rating_stats(),
            'search': self.get_search_stats(),
            'system': self.get_system_stats()
        }

    def get_health_score(self) -> Tuple[int, List[str]]:
        """
        Calculate overall system health score (0-100) and warnings.

        Returns:
            Tuple of (health_score, list_of_warnings)
        """
        score = 100
        warnings = []

        cache_stats = self.get_cache_stats()
        api_stats = self.get_api_stats()
        rating_stats = self.get_rating_stats()

        # Check cache hit rate (weight: 30 points)
        cache_hit_rate = cache_stats['last_hour']['hit_rate']
        if cache_hit_rate < 50:
            score -= 15
            warnings.append(f"Low cache hit rate: {cache_hit_rate:.1f}%")
        elif cache_hit_rate < 70:
            score -= 5
            warnings.append(f"Cache hit rate could be better: {cache_hit_rate:.1f}%")

        # Check API success rate (weight: 30 points)
        api_success_rate = api_stats['success_rate']
        if api_success_rate < 80:
            score -= 20
            warnings.append(f"Low API success rate: {api_success_rate:.1f}%")
        elif api_success_rate < 95:
            score -= 10
            warnings.append(f"API success rate below optimal: {api_success_rate:.1f}%")

        # Check quota trips (weight: 20 points)
        quota_trips = api_stats['quota']['trips']
        if quota_trips > 10:
            score -= 20
            warnings.append(f"High number of quota trips: {quota_trips}")
        elif quota_trips > 5:
            score -= 10
            warnings.append(f"Multiple quota trips detected: {quota_trips}")

        # Check rating queue (weight: 20 points)
        queued_ratings = rating_stats['queued']['total']
        if queued_ratings > 50:
            score -= 15
            warnings.append(f"Large rating queue backlog: {queued_ratings}")
        elif queued_ratings > 20:
            score -= 5
            warnings.append(f"Moderate rating queue: {queued_ratings}")

        return max(0, score), warnings


# Global metrics tracker instance
metrics = MetricsTracker()