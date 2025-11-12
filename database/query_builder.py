"""
Query builder module for YouTube Thumbs addon.
Provides fluent interface for building SQL queries with parameterized values.
"""
from typing import Any, List, Dict, Optional, Tuple


class VideoQueryBuilder:
    """
    Fluent query builder for video_ratings table queries.

    Provides a chainable interface for building SELECT queries with:
    - WHERE conditions (parameterized)
    - ORDER BY clauses (whitelist validated)
    - LIMIT and OFFSET
    - Pagination support

    Example usage:
        builder = VideoQueryBuilder(conn)
        results = builder
            .where("rating = ?", "like")
            .where("play_count > ?", 5)
            .order_by("date_last_played", "DESC")
            .limit(50)
            .execute()
    """

    # Whitelist of allowed sort columns to prevent SQL injection
    ALLOWED_SORT_COLUMNS = [
        'date_added', 'date_last_played', 'play_count', 'rating',
        'ha_title', 'ha_artist', 'yt_title', 'yt_channel', 'yt_duration',
        'rating_score'
    ]

    def __init__(self, connection):
        """
        Initialize query builder with database connection.

        Args:
            connection: Database connection object (sqlite3.Connection)
        """
        self._conn = connection
        self._where_clauses: List[str] = []
        self._params: List[Any] = []
        self._order_by_clause: Optional[str] = None
        self._limit_value: Optional[int] = None
        self._offset_value: Optional[int] = None
        self._select_columns: str = "*"

    def select(self, columns: str) -> 'VideoQueryBuilder':
        """
        Specify columns to select (default: *).

        Args:
            columns: Comma-separated column names or * for all columns

        Returns:
            Self for method chaining
        """
        self._select_columns = columns
        return self

    def where(self, condition: str, *params: Any) -> 'VideoQueryBuilder':
        """
        Add WHERE condition with parameterized values.

        Args:
            condition: SQL condition with ? placeholders (e.g., "rating = ?")
            *params: Values for the placeholders

        Returns:
            Self for method chaining

        Example:
            .where("rating = ?", "like")
            .where("play_count > ?", 5)
            .where("date_last_played >= ?", "2024-01-01")
        """
        self._where_clauses.append(condition)
        self._params.extend(params)
        return self

    def where_rating(self, rating: str) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE rating = ? condition.

        Args:
            rating: Rating value ('like', 'dislike', or 'none')

        Returns:
            Self for method chaining
        """
        return self.where("rating = ?", rating)

    def where_not_rating(self, rating: str) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE rating != ? condition.

        Args:
            rating: Rating value to exclude

        Returns:
            Self for method chaining
        """
        return self.where("rating != ?", rating)

    def where_play_count_min(self, min_count: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE play_count >= ? condition.

        Args:
            min_count: Minimum play count

        Returns:
            Self for method chaining
        """
        return self.where("play_count >= ?", min_count)

    def where_play_count_max(self, max_count: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE play_count <= ? condition.

        Args:
            max_count: Maximum play count

        Returns:
            Self for method chaining
        """
        return self.where("play_count <= ?", max_count)

    def where_play_count_equals(self, count: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE play_count = ? condition.

        Args:
            count: Exact play count

        Returns:
            Self for method chaining
        """
        return self.where("play_count = ?", count)

    def where_date_last_played_not_null(self) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE date_last_played IS NOT NULL condition.

        Returns:
            Self for method chaining
        """
        self._where_clauses.append("date_last_played IS NOT NULL")
        return self

    def where_date_from(self, date_from: str, column: str = "date_last_played") -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE date >= ? condition.

        Args:
            date_from: Start date (ISO format)
            column: Date column to filter (default: date_last_played)

        Returns:
            Self for method chaining
        """
        return self.where(f"{column} >= ?", date_from)

    def where_date_to(self, date_to: str, column: str = "date_last_played") -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE date <= ? condition.

        Args:
            date_to: End date (ISO format)
            column: Date column to filter (default: date_last_played)

        Returns:
            Self for method chaining
        """
        return self.where(f"{column} <= ?", date_to)

    def where_channel(self, channel_id: str) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE yt_channel_id = ? condition.

        Args:
            channel_id: YouTube channel ID

        Returns:
            Self for method chaining
        """
        return self.where("yt_channel_id = ?", channel_id)

    def where_category(self, category_id: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE yt_category_id = ? condition.

        Args:
            category_id: YouTube category ID

        Returns:
            Self for method chaining
        """
        return self.where("yt_category_id = ?", category_id)

    def where_source(self, source: str) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE source = ? condition.

        Args:
            source: Source value (e.g., 'ha_live', 'import_watch_history')

        Returns:
            Self for method chaining
        """
        return self.where("source = ?", source)

    def where_duration_min(self, min_duration: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE yt_duration >= ? condition.

        Args:
            min_duration: Minimum duration in seconds

        Returns:
            Self for method chaining
        """
        return self.where("yt_duration >= ?", min_duration)

    def where_duration_max(self, max_duration: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Add WHERE yt_duration <= ? condition.

        Args:
            max_duration: Maximum duration in seconds

        Returns:
            Self for method chaining
        """
        return self.where("yt_duration <= ?", max_duration)

    def where_search(self, query: str, columns: Optional[List[str]] = None) -> 'VideoQueryBuilder':
        """
        Convenience method: Add search condition across multiple columns.

        Args:
            query: Search query string
            columns: List of columns to search (default: ha_title, ha_artist, yt_channel)

        Returns:
            Self for method chaining
        """
        if columns is None:
            columns = ['ha_title', 'ha_artist', 'yt_channel']

        search_pattern = f"%{query}%"
        search_conditions = " OR ".join([f"{col} LIKE ?" for col in columns])
        self._where_clauses.append(f"({search_conditions})")
        self._params.extend([search_pattern] * len(columns))
        return self

    def order_by(self, column: str, direction: str = "DESC") -> 'VideoQueryBuilder':
        """
        Add ORDER BY clause with whitelist validation.

        Args:
            column: Column name to sort by (must be in ALLOWED_SORT_COLUMNS)
            direction: Sort direction ("ASC" or "DESC")

        Returns:
            Self for method chaining

        Raises:
            ValueError: If column is not in whitelist or direction is invalid
        """
        column = column.strip()
        direction = direction.strip().upper()

        if column not in self.ALLOWED_SORT_COLUMNS:
            from logging_helper import LoggingHelper, LogType
            logger = LoggingHelper.get_logger(LogType.MAIN)
            logger.warning(
                "Invalid sort column detected: '%s' (possible attack attempt)",
                column
            )
            raise ValueError(f"Invalid sort column: {column}")

        if direction not in ['ASC', 'DESC']:
            from logging_helper import LoggingHelper, LogType
            logger = LoggingHelper.get_logger(LogType.MAIN)
            logger.warning(
                "Invalid sort direction detected: '%s' (possible attack attempt)",
                direction
            )
            raise ValueError(f"Invalid sort direction: {direction}")

        self._order_by_clause = f"{column} {direction}"
        return self

    def order_by_multiple(self, orders: List[Tuple[str, str]]) -> 'VideoQueryBuilder':
        """
        Add multiple ORDER BY clauses.

        Args:
            orders: List of (column, direction) tuples

        Returns:
            Self for method chaining

        Example:
            .order_by_multiple([
                ("date_last_played", "DESC"),
                ("play_count", "DESC")
            ])
        """
        validated_orders = []
        for column, direction in orders:
            column = column.strip()
            direction = direction.strip().upper()

            if column not in self.ALLOWED_SORT_COLUMNS:
                raise ValueError(f"Invalid sort column: {column}")
            if direction not in ['ASC', 'DESC']:
                raise ValueError(f"Invalid sort direction: {direction}")

            validated_orders.append(f"{column} {direction}")

        self._order_by_clause = ", ".join(validated_orders)
        return self

    def limit(self, limit: int) -> 'VideoQueryBuilder':
        """
        Add LIMIT clause.

        Args:
            limit: Maximum number of rows to return

        Returns:
            Self for method chaining
        """
        self._limit_value = int(limit)
        return self

    def offset(self, offset: int) -> 'VideoQueryBuilder':
        """
        Add OFFSET clause.

        Args:
            offset: Number of rows to skip

        Returns:
            Self for method chaining
        """
        self._offset_value = int(offset)
        return self

    def paginate(self, page: int, per_page: int) -> 'VideoQueryBuilder':
        """
        Convenience method: Set LIMIT and OFFSET based on page number.

        Args:
            page: Page number (1-indexed)
            per_page: Number of items per page

        Returns:
            Self for method chaining
        """
        offset = (page - 1) * per_page
        return self.limit(per_page).offset(offset)

    def build_query(self) -> Tuple[str, List[Any]]:
        """
        Build the SQL query and return it with parameters.

        Returns:
            Tuple of (query_string, parameters)
        """
        query_parts = [f"SELECT {self._select_columns} FROM video_ratings"]

        # Add WHERE clause
        if self._where_clauses:
            where_sql = " AND ".join(self._where_clauses)
            query_parts.append(f"WHERE {where_sql}")

        # Add ORDER BY clause
        if self._order_by_clause:
            query_parts.append(f"ORDER BY {self._order_by_clause}")

        # Add LIMIT clause
        if self._limit_value is not None:
            query_parts.append("LIMIT ?")
            self._params.append(self._limit_value)

        # Add OFFSET clause
        if self._offset_value is not None:
            query_parts.append("OFFSET ?")
            self._params.append(self._offset_value)

        query = " ".join(query_parts)
        return query, self._params

    def execute(self) -> List[Dict[str, Any]]:
        """
        Execute the query and return results as list of dictionaries.

        Returns:
            List of row dictionaries
        """
        query, params = self.build_query()
        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def execute_one(self) -> Optional[Dict[str, Any]]:
        """
        Execute the query and return first result as dictionary.

        Returns:
            Single row dictionary or None if no results
        """
        query, params = self.build_query()
        cursor = self._conn.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        """
        Execute a COUNT query and return the count.

        Returns:
            Total number of matching rows
        """
        # Build count query (ignore ORDER BY, LIMIT, OFFSET for count)
        query_parts = ["SELECT COUNT(*) as count FROM video_ratings"]

        if self._where_clauses:
            where_sql = " AND ".join(self._where_clauses)
            query_parts.append(f"WHERE {where_sql}")

        query = " ".join(query_parts)
        cursor = self._conn.execute(query, self._params)
        result = cursor.fetchone()
        return result['count'] if result else 0
