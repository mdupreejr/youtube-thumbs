"""
Base Route Handler for YouTube Thumbs Rating
Provides consistent routing architecture across all pages
"""

from typing import Dict, Any, Optional, List, Set
from flask import render_template, g, current_app, jsonify, request
from logging_helper import LoggingHelper, LogType
import traceback
from html import escape

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


class BaseRouteHandler:
    """
    Base class for all route handlers.
    Ensures consistent data handling, validation, and error management.
    """

    # Template field requirements - subclasses should override
    TEMPLATE_REQUIREMENTS: Dict[str, Set[str]] = {
        'base.html': {'ingress_path', 'config'},
        'stats.html': {
            'ingress_path', 'config', 'current_tab',
            'summary.total_videos', 'summary.total_plays',
            'summary.liked', 'summary.disliked', 'summary.skipped',
            'summary.unrated', 'summary.like_percentage',
            'summary.unique_channels',
            'most_played', 'top_channels', 'recent_activity',
            'rating_percentages.liked', 'rating_percentages.disliked',
            'rating_percentages.unrated'
        },
        'index_server.html': {
            'ingress_path', 'config', 'tab', 'ha_test', 'yt_test',
            'db_test', 'metrics'
        },
        'table_viewer.html': {
            'ingress_path', 'config', 'page_config'
        }
    }

    def __init__(self, db=None, ha_api=None, yt_api=None, metrics=None):
        """Initialize the route handler with optional dependencies."""
        self.db = db
        self.ha_api = ha_api
        self.yt_api = yt_api
        self.metrics = metrics

    def get_common_data(self) -> Dict[str, Any]:
        """
        Get common data that should be included in every template render.
        This ensures consistency across all pages.
        """
        return {
            'ingress_path': g.get('ingress_path', ''),
            'config': {
                'version': current_app.config.get('VERSION', 'unknown'),
                'debug': current_app.config.get('DEBUG', False),
            },
            'request': {
                'path': request.path,
                'method': request.method,
                'args': request.args.to_dict()
            }
        }

    def validate_template_data(self, template_name: str, data: Dict[str, Any]) -> None:
        """
        Validate that all required fields for a template are present.
        Raises ValueError if required fields are missing.
        """
        # Get requirements for this template
        requirements = self.TEMPLATE_REQUIREMENTS.get(template_name, set())

        # Check each required field
        missing_fields = []
        for field in requirements:
            # Handle nested field checks (e.g., 'summary.like_percentage')
            if '.' in field:
                parts = field.split('.')
                current = data
                field_exists = True
                for part in parts:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        field_exists = False
                        break
                if not field_exists:
                    missing_fields.append(field)
            elif field not in data:
                missing_fields.append(field)

        if missing_fields:
            raise ValueError(
                f"Template '{template_name}' is missing required fields: {', '.join(missing_fields)}"
            )

    def ensure_dict_fields(self, data_dict: Dict[str, Any], required_fields: Dict[str, Any]) -> None:
        """
        Ensure a dictionary has all required fields with default values.

        Args:
            data_dict: The dictionary to check and update
            required_fields: Dict of field_name -> default_value
        """
        for field, default_value in required_fields.items():
            if field not in data_dict:
                data_dict[field] = default_value
                logger.debug(f"Added missing field '{field}' with default value: {default_value}")

    def render_page(
        self,
        template_name: str,
        validate: bool = True,
        **template_data
    ) -> str:
        """
        Render a template with common data and validation.

        Args:
            template_name: Name of the template file
            validate: Whether to validate template data
            **template_data: Additional data to pass to template

        Returns:
            Rendered HTML string
        """
        try:
            # Start with common data
            data = self.get_common_data()

            # Add template-specific data
            data.update(template_data)

            # Validate if requested
            if validate:
                try:
                    self.validate_template_data(template_name, data)
                except ValueError as e:
                    # Strict validation in debug mode
                    if current_app.config.get('DEBUG', False):
                        raise ValueError(f"Template validation failed: {e}")
                    else:
                        logger.warning(f"Template validation warning: {e}")
                        # In production, log but continue for now

            # Render template
            return render_template(template_name, **data)

        except Exception as e:
            logger.error(f"Error rendering template '{template_name}': {e}")
            logger.error(traceback.format_exc())

            # Return error page
            return self.render_error_page(
                error_message=f"Failed to load {template_name.replace('.html', '')} page",
                error_details=str(e) if current_app.config.get('DEBUG') else None
            )

    def render_error_page(
        self,
        error_message: str = "An error occurred",
        error_details: Optional[str] = None,
        status_code: int = 500
    ) -> tuple:
        """
        Render a consistent error page.

        Args:
            error_message: Main error message to display
            error_details: Additional details (only shown in debug mode)
            status_code: HTTP status code

        Returns:
            Tuple of (rendered_html, status_code)
        """
        data = self.get_common_data()
        data.update({
            'error_message': error_message,
            'error_details': error_details if current_app.config.get('DEBUG') else None,
            'status_code': status_code
        })

        try:
            # Try to use error template if it exists
            return render_template('error.html', **data), status_code
        except Exception as e:
            logger.error(f"Failed to render error template: {e}")
            # Fallback to simple HTML
            html = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Error {status_code}</title></head>
            <body>
                <h1>{escape(str(error_message))}</h1>
                {'<p>' + escape(str(error_details)) + '</p>' if error_details else ''}
                <p><a href="{escape(data['ingress_path'])}/">Return to Home</a></p>
            </body>
            </html>
            """
            return html, status_code

    def render_json(
        self,
        data: Dict[str, Any],
        status_code: int = 200
    ) -> tuple:
        """
        Render JSON response with consistent structure.

        Args:
            data: Data to return as JSON
            status_code: HTTP status code

        Returns:
            Tuple of (json_response, status_code)
        """
        response_data = {
            'success': status_code < 400,
            'data': data,
            'meta': {
                'version': current_app.config.get('VERSION', 'unknown'),
                'ingress_path': g.get('ingress_path', '')
            }
        }

        return jsonify(response_data), status_code

    def handle_error(
        self,
        error: Exception,
        context: str = "processing request"
    ) -> tuple:
        """
        Handle an error consistently.

        Args:
            error: The exception that occurred
            context: What was being done when error occurred

        Returns:
            Tuple of (response, status_code)
        """
        logger.error(f"Error {context}: {error}")
        logger.error(traceback.format_exc())

        # Determine if JSON or HTML response
        if request.path.startswith('/api/') or request.headers.get('Accept') == 'application/json':
            return self.render_json(
                {'error': str(error), 'context': context},
                status_code=500
            )
        else:
            return self.render_error_page(
                error_message=f"Error {context}",
                error_details=str(error)
            )


class TemplateRequirements:
    """
    Centralized documentation of template field requirements.
    This helps prevent data mismatches between backend and frontend.
    """

    STATS_HTML = {
        'summary': {
            'total_videos': int,
            'total_plays': int,
            'liked': int,
            'disliked': int,
            'skipped': int,
            'unrated': int,
            'like_percentage': float,
            'unique_channels': int
        },
        'most_played': list,  # List of video dicts
        'top_channels': list,  # List of channel dicts
        'recent_activity': list,  # List of activity dicts
        'rating_percentages': {
            'liked': float,
            'disliked': float,
            'unrated': float
        },
        'current_tab': str,
        'ingress_path': str
    }

    INDEX_SERVER_HTML = {
        'tab': str,  # 'tests' or 'rating'
        'ha_test': dict,
        'yt_test': dict,
        'db_test': dict,
        'metrics': dict,
        'videos': list,  # For rating tab
        'pagination': dict,  # For rating tab
        'ingress_path': str
    }

    TABLE_VIEWER_HTML = {
        'page_config': dict,  # PageConfig object
        'ingress_path': str
    }

    @classmethod
    def validate_data(cls, template_name: str, data: dict) -> List[str]:
        """
        Validate data against template requirements.
        Returns list of missing or invalid fields.
        """
        errors = []
        requirements = None

        # Get requirements for template
        if 'stats.html' in template_name:
            requirements = cls.STATS_HTML
        elif 'index_server.html' in template_name:
            requirements = cls.INDEX_SERVER_HTML
        elif 'table_viewer.html' in template_name:
            requirements = cls.TABLE_VIEWER_HTML

        if not requirements:
            return errors

        # Check each required field
        for field, expected_type in requirements.items():
            if field not in data:
                errors.append(f"Missing field: {field}")
            elif expected_type != dict and expected_type != list:
                # Type checking for simple types
                if not isinstance(data[field], expected_type):
                    errors.append(
                        f"Field '{field}' should be {expected_type.__name__}, "
                        f"got {type(data[field]).__name__}"
                    )

        return errors