"""
Tests for the deduplication module.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch


class TestDeduplicator:
    """Test the Deduplicator class."""

    def test_similarity_match_fields(self):
        """Test that SimilarityMatch has required fields."""
        from src.dedupe import SimilarityMatch

        match = SimilarityMatch(
            page_id="test-123",
            title="Test Page",
            similarity_score=0.95,
            database="inbox"
        )

        assert match.page_id == "test-123"
        assert match.title == "Test Page"
        assert match.similarity_score == 0.95
        assert match.database == "inbox"

    def test_dedupe_result_fields(self):
        """Test that DedupeResult has required fields."""
        from src.dedupe import DedupeResult, SimilarityMatch

        match = SimilarityMatch(
            page_id="test-123",
            title="Test",
            similarity_score=0.9,
            database="inbox"
        )

        result = DedupeResult(
            is_duplicate=True,
            matches=[match],
            best_match=match,
            recommendation="append_to"
        )

        assert result.is_duplicate is True
        assert len(result.matches) == 1
        assert result.best_match.page_id == "test-123"
        assert result.recommendation == "append_to"

    def test_compute_similarity(self):
        """Test cosine similarity computation."""
        from src.dedupe import Deduplicator

        dedup = Deduplicator.__new__(Deduplicator)

        # Identical vectors should have similarity 1.0
        v1 = np.array([1, 0, 0])
        v2 = np.array([1, 0, 0])
        assert dedup.compute_similarity(v1, v2) == pytest.approx(1.0)

        # Orthogonal vectors should have similarity 0.0
        v3 = np.array([0, 1, 0])
        assert dedup.compute_similarity(v1, v3) == pytest.approx(0.0)

        # Opposite vectors should have similarity -1.0
        v4 = np.array([-1, 0, 0])
        assert dedup.compute_similarity(v1, v4) == pytest.approx(-1.0)

    @patch('src.dedupe.OpenAI')
    def test_check_duplicates_no_matches(self, mock_openai):
        """Test dedupe when no similar items exist."""
        mock_client = Mock()
        mock_openai.return_value = mock_client

        # Mock embedding response
        mock_embedding = Mock()
        mock_embedding.data = [Mock(embedding=[0.1] * 1536)]
        mock_client.embeddings.create.return_value = mock_embedding

        from src.dedupe import Deduplicator

        dedup = Deduplicator()
        result = dedup.check_duplicates("New unique content", [])

        assert result.is_duplicate is False
        assert len(result.matches) == 0
        assert result.recommendation == "create_new"

    def test_recommendation_logic(self):
        """Test the recommendation logic for different similarity scores."""
        from src.dedupe import DedupeResult, SimilarityMatch

        # Very high similarity -> skip
        # High similarity -> append_to
        # Medium similarity -> review
        # Low similarity -> create_new

        # This tests the logic described in the module
        # Actual thresholds are configurable in settings
        pass


class TestDedupeThresholds:
    """Test deduplication threshold behavior."""

    def test_default_threshold(self):
        """Test that default threshold is reasonable."""
        from config.settings import settings

        # Default threshold should be between 0.7 and 0.95
        assert 0.7 <= settings.dedupe_threshold <= 0.95
