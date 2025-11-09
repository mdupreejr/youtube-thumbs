"""
Tests for template helper functions and classes.

These tests verify the security, functionality, and reliability of the
unified table template system.
"""

import unittest
from helpers.template_helpers import (
    sanitize_html, TableCell, TableColumn, TableRow, TableData, PageConfig,
    format_youtube_link, format_badge, create_pagination_info, create_status_message,
    create_filter_option
)


class TestHtmlSanitization(unittest.TestCase):
    """Test HTML sanitization functionality."""
    
    def test_sanitize_html_removes_script_tags(self):
        """Test that script tags are completely removed."""
        malicious_html = '<script>alert("xss")</script><span>Safe content</span>'
        result = sanitize_html(malicious_html)
        self.assertNotIn('<script>', result)
        self.assertNotIn('alert', result)
        self.assertIn('Safe content', result)
    
    def test_sanitize_html_removes_event_handlers(self):
        """Test that event handler attributes are removed."""
        malicious_html = '<span onclick="alert(1)">Click me</span>'
        result = sanitize_html(malicious_html)
        self.assertNotIn('onclick', result)
        self.assertIn('Click me', result)
    
    def test_sanitize_html_removes_javascript_urls(self):
        """Test that javascript: URLs are removed."""
        malicious_html = '<a href="javascript:alert(1)">Link</a>'
        result = sanitize_html(malicious_html)
        self.assertNotIn('javascript:', result)
        self.assertIn('Link', result)
    
    def test_sanitize_html_preserves_safe_content(self):
        """Test that safe HTML content is preserved."""
        safe_html = '<a href="https://example.com" target="_blank">Link</a><span class="badge">Badge</span>'
        result = sanitize_html(safe_html)
        self.assertIn('https://example.com', result)
        self.assertIn('target="_blank"', result)
        self.assertIn('class="badge"', result)
    
    def test_sanitize_html_empty_input(self):
        """Test handling of empty or None input."""
        self.assertEqual(sanitize_html(''), '')
        self.assertEqual(sanitize_html(None), '')


class TestTableCell(unittest.TestCase):
    """Test TableCell class functionality."""
    
    def test_table_cell_basic_creation(self):
        """Test basic cell creation with value only."""
        cell = TableCell('Test Value')
        self.assertEqual(cell.value, 'Test Value')
        self.assertIsNone(cell.html)
        self.assertIsNone(cell.style)
        self.assertIsNone(cell.title)
    
    def test_table_cell_with_safe_html(self):
        """Test cell creation with safe HTML content."""
        safe_html = '<a href="https://example.com">Link</a>'
        cell = TableCell('Link', html=safe_html)
        self.assertEqual(cell.value, 'Link')
        self.assertIn('https://example.com', cell.html)
    
    def test_table_cell_sanitizes_malicious_html(self):
        """Test that malicious HTML is sanitized in cell creation."""
        malicious_html = '<script>alert("xss")</script><span>Safe</span>'
        cell = TableCell('Test', html=malicious_html)
        self.assertNotIn('<script>', cell.html)
        self.assertNotIn('alert', cell.html)
        self.assertIn('Safe', cell.html or '')
    
    def test_table_cell_escapes_attributes(self):
        """Test that style and title attributes are properly escaped."""
        cell = TableCell('Test', style='color: red; "malicious', title='Title with " quotes')
        self.assertNotIn('"malicious', cell.style)
        self.assertIn('&quot;', cell.style)  # HTML escaped quotes
        self.assertIn('&quot;', cell.title)
    
    def test_table_cell_none_value_handling(self):
        """Test handling of None values."""
        cell = TableCell(None)
        self.assertEqual(cell.value, '')
    
    def test_table_cell_to_dict(self):
        """Test conversion to dictionary."""
        cell = TableCell('Value', html='<span>HTML</span>', style='color: blue', title='Tooltip')
        result = cell.to_dict()
        expected_keys = {'value', 'html', 'style', 'title'}
        self.assertEqual(set(result.keys()), expected_keys)


class TestTableColumn(unittest.TestCase):
    """Test TableColumn class functionality."""
    
    def test_table_column_creation(self):
        """Test basic column creation."""
        column = TableColumn('test_key', 'Test Label')
        self.assertEqual(column.key, 'test_key')
        self.assertEqual(column.label, 'Test Label')
        self.assertTrue(column.sortable)
        self.assertTrue(column.resizable)
        self.assertIsNone(column.width)
    
    def test_table_column_with_options(self):
        """Test column creation with custom options."""
        column = TableColumn('key', 'Label', sortable=False, resizable=False, width='200px')
        self.assertFalse(column.sortable)
        self.assertFalse(column.resizable)
        self.assertEqual(column.width, '200px')
    
    def test_table_column_to_dict(self):
        """Test conversion to dictionary."""
        column = TableColumn('key', 'Label', width='100px')
        result = column.to_dict()
        expected_keys = {'key', 'label', 'sortable', 'resizable', 'width'}
        self.assertEqual(set(result.keys()), expected_keys)


