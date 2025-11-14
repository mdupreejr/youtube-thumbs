"""
Unit tests for unified sorting helper.
"""
import pytest
from helpers.sorting_helpers import sort_table_data


def test_sort_numeric_ascending():
    """Test numeric sorting in ascending order."""
    data = [
        {'id': 1, 'count': 10},
        {'id': 2, 'count': 5},
        {'id': 3, 'count': 20}
    ]
    sort_key_map = {'count': 'count'}
    result = sort_table_data(data, 'count', 'asc', sort_key_map, {'count'})
    assert result[0]['count'] == 5
    assert result[1]['count'] == 10
    assert result[2]['count'] == 20


def test_sort_numeric_descending():
    """Test numeric sorting in descending order."""
    data = [
        {'id': 1, 'count': 10},
        {'id': 2, 'count': 5},
        {'id': 3, 'count': 20}
    ]
    sort_key_map = {'count': 'count'}
    result = sort_table_data(data, 'count', 'desc', sort_key_map, {'count'})
    assert result[0]['count'] == 20
    assert result[1]['count'] == 10
    assert result[2]['count'] == 5


def test_sort_string_case_insensitive():
    """Test string sorting is case-insensitive."""
    data = [
        {'id': 1, 'name': 'Zebra'},
        {'id': 2, 'name': 'apple'},
        {'id': 3, 'name': 'Banana'}
    ]
    sort_key_map = {'name': 'name'}
    result = sort_table_data(data, 'name', 'asc', sort_key_map)
    assert result[0]['name'] == 'apple'
    assert result[1]['name'] == 'Banana'
    assert result[2]['name'] == 'Zebra'


def test_sort_handles_none_values():
    """Test that None values are handled correctly."""
    data = [
        {'id': 1, 'value': 'B'},
        {'id': 2, 'value': None},
        {'id': 3, 'value': 'A'}
    ]
    sort_key_map = {'value': 'value'}
    result = sort_table_data(data, 'value', 'asc', sort_key_map)
    assert result[0]['value'] == ''  # None becomes empty string
    assert result[1]['value'] == 'A'
    assert result[2]['value'] == 'B'


def test_sort_boolean_values():
    """Test sorting of boolean values."""
    data = [
        {'id': 1, 'success': True},
        {'id': 2, 'success': False},
        {'id': 3, 'success': True}
    ]
    sort_key_map = {'success': 'success'}
    result = sort_table_data(data, 'success', 'asc', sort_key_map)
    assert result[0]['success'] == False
    assert result[1]['success'] == True
    assert result[2]['success'] == True


def test_sort_with_missing_key():
    """Test sorting with a key that doesn't exist in some records."""
    data = [
        {'id': 1, 'count': 10},
        {'id': 2},  # Missing 'count'
        {'id': 3, 'count': 5}
    ]
    sort_key_map = {'count': 'count'}
    result = sort_table_data(data, 'count', 'asc', sort_key_map, {'count'})
    assert result[0]['count'] == 0  # Missing treated as 0
    assert result[1]['count'] == 5
    assert result[2]['count'] == 10
