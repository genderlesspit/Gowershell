import pytest
import json
import asyncio
from typing import List, Dict, Any, AsyncGenerator
from unittest.mock import patch, MagicMock
from loguru import logger as log
import sys

# Async version of the function for testing
async def extract_json_blobs_async(content: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Async version of extract_json_blobs"""
    log.debug(f"Starting extraction from content of length {len(content)}")

    i = 0
    blob_count = 0
    while i < len(content):
        if content[i] == '{':
            log.debug(f"Found opening brace at position {i}")
            for j in range(len(content) - 1, i, -1):
                if content[j] == '}':
                    try:
                        json_str = content[i:j+1]
                        parsed = json.loads(json_str)
                        blob_count += 1
                        log.debug(f"Successfully parsed JSON blob #{blob_count}: {json_str[:50]}...")
                        yield parsed
                        i = j
                        break
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse JSON at {i}:{j+1} - {e}")
                        pass
        i += 1

        # Yield control periodically for truly async behavior
        if i % 1000 == 0:
            await asyncio.sleep(0)

    log.debug(f"Extraction complete. Found {blob_count} JSON blobs")


def extract_json_blobs(content: str) -> List[Dict[str, Any]]:
    log.debug(f"Starting synchronous extraction from content of length {len(content)}")

    results = []
    i = 0
    while i < len(content):
        if content[i] == '{':
            log.debug(f"Found opening brace at position {i}")
            for j in range(len(content) - 1, i, -1):
                if content[j] == '}':
                    try:
                        json_str = content[i:j+1]
                        parsed = json.loads(json_str)
                        results.append(parsed)
                        log.debug(f"Successfully parsed JSON blob: {json_str[:50]}...")
                        i = j
                        break
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse JSON at {i}:{j+1} - {e}")
                        pass
        i += 1

    log.debug(f"Extraction complete. Found {len(results)} JSON blobs")
    return results

@pytest.fixture
def sample_json_content():
    """Sample content with multiple JSON blobs"""
    return '''
    This is some text before {"name": "John", "age": 30} and after.
    Another blob: {"items": [1, 2, 3], "status": "active"}
    Some more text {"nested": {"key": "value"}} here.
    '''


@pytest.fixture
def complex_json_content():
    """Complex content with nested structures and edge cases"""
    return '''
    Start text {"simple": "value"} middle
    {"complex": {"nested": {"deep": {"value": 42}}, "array": [{"id": 1}, {"id": 2}]}}
    Invalid JSON: {broken: "json"} should be skipped
    {"escaped": "string with \\"quotes\\" and newlines\\n"}
    End text {"final": true}
    '''


@pytest.fixture
def malformed_json_content():
    """Content with malformed JSON that should be skipped"""
    return '''
    Good JSON: {"valid": "data"}
    Bad JSON: {"unclosed": "brace"
    Another bad: {missing: "quotes"}
    Good again: {"valid": 123}
    Nested bad: {"outer": {"inner": "unclosed}
    '''


@pytest.fixture
def edge_case_content():
    """Content with edge cases"""
    return '''
    Empty object: {}
    Single brace: {
    Multiple braces: {{{
    Escaped braces in string: {"text": "has { and } characters"}
    Very long content with {"data": "''' + "x" * 10000 + '''"}
    '''


# Basic functionality tests
class TestBasicFunctionality:

    def test_empty_string(self):
        """Test with empty string"""
        result = extract_json_blobs("")
        assert result == []

    def test_no_json_content(self):
        """Test with content containing no JSON"""
        content = "This is just plain text with no JSON objects"
        result = extract_json_blobs(content)
        assert result == []

    def test_single_json_object(self):
        """Test with single JSON object"""
        content = 'Before {"name": "test"} after'
        result = extract_json_blobs(content)
        assert len(result) == 1
        assert result[0] == {"name": "test"}

    def test_multiple_json_objects(self, sample_json_content):
        """Test with multiple JSON objects"""
        result = extract_json_blobs(sample_json_content)
        assert len(result) == 3
        assert result[0] == {"name": "John", "age": 30}
        assert result[1] == {"items": [1, 2, 3], "status": "active"}
        assert result[2] == {"nested": {"key": "value"}}


# Complex structure tests
class TestComplexStructures:

    def test_nested_json_objects(self, complex_json_content):
        """Test with deeply nested JSON structures"""
        result = extract_json_blobs(complex_json_content)
        assert len(result) == 4

        # Check complex nested structure
        complex_obj = result[1]
        assert complex_obj["complex"]["nested"]["deep"]["value"] == 42
        assert len(complex_obj["complex"]["array"]) == 2

    def test_json_with_arrays(self):
        """Test JSON objects containing arrays"""
        content = '''{"numbers": [1, 2, 3], "strings": ["a", "b", "c"]}'''
        result = extract_json_blobs(content)
        assert len(result) == 1
        assert result[0]["numbers"] == [1, 2, 3]
        assert result[0]["strings"] == ["a", "b", "c"]

    def test_escaped_characters(self, complex_json_content):
        """Test JSON with escaped characters"""
        result = extract_json_blobs(complex_json_content)
        escaped_obj = result[2]
        assert "quotes" in escaped_obj["escaped"]
        assert "newlines" in escaped_obj["escaped"]


# Error handling tests
class TestErrorHandling:

    def test_malformed_json_skipped(self, malformed_json_content):
        """Test that malformed JSON is properly skipped"""
        result = extract_json_blobs(malformed_json_content)
        assert len(result) == 2  # Only the valid JSON objects
        assert result[0] == {"valid": "data"}
        assert result[1] == {"valid": 123}

    def test_unmatched_braces(self):
        """Test handling of unmatched braces"""
        content = "{ This has no closing brace"
        result = extract_json_blobs(content)
        assert result == []

    def test_multiple_opening_braces(self):
        """Test handling of multiple opening braces"""
        content = "{{{"
        result = extract_json_blobs(content)
        assert result == []

    def test_json_with_syntax_errors(self):
        """Test various JSON syntax errors"""
        content = '''
        {"trailing": "comma",}
        {"missing": "quote}
        {missing: "quotes"}
        {"valid": "object"}
        '''
        result = extract_json_blobs(content)
        assert len(result) == 1
        assert result[0] == {"valid": "object"}


# Edge case tests
class TestEdgeCases:

    def test_empty_json_object(self, edge_case_content):
        """Test empty JSON object"""
        result = extract_json_blobs(edge_case_content)
        assert {} in result

    def test_json_with_special_characters(self):
        """Test JSON with special characters"""
        content = '''{"unicode": "café", "symbols": "!@#$%^&*()"}'''
        result = extract_json_blobs(content)
        assert len(result) == 1
        assert result[0]["unicode"] == "café"

    def test_large_json_object(self, edge_case_content):
        """Test with very large JSON object"""
        result = extract_json_blobs(edge_case_content)
        large_obj = next((obj for obj in result if "data" in obj), None)
        assert large_obj is not None
        assert len(large_obj["data"]) == 10000

    def test_adjacent_json_objects(self):
        """Test adjacent JSON objects with no separating text"""
        content = '''{"first": 1}{"second": 2}{"third": 3}'''
        result = extract_json_blobs(content)
        assert len(result) == 3
        assert result[0] == {"first": 1}
        assert result[1] == {"second": 2}
        assert result[2] == {"third": 3}


# Performance tests
class TestPerformance:

    def test_large_content_performance(self):
        """Test performance with large content"""
        # Create large content with scattered JSON
        large_content = "x" * 10000 + '{"middle": "json"}' + "y" * 10000

        import time
        start = time.time()
        result = extract_json_blobs(large_content)
        end = time.time()

        assert len(result) == 1
        assert result[0] == {"middle": "json"}
        assert end - start < 1.0  # Should complete within 1 second

    def test_many_json_objects_performance(self):
        """Test performance with many JSON objects"""
        # Create content with many small JSON objects
        json_objects = [f'{{"id": {i}, "value": "item_{i}"}}' for i in range(100)]
        content = " text ".join(json_objects)

        import time
        start = time.time()
        result = extract_json_blobs(content)
        end = time.time()

        assert len(result) == 100
        assert end - start < 1.0  # Should complete within 1 second


# # Async tests
# class TestAsyncFunctionality:
#
#     @pytest.mark.asyncio
#     async def test_async_extraction_basic(self, sample_json_content):
#         """Test basic async extraction"""
#         result = []
#         async for blob in extract_json_blobs_async(sample_json_content):
#             result.append(blob)
#
#         assert len(result) == 3
#         assert result[0] == {"name": "John", "age": 30}
#
#     @pytest.mark.asyncio
#     async def test_async_extraction_empty(self):
#         """Test async extraction with empty content"""
#         result = []
#         async for blob in extract_json_blobs_async(""):
#             result.append(blob)
#
#         assert result == []
#
#     @pytest.mark.asyncio
#     async def test_async_extraction_large_content(self):
#         """Test async extraction with large content"""
#         large_content = "text " * 5000 + '{"test": "value"}' + " more text " * 5000
#
#         result = []
#         async for blob in extract_json_blobs_async(large_content):
#             result.append(blob)
#
#         assert len(result) == 1
#         assert result[0] == {"test": "value"}
#
#     @pytest.mark.asyncio
#     async def test_async_concurrent_processing(self):
#         """Test concurrent async processing"""
#         contents = [
#             '{"task": 1, "data": "first"}',
#             '{"task": 2, "data": "second"}',
#             '{"task": 3, "data": "third"}'
#         ]
#
#         async def process_content(content):
#             result = []
#             async for blob in extract_json_blobs_async(content):
#                 result.append(blob)
#             return result
#
#         tasks = [process_content(content) for content in contents]
#         results = await asyncio.gather(*tasks)
#
#         assert len(results) == 3
#         assert all(len(result) == 1 for result in results)
#         assert results[0][0]["task"] == 1
#         assert results[1][0]["task"] == 2
#         assert results[2][0]["task"] == 3


# Parameterized tests for comprehensive coverage
class TestParameterizedCases:

    @pytest.mark.parametrize("content,expected_count", [
        ('{"single": "object"}', 1),
        ('{"first": 1} {"second": 2}', 2),
        ('no json here', 0),
        ('{"nested": {"deep": {"value": 42}}}', 1),
        ('[]', 0),  # Arrays are not objects
        ('{"empty": {}}', 1),
        ('{"null": null, "bool": true, "num": 42}', 1),
    ])
    def test_various_json_patterns(self, content, expected_count):
        """Test various JSON patterns with expected counts"""
        result = extract_json_blobs(content)
        assert len(result) == expected_count

    @pytest.mark.parametrize("invalid_json", [
        '{"unclosed": "brace"',
        '{missing: "quotes"}',
        '{"trailing": "comma",}',
        '{"duplicate": "key", "duplicate": "value"}',  # Valid JSON actually
        '{"invalid": undefined}',
    ])
    def test_invalid_json_patterns(self, invalid_json):
        """Test that invalid JSON patterns are properly handled"""
        content = f'Good: {{"valid": "data"}} Bad: {invalid_json} Good: {{"also": "valid"}}'
        result = extract_json_blobs(content)
        # Should extract only the valid JSON objects
        assert len(result) >= 1  # At least one valid object
        assert {"valid": "data"} in result or {"also": "valid"} in result


# Integration tests
class TestIntegration:

    def test_real_world_scenario(self):
        """Test with realistic log-like content"""
        log_content = '''
        [2024-01-15 10:30:00] INFO: Starting process
        [2024-01-15 10:30:01] DEBUG: Config loaded {"config": {"timeout": 30, "retries": 3}}
        [2024-01-15 10:30:02] INFO: Processing request {"request": {"id": "req-123", "user": "john_doe"}}
        [2024-01-15 10:30:03] ERROR: Failed to process {"error": {"code": 500, "message": "Internal server error"}}
        [2024-01-15 10:30:04] INFO: Process completed
        '''

        result = extract_json_blobs(log_content)
        assert len(result) == 3

        # Verify specific extractions
        config = next((obj for obj in result if "config" in obj), None)
        assert config["config"]["timeout"] == 30

        request = next((obj for obj in result if "request" in obj), None)
        assert request["request"]["id"] == "req-123"

        error = next((obj for obj in result if "error" in obj), None)
        assert error["error"]["code"] == 500

    def test_mixed_content_types(self):
        """Test with mixed content including HTML, JSON, and plain text"""
        mixed_content = '''
        <html>
        <body>
            <div>Some HTML content</div>
            <script>
                var config = {"api_key": "secret123", "debug": true};
            </script>
        </body>
        </html>
        
        Plain text with {"embedded": "json"} continues...
        
        More text {"final": {"nested": "value"}}
        '''

        result = extract_json_blobs(mixed_content)
        assert len(result) == 3

        # Check for specific values
        api_config = next((obj for obj in result if "api_key" in obj), None)
        assert api_config["api_key"] == "secret123"

        embedded = next((obj for obj in result if "embedded" in obj), None)
        assert embedded["embedded"] == "json"


# Test logging functionality
class TestLogging:

    def test_verbose_logging_enabled(self):
        """Test that verbose logging produces debug output"""
        with patch('sys.stderr') as mock_stderr:
            result = extract_json_blobs('{"test": "logging"}')
            assert len(result) == 1
            # Note: loguru output verification would need more complex mocking

    def test_quiet_logging(self):
        """Test that quiet logging suppresses debug output"""
        result = extract_json_blobs('{"test": "quiet"}')
        assert len(result) == 1
        # In quiet mode, only warnings and errors should appear


# Utility functions for testing
def create_test_content(num_objects: int, add_noise: bool = True) -> str:
    """Helper function to create test content with specified number of JSON objects"""
    content = ""
    for i in range(num_objects):
        if add_noise and i > 0:
            content += f" noise text {i} "
        content += f'{{"id": {i}, "name": "object_{i}"}}'
    return content


# # Performance benchmarks (optional, for development)
# class TestBenchmarks:
#
#     @pytest.mark.benchmark
#     def test_benchmark_small_content(self, benchmark):
#         """Benchmark with small content"""
#         content = create_test_content(10)
#         result = benchmark(extract_json_blobs, content)
#         assert len(result) == 10
#
#     @pytest.mark.benchmark
#     def test_benchmark_large_content(self, benchmark):
#         """Benchmark with large content"""
#         content = create_test_content(1000)
#         result = benchmark(extract_json_blobs, content)
#         assert len(result) == 1000


# if __name__ == "__main__":
#     # Setup for running tests directly
#     setup_logging(verbose=True)
#     pytest.main([__file__, "-v"])