class TestTableRow(unittest.TestCase):
    """Test TableRow class functionality."""
    
    def test_table_row_creation(self):
        """Test basic row creation."""
        cells = [TableCell('Cell 1'), TableCell('Cell 2')]
        row = TableRow(cells)
        self.assertEqual(len(row.cells), 2)
        self.assertFalse(row.clickable)
        self.assertIsNone(row.id)
    
    def test_table_row_clickable(self):
        """Test clickable row creation."""
        cells = [TableCell('Cell 1')]
        row = TableRow(cells, clickable=True, row_id='row_123')
        self.assertTrue(row.clickable)
        self.assertEqual(row.id, 'row_123')
    
    def test_table_row_to_dict(self):
        """Test conversion to dictionary."""
        cells = [TableCell('Cell 1')]
        row = TableRow(cells, clickable=True, row_id='test_id')
        result = row.to_dict()
        expected_keys = {'cells', 'clickable', 'id'}
        self.assertEqual(set(result.keys()), expected_keys)


class TestTableData(unittest.TestCase):
    """Test TableData class functionality."""
    
    def test_table_data_creation(self):
        """Test basic table data creation."""
        columns = [TableColumn('col1', 'Column 1')]
        rows = [TableRow([TableCell('Value 1')])]
        table_data = TableData(columns, rows)
        self.assertEqual(len(table_data.columns), 1)
        self.assertEqual(len(table_data.rows), 1)
    
    def test_table_data_to_dict(self):
        """Test conversion to dictionary."""
        columns = [TableColumn('col1', 'Column 1')]
        rows = [TableRow([TableCell('Value 1')])]
        table_data = TableData(columns, rows)
        result = table_data.to_dict()
        expected_keys = {'columns', 'rows'}
        self.assertEqual(set(result.keys()), expected_keys)


class TestPageConfig(unittest.TestCase):
    """Test PageConfig class functionality."""
    
    def test_page_config_creation(self):
        """Test basic page config creation."""
        config = PageConfig('Test Page', 'test_nav', 'test_storage')
        self.assertEqual(config.title, 'Test Page')
        self.assertEqual(config.nav_active, 'test_nav')
        self.assertEqual(config.storage_key, 'test_storage')
    
    def test_page_config_auto_storage_key(self):
        """Test automatic storage key generation."""
        config = PageConfig('Test Page', 'test_nav')
        self.assertEqual(config.storage_key, 'table-test_nav')
    
    def test_page_config_add_methods(self):
        """Test fluent interface methods."""
        config = PageConfig('Test')
        config.add_back_link('/back', 'Back Text')
        config.add_main_tab('Tab 1', '/tab1', True)
        config.add_sub_tab('Sub Tab', '/sub', False)
        config.add_filter('filter1', 'Filter Label', [{'value': 'val', 'label': 'Label'}])
        config.add_hidden_field('hidden', 'value')
        config.set_empty_state('📭', 'No Data', 'No items found')
        config.set_modal_config('/api/details', 'Modal Title', 'formatter')
        
        self.assertEqual(config.back_link, '/back')
        self.assertEqual(config.back_text, 'Back Text')
        self.assertEqual(len(config.main_tabs), 1)
        self.assertEqual(len(config.sub_tabs), 1)
        self.assertEqual(len(config.filters), 1)
        self.assertEqual(len(config.hidden_fields), 1)
        self.assertIsNotNone(config.empty_state)
        self.assertEqual(config.modal_api_url, '/api/details')
        self.assertEqual(config.row_click_handler, 'showRowDetails')


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions."""
    
    def test_format_youtube_link(self):
        """Test YouTube link formatting."""
        link = format_youtube_link('dQw4w9WgXcQ', 'Test Video')
        self.assertIn('youtube.com/watch?v=dQw4w9WgXcQ', link)
        self.assertIn('Test Video', link)
        self.assertIn('target="_blank"', link)
    
    def test_format_youtube_link_sanitization(self):
        """Test that YouTube link inputs are properly sanitized."""
        # Test with potentially malicious input
        link = format_youtube_link('"><script>alert(1)</script>', 'Test')
        self.assertNotIn('<script>', link)
        self.assertNotIn('alert', link)
    
    def test_format_badge(self):
        """Test badge formatting."""
        badge = format_badge('Success', 'success')
        self.assertIn('badge-success', badge)
        self.assertIn('Success', badge)
    
    def test_format_badge_sanitization(self):
        """Test badge input sanitization."""
        badge = format_badge('<script>alert(1)</script>', 'success')
        self.assertNotIn('<script>', badge)
        self.assertNotIn('alert', badge)
    
    def test_create_pagination_info(self):
        """Test pagination info creation."""
        pagination = create_pagination_info(3, 10, 50, '/test')
        self.assertEqual(pagination['current_page'], 3)
        self.assertEqual(pagination['total_pages'], 5)
        self.assertIn(3, pagination['page_numbers'])
    
    def test_create_pagination_info_single_page(self):
        """Test pagination with only one page."""
        pagination = create_pagination_info(1, 10, 5, '/test')
        self.assertIsNone(pagination)
    
    def test_create_status_message(self):
        """Test status message creation."""
        message = create_status_message(10, 50, 'items')
        self.assertEqual(message, 'Showing 10 of 50 items')
        
        message2 = create_status_message(25, item_type='songs')
        self.assertEqual(message2, 'Showing 25 songs')
    
    def test_create_filter_option(self):
        """Test filter option creation."""
        option = create_filter_option('value1', 'Label 1', True)
        expected = {'value': 'value1', 'label': 'Label 1', 'selected': True}
        self.assertEqual(option, expected)


if __name__ == '__main__':
    # Run the tests
    unittest.main()