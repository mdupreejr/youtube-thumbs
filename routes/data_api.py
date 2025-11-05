"""
Data API routes blueprint for statistics, analytics, history, insights, and recommendations.
Extracted from app.py to improve code organization.
"""
from flask import Blueprint, request, jsonify, Response
from flask_wtf.csrf import csrf
from logger import logger
from helpers.validation_helpers import validate_limit_param
from helpers.response_helpers import error_response, success_response
from constants import MAX_BATCH_SIZE

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
        limit, error = validate_limit_param(request.args, default=10, max_value=100)
        if error:
            return error
        videos = db.get_most_played(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting most played stats: {e}")
        return error_response('Failed to retrieve most played statistics', 500)


@bp.route('/stats/top-channels', methods=['GET'])
def get_top_channels_stats() -> Response:
    """Get top channels/artists for statistics dashboard."""
    try:
        limit, error = validate_limit_param(request.args, default=10, max_value=100)
        if error:
            return error
        channels = db.get_top_channels(limit)
        return jsonify({'success': True, 'data': channels})
    except Exception as e:
        logger.error(f"Error getting top channels stats: {e}")
        return error_response('Failed to retrieve top channels statistics', 500)


@bp.route('/stats/rating-distribution', methods=['GET'])
def get_rating_distribution() -> Response:
    """Get rating distribution for pie chart."""
    try:
        distribution = db.get_ratings_breakdown()
        return jsonify({'success': True, 'data': distribution})
    except Exception as e:
        logger.error(f"Error getting rating distribution: {e}")
        return error_response('Failed to retrieve rating distribution', 500)


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
        return error_response( 'Failed to retrieve summary statistics', 500)


@bp.route('/stats/top-rated', methods=['GET'])
def get_top_rated_api() -> Response:
    """Get top rated videos."""
    try:
        limit, error = validate_limit_param(request.args, default=10, max_value=100)
        if error:
            return error

        videos = db.get_top_rated(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting top rated: {e}")
        return error_response( 'An error occurred processing your request', 500)


@bp.route('/stats/recent', methods=['GET'])
def get_recent_activity_api() -> Response:
    """Get recent activity."""
    try:
        limit, error = validate_limit_param(request.args, default=20, max_value=100)
        if error:
            return error

        videos = db.get_recent_activity(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return error_response( 'An error occurred processing your request', 500)


@bp.route('/stats/categories', methods=['GET'])
def get_category_stats() -> Response:
    """Get category breakdown."""
    try:
        categories = db.get_category_breakdown()
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"Error getting category stats: {e}")
        return error_response( 'Failed to retrieve category statistics', 500)


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
        return error_response( 'Failed to retrieve timeline statistics', 500)


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
        return error_response( 'Failed to retrieve API usage statistics', 500)


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
        return error_response( 'Failed to retrieve daily API usage', 500)


@bp.route('/stats/api-usage/hourly', methods=['GET'])
def get_hourly_api_usage() -> Response:
    """Get hourly API usage pattern."""
    try:
        usage = db.get_hourly_api_usage()
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting hourly API usage: {e}")
        return error_response( 'Failed to retrieve hourly API usage', 500)


@bp.route('/history/plays', methods=['GET'])
def get_play_history_api() -> Response:
    """Get play history."""
    try:
        limit, error = validate_limit_param(request.args, default=50, max_value=500)
        if error:
            return error

        offset = int(request.args.get('offset', 0))
        offset = max(0, offset)

        history = db.get_play_history(limit, offset)
        return jsonify({'success': True, 'data': history})
    except ValueError:
        return error_response( 'Invalid offset parameter', 400)
    except Exception as e:
        logger.error(f"Error getting play history: {e}")
        return error_response( 'Failed to retrieve play history', 500)


@bp.route('/history/search', methods=['GET'])
def search_history_api() -> Response:
    """Search history."""
    try:
        query = request.args.get('q', '').strip()
        limit, error = validate_limit_param(request.args, default=50, max_value=500)
        if error:
            return error

        if not query:
            return error_response( 'Search query required', 400)

        results = db.search_history(query, limit)
        return jsonify({'success': True, 'data': results})
    except ValueError:
        return error_response( 'Invalid limit parameter', 400)
    except Exception as e:
        logger.error(f"Error searching history: {e}")
        return error_response( 'Failed to search history', 500)


@bp.route('/insights/patterns', methods=['GET'])
def get_listening_patterns() -> Response:
    """Get listening patterns."""
    try:
        patterns = db.get_listening_patterns()
        return jsonify({'success': True, 'data': patterns})
    except Exception as e:
        logger.error(f"Error getting listening patterns: {e}")
        return error_response( 'Failed to retrieve listening patterns', 500)


@bp.route('/insights/trends', methods=['GET'])
def get_discovery_insights() -> Response:
    """Get discovery insights and trends."""
    try:
        period_days = int(request.args.get('days', 30))
        period_days = max(1, min(period_days, 365))

        insights = db.get_discovery_stats(period_days)
        return jsonify({'success': True, 'data': insights})
    except ValueError:
        return error_response( 'Invalid days parameter', 400)
    except Exception as e:
        logger.error(f"Error getting discovery insights: {e}")
        return error_response( 'Failed to retrieve discovery insights', 500)


@bp.route('/analytics/correlation', methods=['GET'])
def get_correlation_analysis() -> Response:
    """Get correlation analysis between different metrics."""
    try:
        data = db.get_correlation_stats()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting correlation analysis: {e}")
        return error_response( 'Failed to retrieve correlation analysis', 500)


@bp.route('/analytics/retention', methods=['GET'])
def get_retention_analysis() -> Response:
    """Get retention analysis."""
    try:
        data = db.get_retention_analysis()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting retention analysis: {e}")
        return error_response( 'Failed to retrieve retention analysis', 500)


@bp.route('/analytics/duration', methods=['GET'])
def get_duration_analysis() -> Response:
    """Get duration analysis."""
    try:
        data = db.get_duration_analysis()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting duration analysis: {e}")
        return error_response( 'Failed to retrieve duration analysis', 500)


@bp.route('/analytics/source', methods=['GET'])
def get_source_breakdown() -> Response:
    """Get source breakdown analysis."""
    try:
        data = db.get_source_breakdown()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"Error getting source breakdown: {e}")
        return error_response( 'Failed to retrieve source breakdown', 500)


@bp.route('/explorer/filter', methods=['POST'])
def filter_videos_api() -> Response:
    """Filter videos based on criteria."""
    try:
        filters = request.get_json()

        if not filters:
            return error_response( 'Filter criteria required', 400)

        videos = db.filter_videos(filters)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error filtering videos: {e}")
        return error_response( 'Failed to filter videos', 500)


@bp.route('/explorer/channels', methods=['GET'])
def get_all_channels_api() -> Response:
    """Get all channels."""
    try:
        channels = db.get_all_channels()
        return jsonify({'success': True, 'data': channels})
    except Exception as e:
        logger.error(f"Error getting channels: {e}")
        return error_response( 'Failed to retrieve channels', 500)


@bp.route('/explorer/categories', methods=['GET'])
def get_all_categories_api() -> Response:
    """Get all categories."""
    try:
        categories = db.get_all_categories()
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return error_response( 'Failed to retrieve categories', 500)


@bp.route('/recommendations', methods=['GET'])
def get_recommendations_api() -> Response:
    """Get video recommendations."""
    try:
        based_on = request.args.get('strategy', 'likes')
        limit, error = validate_limit_param(request.args, default=10, max_value=50)
        if error:
            return error

        # Validate strategy
        if based_on not in ['likes', 'played', 'discover']:
            based_on = 'likes'

        recommendations = db.get_recommendations(based_on, limit)
        return jsonify({'success': True, 'data': recommendations})
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        return error_response( 'An error occurred processing your request', 500)


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
        return error_response( 'Failed to retrieve pending video status', 500)


@bp.route('/pending/retry', methods=['POST'])
@csrf.exempt
def retry_pending_videos() -> Response:
    """
    Manually trigger retry of pending videos with quota_exceeded reason.
    Processes videos in batches to avoid overwhelming the YouTube API.
    API endpoint called from JavaScript - CSRF exempted.
    """
    import time
    from search_helpers import search_and_match_video
    from cache_helpers import find_cached_video
    from quota_guard import get_quota_guard

    try:
        # Get batch size from request (default: 5, max: 50)
        batch_size = int(request.args.get('batch_size', 5))
        batch_size = max(1, min(batch_size, MAX_BATCH_SIZE))

        # Rate limiting check - use simple time-based check
        # In production, consider using Redis or similar for distributed rate limiting
        import os
        import tempfile
        # SECURITY: Use tempfile.gettempdir() instead of hardcoded /tmp path
        last_retry_file = os.path.join(tempfile.gettempdir(), 'youtube_thumbs_last_retry.txt')
        if os.path.exists(last_retry_file):
            with open(last_retry_file, 'r') as f:
                last_retry = float(f.read().strip())
                if time.time() - last_retry < 30:  # 30 second cooldown
                    return jsonify({
                        'success': False,
                        'error': 'Please wait 30 seconds between retry attempts'
                    }), 429

        # Update last retry timestamp
        with open(last_retry_file, 'w') as f:
            f.write(str(time.time()))

        # Get pending videos with quota_exceeded reason
        pending_videos = db.get_pending_videos(limit=batch_size, reason_filter='quota_exceeded')

        if not pending_videos:
            return jsonify({
                'success': True,
                'processed': 0,
                'resolved': 0,
                'failed': 0,
                'not_found': 0,
                'message': 'No pending videos with quota_exceeded reason found'
            })

        # Check quota status
        quota_guard = get_quota_guard()
        quota_blocked = quota_guard.is_blocked() if quota_guard else False

        if quota_blocked:
            logger.warning("Manual retry attempted while quota is blocked")

        # Process each video
        resolved = 0
        failed = 0
        not_found = 0

        for video in pending_videos:
            try:
                ha_title = video.get('ha_title', 'Unknown')
                ha_artist = video.get('ha_artist', 'Unknown')
                ha_duration = video.get('ha_duration')
                ha_content_id = video.get('ha_content_id')

                logger.info(f"Manual retry: Processing '{ha_title}' by {ha_artist}")

                # Try cache first
                cached_video = find_cached_video(db, {'title': ha_title, 'artist': ha_artist, 'duration': ha_duration})
                if cached_video:
                    db.resolve_pending_video(ha_content_id, cached_video)
                    resolved += 1
                    logger.info(f"Resolved from cache: {ha_title}")
                    continue

                # Search YouTube
                ha_media = {'title': ha_title, 'artist': ha_artist, 'duration': ha_duration}
                from youtube_api import get_youtube_api
                yt_api = get_youtube_api()
                result = search_and_match_video(ha_media, yt_api, db)

                if result and result.get('video'):
                    # Found and matched
                    db.resolve_pending_video(ha_content_id, result['video'])
                    resolved += 1
                    logger.info(f"Resolved from YouTube: {ha_title}")
                elif result and result.get('reason') == 'not_found':
                    # Not found
                    db.mark_pending_not_found(ha_content_id)
                    not_found += 1
                    logger.info(f"Not found: {ha_title}")
                else:
                    # Search failed
                    failed += 1
                    logger.warning(f"Search failed: {ha_title}")

                # Delay between requests to avoid hammering API
                time.sleep(2)

            except Exception as e:
                logger.error(f"Error processing pending video: {e}")
                failed += 1

        processed = len(pending_videos)
        message = f"Processed {processed} pending videos: {resolved} resolved, {failed} failed, {not_found} not found"

        return jsonify({
            'success': True,
            'processed': processed,
            'resolved': resolved,
            'failed': failed,
            'not_found': not_found,
            'quota_blocked': quota_blocked,
            'message': message
        })

    except ValueError:
        return error_response( 'Invalid batch_size parameter', 400)
    except Exception as e:
        logger.error(f"Error in manual pending video retry: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return error_response( 'Failed to retry pending videos', 500)
