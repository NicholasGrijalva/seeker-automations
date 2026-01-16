"""
Pipeline Orchestrator

Coordinates all stages of the content processing pipeline.
"""

import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from .transcribe import Transcriber
from .classify import Classifier, ClassificationResult
from .dedupe import Deduplicator, DedupeResult
from .notion_client import NotionClient
from .refine import Refiner, RefinedContent
from .templates import TemplateEngine, PlatformOutput
from config.notion_schema import InboxItem, ContentObject

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of running the full pipeline."""

    success: bool
    stage_reached: str  # transcribe, classify, dedupe, notion, refine, template
    error: Optional[str] = None

    # Outputs from each stage
    transcript: Optional[str] = None
    classification: Optional[ClassificationResult] = None
    dedupe_result: Optional[DedupeResult] = None
    notion_page_id: Optional[str] = None
    refined_content: Optional[RefinedContent] = None
    platform_outputs: dict[str, PlatformOutput] = field(default_factory=dict)

    # Metadata
    input_type: str = "text"  # "text", "audio", "file"
    processing_time_ms: int = 0


class Pipeline:
    """
    Main pipeline orchestrator.

    Stages:
    1. Transcribe (if audio)
    2. Classify (determine type, priority, category, tags)
    3. Dedupe (check for similar existing content)
    4. Notion (create in Inbox or append to existing)
    5. Refine (optional - transform to structured hypertext)
    6. Template (optional - format for specific platforms)
    """

    def __init__(self):
        self.transcriber = Transcriber()
        self.classifier = Classifier()
        self.deduplicator = Deduplicator()
        self.notion = NotionClient()
        self.refiner = Refiner()
        self.template_engine = TemplateEngine()

    def process_audio(
        self,
        audio_path: str | Path,
        auto_refine: bool = False,
        platforms: Optional[list[str]] = None
    ) -> PipelineResult:
        """
        Process an audio file through the full pipeline.

        Args:
            audio_path: Path to audio file
            auto_refine: Whether to automatically refine content
            platforms: List of platforms to generate outputs for

        Returns:
            PipelineResult with all outputs
        """
        start_time = datetime.now()
        result = PipelineResult(success=False, stage_reached="init", input_type="audio")

        try:
            # Stage 1: Transcribe
            logger.info("Stage 1: Transcribing audio")
            transcription = self.transcriber.transcribe(audio_path)
            result.transcript = transcription["text"]
            result.stage_reached = "transcribe"

            # Continue with text processing
            return self._process_text_internal(
                text=result.transcript,
                result=result,
                source_context=f"voice memo: {Path(audio_path).name}",
                auto_refine=auto_refine,
                platforms=platforms,
                start_time=start_time
            )

        except Exception as e:
            logger.error(f"Pipeline failed at {result.stage_reached}: {e}")
            result.error = str(e)
            result.processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return result

    def process_text(
        self,
        text: str,
        source_context: Optional[str] = None,
        auto_refine: bool = False,
        platforms: Optional[list[str]] = None
    ) -> PipelineResult:
        """
        Process raw text through the pipeline.

        Args:
            text: Raw text input
            source_context: Optional context about the source
            auto_refine: Whether to automatically refine content
            platforms: List of platforms to generate outputs for

        Returns:
            PipelineResult with all outputs
        """
        start_time = datetime.now()
        result = PipelineResult(success=False, stage_reached="init", input_type="text")
        result.transcript = text

        return self._process_text_internal(
            text=text,
            result=result,
            source_context=source_context,
            auto_refine=auto_refine,
            platforms=platforms,
            start_time=start_time
        )

    def _process_text_internal(
        self,
        text: str,
        result: PipelineResult,
        source_context: Optional[str],
        auto_refine: bool,
        platforms: Optional[list[str]],
        start_time: datetime
    ) -> PipelineResult:
        """Internal text processing logic."""

        try:
            # Stage 2: Classify
            logger.info("Stage 2: Classifying content")
            result.classification = self.classifier.classify(text, source_context)
            result.stage_reached = "classify"

            # Stage 3: Dedupe
            logger.info("Stage 3: Checking for duplicates")
            # Get existing items for comparison
            inbox_items = self.notion.query_inbox(limit=50)
            content_items = self.notion.query_content_objects(limit=50)

            existing = []
            for item in inbox_items:
                existing.append({
                    "page_id": item["id"],
                    "title": item["title"],
                    "text": item["title"],
                    "database": "inbox"
                })
            for item in content_items:
                existing.append({
                    "page_id": item["id"],
                    "title": item["name"],
                    "text": item["name"] + " " + (item.get("main_idea") or ""),
                    "database": "content_objects"
                })

            result.dedupe_result = self.deduplicator.check_duplicates(text, existing)
            result.stage_reached = "dedupe"

            # Stage 4: Create in Notion
            logger.info(f"Stage 4: Notion action - {result.dedupe_result.recommendation}")

            if result.dedupe_result.recommendation == "skip":
                logger.info("Skipping - nearly identical content exists")
                result.notion_page_id = result.dedupe_result.best_match.page_id

            elif result.dedupe_result.recommendation == "append_to":
                # Append to existing page
                page_id = result.dedupe_result.best_match.page_id
                self.notion.append_to_page(
                    page_id=page_id,
                    text=text,
                    heading=f"Additional notes ({datetime.now().strftime('%Y-%m-%d')})"
                )
                result.notion_page_id = page_id

            else:
                # Create new inbox item
                inbox_item = InboxItem(
                    title=result.classification.title,
                    status="New",
                    tags=result.classification.tags,
                    type=result.classification.content_type,
                    raw_transcript=text
                )
                response = self.notion.create_inbox_item(inbox_item)
                result.notion_page_id = response["id"]

            result.stage_reached = "notion"

            # Stage 5: Refine (optional)
            if auto_refine:
                logger.info("Stage 5: Refining content")
                result.refined_content = self.refiner.refine(
                    text,
                    context={
                        "title": result.classification.title,
                        "category": result.classification.category,
                        "tags": result.classification.tags
                    }
                )
                result.stage_reached = "refine"

                # Stage 6: Template (optional)
                if platforms:
                    logger.info(f"Stage 6: Generating templates for {platforms}")
                    for platform in platforms:
                        try:
                            output = self.template_engine.format_all(result.refined_content).get(platform)
                            if output:
                                result.platform_outputs[platform] = output
                        except Exception as e:
                            logger.warning(f"Failed to generate {platform} template: {e}")
                    result.stage_reached = "template"

            result.success = True

        except Exception as e:
            logger.error(f"Pipeline failed at {result.stage_reached}: {e}")
            result.error = str(e)

        result.processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        return result

    def refine_existing(self, page_id: str, platforms: Optional[list[str]] = None) -> PipelineResult:
        """
        Refine an existing Notion page.

        Args:
            page_id: Notion page ID to refine
            platforms: Platforms to generate outputs for

        Returns:
            PipelineResult with refined content
        """
        start_time = datetime.now()
        result = PipelineResult(success=False, stage_reached="init", input_type="notion_page")

        try:
            # Get page content
            content = self.notion.get_page_content(page_id)
            result.transcript = content
            result.notion_page_id = page_id

            # Refine
            result.refined_content = self.refiner.refine(content)
            result.stage_reached = "refine"

            # Generate templates
            if platforms:
                for platform in platforms:
                    try:
                        output = self.template_engine.format_all(result.refined_content).get(platform)
                        if output:
                            result.platform_outputs[platform] = output
                    except Exception as e:
                        logger.warning(f"Failed to generate {platform} template: {e}")
                result.stage_reached = "template"

            result.success = True

        except Exception as e:
            logger.error(f"Refine failed: {e}")
            result.error = str(e)

        result.processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        return result


# Convenience functions
def process_voice_memo(audio_path: str | Path) -> PipelineResult:
    """Quick function to process a voice memo."""
    pipeline = Pipeline()
    return pipeline.process_audio(audio_path)


def process_idea(text: str) -> PipelineResult:
    """Quick function to process a text idea."""
    pipeline = Pipeline()
    return pipeline.process_text(text)
