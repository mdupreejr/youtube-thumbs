"""
Data API routes blueprint for statistics, analytics, history, insights, and recommendations.
Extracted from app.py to improve code organization.
"""
from flask import Blueprint, request, jsonify, Response
from logger import logger

# Create blueprint
bp = Blueprint('data_api', __name__, url_prefix='/api')

# Database instance will be injected
db = None


def init_data_api_routes(database):
    """
    Initialize the data API routes with database instance.

    Args:
        database: Database instance to use for queries
    """
    global db
    db = database


@bp.route('/stats/most-played', methods=['GET'])
def get_most_played_stats() -> Response:
    """Get most played songs for statistics dashboard."""
    try:
        limit = int(request.args.get('limit', 10))
        limit = max(1, min(limit, 100))  # Enforce bounds: 1-100
        videos = db.get_most_played(limit)
        return jsonify({'success': True, 'data': videos})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400
    except Exception as e:
        logger.error(f"Error getting most played stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve most played statistics'}), 500


@bp.route('/stats/top-channels', methods=['GET'])
def get_top_channels_stats() -> Response:
    """Get top channels/artists for statistics dashboard."""
    try:
        limit = int(request.args.get('limit', 10))
        limit = max(1, min(limit, 100))  # Enforce bounds: 1-100
        channels = db.get_top_channels(limit)
        return jsonify({'success': True, 'data': channels})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400
    except Exception as e:
        logger.error(f"Error getting top channels stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve top channels statistics'}), 500


@bp.route('/stats/rating-distribution', methods=['GET'])
def get_rating_distribution() -> Response:
    """Get rating distribution for pie chart."""
    try:
        distribution = db.get_ratings_breakdown()
        return jsonify({'success': True, 'data': distribution})
    except Exception as e:
        logger.error(f"Error getting rating distribution: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve rating distribution'}), 500


@bp.route('/stats/summary', methods=['GET'])
def get_stats_summary() -> Response:
    """Get summary statistics for dashboard."""
    try:
        summary = db.get_stats_summary()
        return jsonify({
            'success': True,
            'data': summary
        })
    except Exception as e:
        logger.error(f"Error getting stats summary: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve summary statistics'}), 500


@bp.route('/stats/top-rated', methods=['GET'])
def get_top_rated_api() -> Response:
    """Get top rated videos."""
    try:
        try:
            limit = int(request.args.get('limit', 10))
            limit = max(1, min(limit, 100))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400

        videos = db.get_top_rated(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting top rated: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@bp.route('/stats/recent', methods=['GET'])
def get_recent_activity_api() -> Response:
    """Get recent activity."""
    try:
        try:
            limit = int(request.args.get('limit', 20))
            limit = max(1, min(limit, 100))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400

        videos = db.get_recent_activity(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@bp.route('/stats/categories', methods=['GET'])
def get_category_stats() -> Response:
    """Get category breakdown."""
    try:
        categories = db.get_category_breakdown()
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"Error getting category stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve category statistics'}), 500


@bp.route('/stats/timeline', methods=['GET'])
def get_timeline_stats() -> Response:
    """Get play timeline data."""
    try:
        period = request.args.get('period', 'daily')

        if period not in ['hourly', 'daily', 'weekly', 'monthly']:
            period = 'daily'

        timeline = db.get_plays_by_period(period)
        return jsonify({'success': True, 'data': timeline})
    except Exception as e:
        logger.error(f"Error getting timeline stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve timeline statistics'}), 500


@bp.route('/stats/api-usage', methods=['GET'])
def get_api_usage_stats() -> Response:
    """Get API usage statistics."""
    try:
        from datetime import datetime, timedelta

        # Default to last 7 days
        days = int(request.args.get('days', 7))
        days = max(1, min(days, 90))  # Enforce bounds: 1-90

        usage = db.get_api_usage_stats(days)
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting API usage stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve API usage statistics'}), 500


@bp.route('/stats/api-usage/daily', methods=['GET'])
def get_daily_api_usage() -> Response:
    """Get daily API usage breakdown."""
    try:
        days = int(request.args.get('days', 30))
        days = max(1, min(days, 90))

        usage = db.get_daily_api_usage(days)
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting daily API usage: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve daily API usage'}), 500


@bp.route('/stats/api-usage/hourly', methods=['GET'])
def get_hourly_api_usage() -> Response:
    """Get hourly API usage pattern."""
    try:
        usage = db.get_hourly_api_usage()
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting hourly API usage: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve hourly API usage'}), 500


@bp.route('/history/plays', methods=['GET'])
def get_play_history_api() -> Response:
    """Get play history."""
    try:
        limit = int(request.args.get('limit', 50))
        limit = max(1, min(limit, 500))

        offset = int(request.args.get('offset', 0))
        offset = max(0, offset)

        history = db.get_play_history(limit, offset)
        return jsonify({'success': True, 'data': history})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid limit or offset parameter'}), 400
    except Exception as e:
        logger.error(f"Error getting play history: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve play history'}), 500


@bp.route('/history/search', methods=['GET'])
def search_history_api() -> Response:
    """Search history."""
    try:
        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 50))
        limit = max(1, min(limit, 500))

        if not query:
            return jsonify({'success': False, 'error': 'Search query required'}), 400

        results = db.search_history(query, limit)
        return jsonify({'success': True, 'data': results})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400
    except Exception as e:
        logger.error(f"Error searching history: {e}")
        return jsonify({'success': False, 'error': 'Failed to search history'}), 500


@bp.route('/insights/patterns', methods=['GET'])
def get_listening_patterns() -> Response:
    """Get listening patterns."""
    try:
        patterns = db.get_listening_patterns()
        return jsonify({'success': True, 'data': patterns})
    except Exception as e:
        logger.error(f"Error getting listening patterns: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve listening patterns'}), 500


@bp.route('/insights/trends', methods=['GET'])
def get_discovery_insights() -> Response:
    """Get discovery insights and trends."""
    try:
        period_days = int(request.args.get('days', 30))
        period_days = max(1, min(period_days, 365))

        insights = db.get_discovery_stats(period_days)
        return jsonify({'success': True, 'data': insights})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid days parameter'}), 400
    except Exception as e:
        logger.error(f"Error getting discovery insights: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve discovery insights'}), 500


@bp.route('/analytics/correlation', methods=['GET'])
def get_correlation_analysis() -> Response:
    """Get correlation analysis between different metrics."""
    try:
        data = db.get_correlation_stats()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting correlation analysis: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve correlation analysis'}), 500


@bp.route('/analytics/retention', methods=['GET'])
def get_retention_analysis() -> Response:
    """Get retention analysis."""
    try:
        data = db.get_retention_analysis()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting retention analysis: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve retention analysis'}), 500


@bp.route('/analytics/duration', methods=['GET'])
def get_duration_analysis() -> Response:
    """Get duration analysis."""
    try:
        data = db.get_duration_analysis()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting duration analysis: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve duration analysis'}), 500


@bp.route('/analytics/source', methods=['GET'])
def get_source_breakdown() -> Response:
    """Get source breakdown analysis."""
    try:
        data = db.get_source_breakdown()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting source breakdown: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve source breakdown'}), 500


@bp.route('/explorer/filter', methods=['POST'])
def filter_videos_api() -> Response:
    """Filter videos based on criteria."""
    try:
        filters = request.get_json()

        if not filters:
            return jsonify({'success': False, 'error': 'Filter criteria required'}), 400

        videos = db.filter_videos(filters)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error filtering videos: {e}")
        return jsonify({'success': False, 'error': 'Failed to filter videos'}), 500


@bp.route('/explorer/channels', methods=['GET'])
def get_all_channels_api() -> Response:
    """Get all channels."""
    try:
        channels = db.get_all_channels()
        return jsonify({'success': True, 'data': channels})
    except Exception as e:
        logger.error(f"Error getting channels: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve channels'}), 500


@bp.route('/explorer/categories', methods=['GET'])
def get_all_categories_api() -> Response:
    """Get all categories."""
    try:
        categories = db.get_all_categories()
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve categories'}), 500


@bp.route('/recommendations', methods=['GET'])
def get_recommendations_api() -> Response:
    """Get video recommendations."""
    try:
        based_on = request.args.get('strategy', 'likes')
        limit = int(request.args.get('limit', 10))

        # Validate strategy
        if based_on not in ['likes', 'played', 'discover']:
            based_on = 'likes'

        # Limit range
        limit = max(1, min(limit, 50))

        recommendations = db.get_recommendations(based_on, limit)
        return jsonify({'success': True, 'data': recommendations})
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@bp.route('/pending/status', methods=['GET'])
def get_pending_status() -> Response:
    """Get pending video statistics and breakdown by reason."""
    try:
        # Get total counts
        cursor = db._conn.execute("""
            SELECT
                COUNT(*) as total_pending,
                SUM(CASE WHEN pending_reason = 'quota_exceeded' THEN 1 ELSE 0 END) as quota_exceeded,
                SUM(CASE WHEN pending_reason = 'not_found' THEN 1 ELSE 0 END) as not_found,
                SUM(CASE WHEN pending_reason = 'unknown' OR pending_reason IS NULL THEN 1 ELSE 0 END) as unknown,
                COUNT(DISTINCT ha_artist) as unique_artists
            FROM video_ratings
            WHERE yt_match_pending = 1
        """)
        stats = dict(cursor.fetchone())

        # Get recent pending videos
        cursor = db._conn.execute("""
            SELECT ha_title, ha_artist, pending_reason, yt_match_attempts, yt_match_last_attempt
            FROM video_ratings
            WHERE yt_match_pending = 1
            ORDER BY yt_match_last_attempt DESC
            LIMIT 10
        """)
        recent_pending = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            'success': True,
            'data': {
                'statistics': stats,
                'recent_pending': recent_pending
            }
        })
    except Exception as e:
        logger.error(f"Error getting pending status: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve pending video status'}), 500
