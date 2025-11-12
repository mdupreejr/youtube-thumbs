"""
Stats operations module for YouTube Thumbs addon.
Provides statistical query methods for analytics and reporting.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from database.query_builder import VideoQueryBuilder


class StatsOperations:
    """Helper class for stats and analytics queries."""

    def __init__(self, connection):
        """
        Initialize stats operations with database connection.

        Args:
            connection: DatabaseConnection instance
        """
        self._connection = connection
        self._conn = connection.connection
        self._lock = connection.lock

    def get_total_videos(self) -> int:
        """
        Get total count of matched videos.

        Returns:
            Total number of videos (all videos in video_ratings are matched)
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(DISTINCT yt_video_id) as count FROM video_ratings "
            )
            result = cursor.fetchone()
            return result['count'] if result else 0

    def get_total_plays(self) -> int:
        """
        Get total play count across all videos.

        Returns:
            Sum of all play counts
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT SUM(play_count) as total FROM video_ratings "
            )
            result = cursor.fetchone()
            return result['total'] if result and result['total'] is not None else 0

    def get_ratings_breakdown(self) -> Dict[str, int]:
        """
        Get breakdown of ratings by type.

        Returns:
            Dictionary with rating types as keys and counts as values
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT rating, COUNT(*) as count
                FROM video_ratings
                               GROUP BY rating
                """
            )
            rows = cursor.fetchall()
            return {row['rating']: row['count'] for row in rows}

    def get_most_played(self, limit: int = 10) -> List[Dict]:
        """
        Get most played videos.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of video dictionaries sorted by play count
        """
        with self._lock:
            builder = VideoQueryBuilder(self._conn)
            return builder.order_by("play_count", "DESC").limit(limit).execute()

    def get_top_rated(self, limit: int = 10) -> List[Dict]:
        """
        Get top rated videos by rating score.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of video dictionaries sorted by rating score
        """
        with self._lock:
            builder = VideoQueryBuilder(self._conn)
            return builder.where_not_rating("none").order_by("rating_score", "DESC").limit(limit).execute()

    def get_recent_activity(self, limit: int = 20) -> List[Dict]:
        """
        Get recently played videos.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of video dictionaries sorted by last played date
        """
        with self._lock:
            builder = VideoQueryBuilder(self._conn)
            return builder.where_date_last_played_not_null().order_by("date_last_played", "DESC").limit(limit).execute()

    def get_rated_videos(self, rating: str, page: int = 1, per_page: int = 50) -> Dict:
        """
        Get videos with specific rating (like/dislike) with pagination.

        Args:
            rating: Rating to filter by ('like' or 'dislike')
            page: Page number (1-indexed)
            per_page: Number of results per page

        Returns:
            Dictionary with videos list, total count, and page info
        """
        with self._lock:
            # Get total count using query builder
            builder = VideoQueryBuilder(self._conn)
            total_count = builder.where_rating(rating).count()
            total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 0

            # Get paginated results using query builder
            builder = VideoQueryBuilder(self._conn)
            videos = builder.where_rating(rating).order_by_multiple([
                ("date_last_played", "DESC"),
                ("play_count", "DESC")
            ]).paginate(page, per_page).execute()

            return {
                'videos': videos,
                'total_count': total_count,
                'total_pages': total_pages,
                'current_page': page,
                'per_page': per_page
            }

    def get_top_channels(self, limit: int = 10) -> List[Dict]:
        """
        Get channels with most videos and plays.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of channel statistics
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT yt_channel, yt_channel_id,
                       COUNT(*) as video_count,
                       SUM(play_count) as total_plays,
                       AVG(rating_score) as avg_rating
                FROM video_ratings
                WHERE yt_channel IS NOT NULL
                GROUP BY yt_channel_id
                ORDER BY video_count DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_category_breakdown(self) -> List[Dict]:
        """
        Get video count by YouTube category.

        Returns:
            List of category statistics
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT yt_category_id, COUNT(*) as count
                FROM video_ratings
                WHERE yt_category_id IS NOT NULL
                GROUP BY yt_category_id
                ORDER BY count DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_plays_by_period(self, days: int = 7) -> List[Dict]:
        """
        Get play count grouped by date for last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of date/count pairs
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT DATE(date_last_played) as date, COUNT(*) as play_count
                FROM video_ratings
                                 AND date_last_played >= datetime('now', '-' || ? || ' days')
                GROUP BY DATE(date_last_played)
                ORDER BY date
                """,
                (days,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_additions(self, days: int = 7) -> List[Dict]:
        """
        Get videos added in last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of recently added videos
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM video_ratings
                                 AND date_added >= datetime('now', '-' || ? || ' days')
                ORDER BY date_added DESC
                """,
                (days,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive summary statistics.

        Returns:
            Dictionary with all summary metrics

        Note: v4.0.0+ All videos in video_ratings are matched (yt_video_id NOT NULL).
              Rating counts accurately reflect user's rating history.
        """
        with self._lock:
            # Get matched video statistics
            cursor = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total_videos,
                    COALESCE(SUM(play_count), 0) as total_plays,
                    COUNT(DISTINCT yt_channel_id) as unique_channels,
                    AVG(rating_score) as avg_rating_score
                FROM video_ratings
                               """
            )
            matched_stats = cursor.fetchone()

            # Get ALL rating counts (including pending videos)
            # This ensures users see accurate counts of their rated videos
            cursor = self._conn.execute(
                """
                SELECT
                    SUM(CASE WHEN rating = 'like' THEN 1 ELSE 0 END) as liked,
                    SUM(CASE WHEN rating = 'dislike' THEN 1 ELSE 0 END) as disliked,
                    SUM(CASE WHEN rating = 'none' THEN 1 ELSE 0 END) as unrated
                FROM video_ratings
                """
            )
            rating_stats = cursor.fetchone()

            if not matched_stats or not rating_stats:
                return {
                    'total_videos': 0,
                    'total_plays': 0,
                    'liked': 0,
                    'disliked': 0,
                    'unrated': 0,
                    'unique_channels': 0,
                    'avg_rating_score': 0
                }

            return {
                'total_videos': matched_stats['total_videos'],
                'total_plays': matched_stats['total_plays'],
                'liked': rating_stats['liked'] or 0,
                'disliked': rating_stats['disliked'] or 0,
                'unrated': rating_stats['unrated'] or 0,
                'unique_channels': matched_stats['unique_channels'] or 0,
                'avg_rating_score': round(matched_stats['avg_rating_score'], 2) if matched_stats['avg_rating_score'] is not None else 0
            }

    def get_play_history(self, limit: int = 100, offset: int = 0,
                         date_from: Optional[str] = None,
                         date_to: Optional[str] = None) -> List[Dict]:
        """
        Get paginated play history with optional date filtering.

        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip
            date_from: Optional start date filter (ISO format)
            date_to: Optional end date filter (ISO format)

        Returns:
            List of video dictionaries sorted by last played date
        """
        with self._lock:
            builder = VideoQueryBuilder(self._conn)
            builder.where_date_last_played_not_null()

            if date_from:
                builder.where_date_from(date_from)
            if date_to:
                builder.where_date_to(date_to)

            return builder.order_by("date_last_played", "DESC").limit(limit).offset(offset).execute()

    def get_rating_history(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Get paginated rating history.

        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns:
            List of video dictionaries sorted by last played date
        """
        with self._lock:
            builder = VideoQueryBuilder(self._conn)
            return builder.where_not_rating("none").order_by("date_last_played", "DESC").limit(limit).offset(offset).execute()

    def search_history(self, query: str, limit: int = 50) -> List[Dict]:
        """
        Search history by title, artist, or channel.

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            List of matching video dictionaries
        """
        with self._lock:
            builder = VideoQueryBuilder(self._conn)
            return builder.where_search(query).order_by("date_last_played", "DESC").limit(limit).execute()

    def get_listening_patterns(self) -> Dict:
        """
        Analyze listening patterns by day of week and hour.

        Returns:
            Dictionary with 'by_day' and 'by_hour' keys containing pattern data
        """
        with self._lock:
            # Day of week analysis
            cursor_day = self._conn.execute(
                """
                SELECT
                    CAST(strftime('%w', date_last_played) AS INTEGER) as day_of_week,
                    COUNT(*) as play_count
                FROM video_ratings
                WHERE date_last_played IS NOT NULL
                GROUP BY day_of_week
                ORDER BY day_of_week
                """
            )
            by_day = [dict(row) for row in cursor_day.fetchall()]

            # Hour of day analysis
            cursor_hour = self._conn.execute(
                """
                SELECT
                    CAST(strftime('%H', date_last_played) AS INTEGER) as hour,
                    COUNT(*) as play_count
                FROM video_ratings
                WHERE date_last_played IS NOT NULL
                GROUP BY hour
                ORDER BY hour
                """
            )
            by_hour = [dict(row) for row in cursor_hour.fetchall()]

            return {
                'by_day': by_day,
                'by_hour': by_hour
            }

    def get_discovery_stats(self) -> List[Dict]:
        """
        Get new video discovery rate over time.

        Returns:
            List of weekly discovery statistics for last 12 weeks
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    strftime('%Y-%W', date_added) as week,
                    COUNT(*) as new_videos
                FROM video_ratings
                               GROUP BY week
                ORDER BY week DESC
                LIMIT 12
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_play_distribution(self) -> List[Dict]:
        """
        Get distribution of videos by play count ranges.

        Returns:
            List of play count distribution statistics
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    CASE
                        WHEN play_count = 1 THEN '1 play'
                        WHEN play_count BETWEEN 2 AND 5 THEN '2-5 plays'
                        WHEN play_count BETWEEN 6 AND 10 THEN '6-10 plays'
                        WHEN play_count BETWEEN 11 AND 20 THEN '11-20 plays'
                        ELSE '20+ plays'
                    END as play_range,
                    COUNT(*) as video_count
                FROM video_ratings
                               GROUP BY play_range
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_correlation_stats(self) -> Dict:
        """
        Analyze correlations between play count and rating.

        Returns:
            Dictionary with rating types as keys and statistics as values
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    rating,
                    AVG(play_count) as avg_play_count,
                    COUNT(*) as video_count
                FROM video_ratings
                               GROUP BY rating
                """
            )
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                result[row['rating']] = {
                    'avg_play_count': row['avg_play_count'],
                    'video_count': row['video_count']
                }
            return result

    def get_retention_analysis(self) -> List[Dict]:
        """
        Analyze video retention (percentage of videos played more than once).

        Returns:
            List of retention statistics with type, count, and percentage
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    CASE
                        WHEN play_count = 1 THEN 'One-time play'
                        ELSE 'Repeat play'
                    END as retention_type,
                    COUNT(*) as count,
                    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM video_ratings ), 2) as percentage
                FROM video_ratings
                               GROUP BY retention_type
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_source_breakdown(self) -> List[Dict]:
        """
        Get breakdown by source (ha_live, import_watch_history, etc).

        Returns:
            List of source statistics
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT source, COUNT(*) as count
                FROM video_ratings
                               GROUP BY source
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_duration_analysis(self) -> List[Dict]:
        """
        Analyze video duration preferences.

        Returns:
            List of duration bucket statistics
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    CASE
                        WHEN yt_duration < 180 THEN 'Under 3 min'
                        WHEN yt_duration < 300 THEN '3-5 min'
                        WHEN yt_duration < 600 THEN '5-10 min'
                        ELSE 'Over 10 min'
                    END as duration_bucket,
                    COUNT(*) as count,
                    AVG(play_count) as avg_plays,
                    SUM(CASE WHEN rating = 'like' THEN 1 ELSE 0 END) as likes
                FROM video_ratings
                WHERE yt_duration IS NOT NULL
                GROUP BY duration_bucket
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def filter_videos(self, filters: Dict) -> Dict:
        """
        Advanced filtering with multiple criteria.

        Args:
            filters: Dictionary with filter parameters

        Returns:
            Dictionary with 'videos' list and 'total' count
        """
        with self._lock:
            # Build query using query builder
            builder = VideoQueryBuilder(self._conn)

            # Apply WHERE filters
            if filters.get('rating'):
                builder.where_rating(filters['rating'])

            if filters.get('channel_id'):
                builder.where_channel(filters['channel_id'])

            if filters.get('category'):
                builder.where_category(int(filters['category']))

            if filters.get('play_count_min'):
                builder.where_play_count_min(int(filters['play_count_min']))

            if filters.get('play_count_max'):
                builder.where_play_count_max(int(filters['play_count_max']))

            if filters.get('date_from'):
                builder.where_date_from(filters['date_from'], column='date_added')

            if filters.get('date_to'):
                builder.where_date_to(filters['date_to'], column='date_added')

            if filters.get('duration_min'):
                builder.where_duration_min(int(filters['duration_min']))

            if filters.get('duration_max'):
                builder.where_duration_max(int(filters['duration_max']))

            if filters.get('source'):
                builder.where_source(filters['source'])

            # Get total count
            total = builder.count()

            # Apply sorting and pagination
            sort_by = filters.get('sort_by', 'date_added')
            sort_order = filters.get('sort_order', 'desc').upper()

            try:
                builder.order_by(sort_by, sort_order)
            except ValueError:
                # Invalid sort column or order, use defaults
                builder.order_by('date_added', 'DESC')

            limit = int(filters.get('limit', 50))
            offset = int(filters.get('offset', 0))
            builder.limit(limit).offset(offset)

            # Execute query
            videos = builder.execute()

            return {
                'videos': videos,
                'total': total
            }

    def get_all_channels(self) -> List[Dict]:
        """
        Get list of all unique channels.

        Returns:
            List of channel dictionaries with yt_channel and yt_channel_id
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT DISTINCT yt_channel, yt_channel_id
                FROM video_ratings
                WHERE yt_channel IS NOT NULL
                ORDER BY yt_channel
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all_categories(self) -> List[int]:
        """
        Get list of all categories present in database.

        Returns:
            List of category IDs
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT DISTINCT yt_category_id
                FROM video_ratings
                WHERE yt_category_id IS NOT NULL
                ORDER BY yt_category_id
                """
            )
            return [row['yt_category_id'] for row in cursor.fetchall()]

    def get_recommendations(self, based_on: str = 'likes', limit: int = 10) -> List[Dict]:
        """
        Recommend videos based on user preferences.

        Args:
            based_on: Strategy for recommendations ('likes', 'played', or 'discover')
            limit: Maximum number of recommendations to return

        Returns:
            List of recommended video dictionaries
        """
        with self._lock:
            if based_on == 'likes':
                # Similar to liked videos (same channel/category, low play count, unrated)
                # Note: Subquery pattern - keeping original for complex subquery logic
                cursor = self._conn.execute(
                    """
                    SELECT * FROM video_ratings
                    WHERE yt_channel_id IN (
                        SELECT DISTINCT yt_channel_id
                        FROM video_ratings
                        WHERE rating = 'like'                    )
                    AND play_count < 3
                    AND rating = 'none'
                                       ORDER BY RANDOM()
                    LIMIT ?
                    """,
                    (limit,)
                )
            elif based_on == 'played':
                # Similar to most played videos (same category, low play count)
                # Note: Subquery pattern - keeping original for complex subquery logic
                cursor = self._conn.execute(
                    """
                    SELECT * FROM video_ratings
                    WHERE yt_category_id IN (
                        SELECT DISTINCT yt_category_id
                        FROM video_ratings
                                               ORDER BY play_count DESC
                        LIMIT 5
                    )
                    AND play_count < 2
                                       ORDER BY date_added DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
            elif based_on == 'discover':
                # Never played videos in liked channels
                # Note: Subquery pattern - keeping original for complex subquery logic
                cursor = self._conn.execute(
                    """
                    SELECT * FROM video_ratings
                    WHERE yt_channel_id IN (
                        SELECT DISTINCT yt_channel_id
                        FROM video_ratings
                        WHERE rating = 'like'                    )
                    AND play_count = 0
                                       ORDER BY date_added DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
            else:
                return []

            return [dict(row) for row in cursor.fetchall()]

    def get_unrated_videos(self, page: int = 1, limit: int = 50) -> Dict[str, Any]:
        """
        Get paginated list of unrated videos sorted by play count.

        Args:
            page: Page number (1-indexed)
            limit: Number of videos per page

        Returns:
            Dictionary with songs list, pagination info, and total count
        """
        with self._lock:
            # Get total count of unrated songs using query builder
            builder = VideoQueryBuilder(self._conn)
            total_count = builder.where_rating('none').count()

        # Handle empty results
        if total_count == 0:
            return {
                'songs': [],
                'page': 1,
                'total_pages': 0,
                'total_count': 0
            }

        # Calculate total pages and clamp page to valid range
        total_pages = (total_count + limit - 1) // limit
        page = max(1, min(page, total_pages))  # Clamp page to [1, total_pages]

        with self._lock:
            # Get unrated songs using query builder
            builder = VideoQueryBuilder(self._conn)
            builder.select("yt_video_id, ha_title, yt_title, ha_artist, yt_channel, play_count, yt_url, ha_duration, yt_duration")
            songs = builder.where_rating('none').order_by_multiple([
                ("play_count", "DESC"),
                ("date_last_played", "DESC")
            ]).paginate(page, limit).execute()

        # Note: page is now clamped to valid range above
        total_pages = (total_count + limit - 1) // limit

        return {
            'songs': songs,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count
        }

    