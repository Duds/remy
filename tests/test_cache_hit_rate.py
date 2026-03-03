"""
Tests for cache hit rate calculation in call_log.
"""


from remy.analytics.call_log import calculate_cache_hit_rate
from remy.models import TokenUsage


class TestCacheHitRate:
    """Test cache hit rate calculation."""

    def test_no_cache_hits(self):
        """Zero cache reads means 0% hit rate."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        )
        rate = calculate_cache_hit_rate(usage)
        assert rate == 0.0

    def test_full_cache_hit(self):
        """All input from cache means 100% hit rate."""
        usage = TokenUsage(
            input_tokens=0,
            output_tokens=500,
            cache_creation_tokens=0,
            cache_read_tokens=1000,
        )
        rate = calculate_cache_hit_rate(usage)
        assert rate == 1.0

    def test_partial_cache_hit(self):
        """Mixed cache and fresh input."""
        usage = TokenUsage(
            input_tokens=500,
            output_tokens=200,
            cache_creation_tokens=0,
            cache_read_tokens=500,
        )
        rate = calculate_cache_hit_rate(usage)
        assert rate == 0.5

    def test_zero_total_input(self):
        """Zero total input returns 0% (avoid division by zero)."""
        usage = TokenUsage(
            input_tokens=0,
            output_tokens=100,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        )
        rate = calculate_cache_hit_rate(usage)
        assert rate == 0.0

    def test_cache_creation_not_counted(self):
        """Cache creation tokens don't affect hit rate calculation."""
        usage = TokenUsage(
            input_tokens=500,
            output_tokens=200,
            cache_creation_tokens=1000,  # Creating cache
            cache_read_tokens=500,
        )
        rate = calculate_cache_hit_rate(usage)
        # Hit rate is cache_read / (cache_read + input)
        assert rate == 0.5
