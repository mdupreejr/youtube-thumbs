#!/usr/bin/env python3
"""
Test script to verify the regex security fixes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from helpers.template_helpers import sanitize_html

def test_security_fixes():
    """Test that the regex vulnerabilities are fixed."""
    
    print("Testing security fixes...")
    
    # Test script tag handling (should remove script tags)
    test_cases = [
        # Basic script tags
        "<script>alert('xss')</script>",
        "<script >alert('xss')</script >",
        "<script\n>alert('xss')</script\n>",
        
        # Malicious patterns that could cause ReDoS
        "<script" + ">" * 1000 + "alert('xss')" + "</script" + ">" * 1000,
        
        # Safe HTML should be preserved
        "<span>Safe text</span>",
        "<a href='https://example.com'>Link</a>",
        "<strong>Bold text</strong>",
    ]
    
    for i, test_case in enumerate(test_cases):
        print(f"Test {i+1}: Testing input of length {len(test_case)}")
        try:
            result = sanitize_html(test_case)
            print(f"  Input:  {test_case[:100]}{'...' if len(test_case) > 100 else ''}")
            print(f"  Output: {result[:100]}{'...' if len(result) > 100 else ''}")
            
            # Check that script tags are removed
            if '<script' in test_case.lower():
                if '<script' in result.lower():
                    print("  ❌ FAIL: Script tags not properly removed")
                else:
                    print("  ✅ PASS: Script tags removed")
            else:
                print("  ✅ PASS: Input processed")
                
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
        print()
    
    print("Security fix testing complete!")

if __name__ == "__main__":
    test_security_fixes()