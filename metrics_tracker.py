"""
Metrics tracking for YouTube Thumbs addon.
Tracks API usage, cache performance, and system health metrics.
"""
import time
import threading
from datetime import datetime, timedelta
from collections import deque, defaultdict, Counter
from typing import Dict, Any, Optional, List, Tuple
from logger import logger


class MetricsTracker:
    """Tracks and reports application metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()

        # API call tracking
        self._api_calls = deque(maxlen=10000)  # Store last 10k API calls
        # Use lambda to create bounded deques for each API type
        self._api_calls_by_type = defaultdict(lambda: deque(maxlen=1000))

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
        """Get search operation statistics using Python's Counter for efficiency."""
        with self._lock:
            # Use Counter for automatic counting
            reasons = Counter(s.get('reason', 'unknown') for s in self._failed_searches)
            titles = Counter(s.get('title', '') for s in self._failed_searches if s.get('title'))

            # Calculate batch operation averages using generator expressions
            batch_count = len(self._batch_operations)
            avg_batch_size = (
                sum(op['batch_size'] for op in self._batch_operations) / batch_count
                if batch_count > 0 else 0
            )
            avg_success_rate = (
                sum(op['success_rate'] for op in self._batch_operations) / batch_count
                if batch_count > 0 else 0
            )

            return {
                'total_searches': len(self._search_queries),
                'failed_searches': {
                    'total': len(self._failed_searches),
                    'last_hour': self._count_recent(self._failed_searches, 3600),
                    'by_reason': dict(reasons),
                    'top_failed_titles': [
                        {'title': title, 'count': count}
                        for title, count in titles.most_common(10)
                    ]
                },
                'results_distribution': dict(self._search_results_count),
                'batch_operations': {
                    'total': batch_count,
                    'average_batch_size': avg_batch_size,
                    'average_success_rate': avg_success_rate
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
        """Get all metrics in a single call with error resilience."""
        result = {'timestamp': datetime.now().isoformat()}

        # Safely gather each metric category
        metric_methods = [
            ('cache', self.get_cache_stats),
            ('api', self.get_api_stats),
            ('ratings', self.get_rating_stats),
            ('search', self.get_search_stats),
            ('system', self.get_system_stats)
        ]

        for key, method in metric_methods:
            try:
                result[key] = method()
            except Exception as e:
                logger.error("Failed to get %s metrics: %s", key, e)
                result[key] = {'error': str(e), 'status': 'failed'}

        return result

    def get_health_score(self) -> Tuple[int, List[str]]:
        """
        Calculate overall system health score (0-100) and warnings.
        Uses data-driven scoring rules for better maintainability.

        Returns:
            Tuple of (health_score, list_of_warnings)
        """
        cache_stats = self.get_cache_stats()
        api_stats = self.get_api_stats()
        rating_stats = self.get_rating_stats()

        # Data-driven scoring rules: (value_getter, thresholds, penalties, messages)
        scoring_rules = [
            # Cache hit rate (weight: 20 points total)
            (
                lambda: cache_stats['last_hour']['hit_rate'],
                [(50, 15, "Low cache hit rate: {value:.1f}%"),
                 (70, 5, "Cache hit rate could be better: {value:.1f}%")]
            ),
            # API success rate (weight: 30 points total)
            (
                lambda: api_stats['success_rate'],
                [(80, 20, "Low API success rate: {value:.1f}%"),
                 (95, 10, "API success rate below optimal: {value:.1f}%")]
            ),
            # Quota trips (weight: 20 points total) - reversed comparison
            (
                lambda: api_stats['quota']['trips'],
                [(10, 20, "High number of quota trips: {value}", True),
                 (5, 10, "Multiple quota trips detected: {value}", True)]
            ),
            # Rating queue (weight: 20 points total) - reversed comparison
            (
                lambda: rating_stats['queued']['total'],
                [(50, 15, "Large rating queue backlog: {value}", True),
                 (20, 5, "Moderate rating queue: {value}", True)]
            )
        ]

        score = 100
        warnings = []

        for value_getter, thresholds in scoring_rules:
            try:
                value = value_getter()
                for threshold_info in thresholds:
                    if len(threshold_info) == 4:
                        threshold, penalty, message, reverse = threshold_info
                        # For reverse comparisons (higher is worse)
                        if reverse and value > threshold:
                            score -= penalty
                            warnings.append(message.format(value=value))
                            break  # Apply only the first matching threshold
                    else:
                        threshold, penalty, message = threshold_info
                        # For normal comparisons (lower is worse)
                        if value < threshold:
                            score -= penalty
                            warnings.append(message.format(value=value))
                            break  # Apply only the first matching threshold
            except Exception as e:
                logger.error(f"Error calculating health metric: {e}")
                # Continue with other metrics if one fails

        return max(0, score), warnings


# Global metrics tracker instance
metrics = MetricsTracker()