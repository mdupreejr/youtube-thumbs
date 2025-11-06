"""
Data API routes blueprint for statistics, analytics, history, insights, and recommendations.
Extracted from app.py to improve code organization.
"""
from flask import Blueprint, request, jsonify, Response
from logger import logger
from helpers.validation_helpers import validate_limit_param
from helpers.response_helpers import error_response, success_response
from helpers.api_helpers import stats_endpoint, simple_stats_endpoint, api_endpoint
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
@stats_endpoint('get_most_played', limit_default=10, limit_max=100,
                error_message='Failed to retrieve most played statistics')
def get_most_played_stats() -> Response:
    """Get most played songs for statistics dashboard."""
    pass  # Decorator handles everything


@bp.route('/stats/top-channels', methods=['GET'])
@stats_endpoint('get_top_channels', limit_default=10, limit_max=100,
                error_message='Failed to retrieve top channels statistics')
def get_top_channels_stats() -> Response:
    """Get top channels/artists for statistics dashboard."""
    pass  # Decorator handles everything


@bp.route('/stats/rating-distribution', methods=['GET'])
@simple_stats_endpoint('get_ratings_breakdown',
                       error_message='Failed to retrieve rating distribution')
def get_rating_distribution() -> Response:
    """Get rating distribution for pie chart."""
    pass  # Decorator handles everything


@bp.route('/stats/summary', methods=['GET'])
@simple_stats_endpoint('get_stats_summary',
                       error_message='Failed to retrieve summary statistics')
def get_stats_summary() -> Response:
    """Get summary statistics for dashboard."""
    pass  # Decorator handles everything


@bp.route('/stats/top-rated', methods=['GET'])
@stats_endpoint('get_top_rated', limit_default=10, limit_max=100,
                error_message='An error occurred processing your request')
def get_top_rated_api() -> Response:
    """Get top rated videos."""
    pass  # Decorator handles everything


@bp.route('/stats/recent', methods=['GET'])
@stats_endpoint('get_recent_activity', limit_default=20, limit_max=100,
                error_message='An error occurred processing your request')
def get_recent_activity_api() -> Response:
    """Get recent activity."""
    pass  # Decorator handles everything


@bp.route('/stats/categories', methods=['GET'])
@simple_stats_endpoint('get_category_breakdown',
                       error_message='Failed to retrieve category statistics')
def get_category_stats() -> Response:
    """Get category breakdown."""
    pass  # Decorator handles everything


@bp.route('/stats/timeline', methods=['GET'])
@api_endpoint('get_plays_by_period',
              custom_params_builder=lambda args: (args.get('period', 'daily') if args.get('period') in ['hourly', 'daily', 'weekly', 'monthly'] else 'daily',),
              error_message='Failed to retrieve timeline statistics')
def get_timeline_stats() -> Response:
    """Get play timeline data."""
    pass  # Decorator handles everything


@bp.route('/stats/api-usage', methods=['GET'])
@api_endpoint('get_api_usage_stats',
              custom_params_builder=lambda args: (max(1, min(int(args.get('days', 7)), 90)),),
              error_message='Failed to retrieve API usage statistics')
def get_api_usage_stats() -> Response:
    """Get API usage statistics."""
    pass  # Decorator handles everything


@bp.route('/stats/api-usage/daily', methods=['GET'])
@api_endpoint('get_daily_api_usage',
              custom_params_builder=lambda args: (max(1, min(int(args.get('days', 30)), 90)),),
              error_message='Failed to retrieve daily API usage')
def get_daily_api_usage() -> Response:
    """Get daily API usage breakdown."""
    pass  # Decorator handles everything


@bp.route('/stats/api-usage/hourly', methods=['GET'])
@simple_stats_endpoint('get_hourly_api_usage',
                       error_message='Failed to retrieve hourly API usage')
def get_hourly_api_usage() -> Response:
    """Get hourly API usage pattern."""
    pass  # Decorator handles everything


def _build_play_history_params(args):
    """Build parameters for play history endpoint."""
    limit, error = validate_limit_param(args, default=50, max_value=500)
    if error:
        limit = 50
    offset = max(0, int(args.get('offset', 0)))
    return (limit, offset)


@bp.route('/history/plays', methods=['GET'])
@api_endpoint('get_play_history',
              custom_params_builder=_build_play_history_params,
              error_message='Failed to retrieve play history')
def get_play_history_api() -> Response:
    """Get play history."""
    pass  # Decorator handles everything


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
@simple_stats_endpoint('get_listening_patterns',
                       error_message='Failed to retrieve listening patterns')
def get_listening_patterns() -> Response:
    """Get listening patterns."""
    pass  # Decorator handles everything


@bp.route('/insights/trends', methods=['GET'])
@api_endpoint('get_discovery_stats',
              custom_params_builder=lambda args: (max(1, min(int(args.get('days', 30)), 365)),),
              error_message='Failed to retrieve discovery insights')
def get_discovery_insights() -> Response:
    """Get discovery insights and trends."""
    pass  # Decorator handles everything


@bp.route('/analytics/correlation', methods=['GET'])
@simple_stats_endpoint('get_correlation_stats',
                       error_message='Failed to retrieve correlation analysis')
