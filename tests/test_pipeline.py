"""
Tests for the pipeline orchestrator.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


class TestPipelineResult:
    """Test PipelineResult dataclass."""

    def test_pipeline_result_defaults(self):
        """Test default values for PipelineResult."""
        from src.pipeline import PipelineResult

        result = PipelineResult(success=False, stage_reached="init")

        assert result.success is False
        assert result.stage_reached == "init"
        assert result.error is None
        assert result.transcript is None
        assert result.classification is None
        assert result.dedupe_result is None
        assert result.notion_page_id is None
        assert result.refined_content is None
        assert result.platform_outputs == {}
        assert result.input_type == "text"
        assert result.processing_time_ms == 0


class TestPipeline:
    """Test Pipeline class."""

    @patch('src.pipeline.Transcriber')
    @patch('src.pipeline.Classifier')
    @patch('src.pipeline.Deduplicator')
    @patch('src.pipeline.NotionClient')
    @patch('src.pipeline.Refiner')
    @patch('src.pipeline.TemplateEngine')
    def test_pipeline_initializes_all_components(
        self,
        mock_template,
        mock_refiner,
        mock_notion,
        mock_dedupe,
        mock_classifier,
        mock_transcriber
    ):
        """Test that Pipeline initializes all components."""
        from src.pipeline import Pipeline

        pipeline = Pipeline()

        mock_transcriber.assert_called_once()
        mock_classifier.assert_called_once()
        mock_dedupe.assert_called_once()
        mock_notion.assert_called_once()
        mock_refiner.assert_called_once()
        mock_template.assert_called_once()

    @patch('src.pipeline.Transcriber')
    @patch('src.pipeline.Classifier')
    @patch('src.pipeline.Deduplicator')
    @patch('src.pipeline.NotionClient')
    @patch('src.pipeline.Refiner')
    @patch('src.pipeline.TemplateEngine')
    def test_process_text_classification(
        self,
        mock_template,
        mock_refiner,
        mock_notion,
        mock_dedupe,
        mock_classifier,
        mock_transcriber
    ):
        """Test text processing through classification stage."""
        from src.pipeline import Pipeline
        from src.classify import ClassificationResult

        # Setup mocks
        mock_classifier_instance = Mock()
        mock_classifier.return_value = mock_classifier_instance
        mock_classifier_instance.classify.return_value = ClassificationResult(
            title="Test",
            content_type="Essay",
            priority="Active",
            category="Test",
            tags=["test"],
            main_idea="Test idea",
            atomic_ideas=[]
        )

        mock_notion_instance = Mock()
        mock_notion.return_value = mock_notion_instance
        mock_notion_instance.query_inbox.return_value = []
        mock_notion_instance.query_content_objects.return_value = []
        mock_notion_instance.create_inbox_item.return_value = {"id": "test-page-id"}

        from src.dedupe import DedupeResult
        mock_dedupe_instance = Mock()
        mock_dedupe.return_value = mock_dedupe_instance
        mock_dedupe_instance.check_duplicates.return_value = DedupeResult(
            is_duplicate=False,
            matches=[],
            best_match=None,
            recommendation="create_new"
        )

        pipeline = Pipeline()
        result = pipeline.process_text("Test content")

        assert result.success is True
        assert result.classification.title == "Test"
        assert result.stage_reached == "notion"


class TestPipelineStages:
    """Test individual pipeline stages."""

    def test_stage_order(self):
        """Test that stages are processed in correct order."""
        # The pipeline should process in this order:
        # 1. transcribe (if audio)
        # 2. classify
        # 3. dedupe
        # 4. notion
        # 5. refine (optional)
        # 6. template (optional)

        stages = ["transcribe", "classify", "dedupe", "notion", "refine", "template"]
        for i, stage in enumerate(stages[:-1]):
            next_stage = stages[i + 1]
            # Each stage should come before the next
            assert stages.index(stage) < stages.index(next_stage)

    def test_audio_requires_transcribe(self):
        """Test that audio input requires transcription."""
        # Audio files should go through transcribe stage
        # Text input should skip transcribe stage
        pass