def get_correlation_analysis() -> Response:
    """Get correlation analysis between different metrics."""
    pass  # Decorator handles everything


@bp.route('/analytics/retention', methods=['GET'])
@simple_stats_endpoint('get_retention_analysis',
                       error_message='Failed to retrieve retention analysis')
def get_retention_analysis() -> Response:
    """Get retention analysis."""
    pass  # Decorator handles everything


@bp.route('/analytics/duration', methods=['GET'])
@simple_stats_endpoint('get_duration_analysis',
                       error_message='Failed to retrieve duration analysis')
def get_duration_analysis() -> Response:
    """Get duration analysis."""
    pass  # Decorator handles everything


@bp.route('/analytics/source', methods=['GET'])
@simple_stats_endpoint('get_source_breakdown',
                       error_message='Failed to retrieve source breakdown')
def get_source_breakdown() -> Response:
    """Get source breakdown analysis."""
    pass  # Decorator handles everything


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
@simple_stats_endpoint('get_all_channels',
                       error_message='Failed to retrieve channels')
def get_all_channels_api() -> Response:
    """Get all channels."""
    pass  # Decorator handles everything


@bp.route('/explorer/categories', methods=['GET'])
@simple_stats_endpoint('get_all_categories',
                       error_message='Failed to retrieve categories')
def get_all_categories_api() -> Response:
    """Get all categories."""
    pass  # Decorator handles everything


def _build_recommendations_params(args):
    """Build parameters for recommendations endpoint."""
    # Validate strategy
    strategy = args.get('strategy', 'likes')
    if strategy not in ['likes', 'played', 'discover']:
        strategy = 'likes'

    # Validate limit
    limit, error = validate_limit_param(args, default=10, max_value=50)
    if error:
        # This shouldn't happen with proper validation, but default to 10
        limit = 10

    return (strategy, limit)


@bp.route('/recommendations', methods=['GET'])
@api_endpoint('get_recommendations',
              custom_params_builder=_build_recommendations_params,
              error_message='An error occurred processing your request')
def get_recommendations_api() -> Response:
    """Get video recommendations."""
    pass  # Decorator handles everything


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
def retry_pending_videos() -> Response:
    """
    Manually trigger retry of pending videos with quota_exceeded reason.
    Processes videos in batches to avoid overwhelming the YouTube API.
    API endpoint called from JavaScript - CSRF will be exempted in app.py.
    """
    import time
    from helpers.search_helpers import search_and_match_video
    from helpers.cache_helpers import find_cached_video

    try:
        # Get batch size from request (default: 5, max: 50)
        batch_size = int(request.args.get('batch_size', 5))
        batch_size = max(1, min(batch_size, MAX_BATCH_SIZE))

        # Note: Rate limiting removed for manual retry button - user controls when to retry

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

        # Process each video (quota errors will be raised as QuotaExceededError)
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
                video = search_and_match_video(ha_media, yt_api, db)

                if video and video.get('yt_video_id'):
                    # Found and matched - search_and_match_video returns the video dict directly
                    db.resolve_pending_video(ha_content_id, video)
                    resolved += 1
                    logger.info(f"Resolved from YouTube: {ha_title}")
                else:
                    # Search returned None - genuinely not found
                    db.mark_pending_not_found(ha_content_id)
                    not_found += 1
                    logger.info(f"Not found: {ha_title}")

                # Delay between requests to avoid hammering API
                time.sleep(2)

            except Exception as e:
                logger.error(f"Error processing pending video: {e}")
                failed += 1

        processed = len(pending_videos)

        # Build message
        message = f"Processed {processed} pending videos: {resolved} resolved, {failed} failed, {not_found} not found"

        # Invalidate stats cache if any videos were resolved
        if resolved > 0 or not_found > 0:
            db.invalidate_stats_cache()
            logger.debug("Stats cache invalidated after manual retry")

        return jsonify({
            'success': True,
            'processed': processed,
            'resolved': resolved,
            'failed': failed,
            'not_found': not_found,
            'message': message
        })

    except ValueError:
        return error_response( 'Invalid batch_size parameter', 400)
    except Exception as e:
        logger.error(f"Error in manual pending video retry: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return error_response( 'Failed to retry pending videos', 500)


@bp.route('/cleanup/unknown', methods=['POST'])
def cleanup_unknown_entries() -> Response:
    """
    Remove garbage 'Unknown' entries from the database.
    Home Assistant API never returns 'Unknown', so these are artifacts that waste space and quota.
    """
    try:
        logger.info("Starting cleanup of Unknown entries...")

        # Run cleanup
        result = db.cleanup_unknown_entries()

        # Invalidate stats cache since database changed
        if result.get('removed', 0) > 0:
            db.invalidate_stats_cache()
            logger.info("Stats cache invalidated after cleanup")

        message = f"Cleanup complete: Removed {result['removed']} Unknown entries. Database now has {result['after']} total entries."

        return jsonify({
            'success': True,
            'removed': result['removed'],
            'before': result['before'],
            'after': result['after'],
            'message': message
        })

    except Exception as e:
        logger.error(f"Error during Unknown entries cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return error_response('Failed to cleanup Unknown entries', 500)
