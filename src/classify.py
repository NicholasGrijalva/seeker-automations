"""
Content Classification Module

Uses Claude to classify raw input into structured metadata.
"""

import json
import logging
from typing import Optional
from dataclasses import dataclass

import anthropic

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of content classification."""

    title: str
    content_type: str  # Essay, Video, Post, Proself
    priority: str  # Active, Essential, Backlog
    category: str  # AI/Technology, Philosophy, etc.
    tags: list[str]
    main_idea: str  # 1-2 sentence summary
    atomic_ideas: list[str]  # Key standalone claims/insights

    # Optional enrichment
    suggested_platforms: list[str] = None
    related_concepts: list[str] = None


class Classifier:
    """Classify content using Claude."""

    SYSTEM_PROMPT = """You are a content classification assistant for a personal knowledge management system.

Your task is to analyze raw text (often transcribed voice memos) and extract structured metadata.

The user is a creator focused on:
- AI/Technology and its societal implications
- Philosophy, spirituality, and personal development
- Leadership, business, and content strategy
- Deep thinking about human nature and relationships

Classification Guidelines:

CONTENT TYPE:
- Essay: Long-form written content, deep dives, articles
- Video: Content intended for video format, visual explanations
- Post: Short-form social content (Twitter, LinkedIn)
- Proself: Personal development notes, self-reflection, journaling

PRIORITY:
- Active: Should be worked on immediately, timely or urgent
- Essential: Important ideas that should be developed soon
- Backlog: Good ideas to revisit later, not time-sensitive

CATEGORY (choose the best fit):
- AI/Technology
- Philosophy/Spirituality
- Leadership/Business
- Personal Development
- Content Strategy
- Relationships
- Health/Fitness
- Other

TAGS: Extract 2-5 specific topic tags from the content.

MAIN IDEA: A 1-2 sentence summary of the core insight or purpose.

ATOMIC IDEAS: Extract 1-3 standalone claims or insights that could each be their own post.

TITLE: Create a compelling, descriptive title (not clickbait, but clear and engaging).

Always respond with valid JSON matching the specified schema."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def classify(self, text: str, source_context: Optional[str] = None) -> ClassificationResult:
        """
        Classify raw text into structured content metadata.

        Args:
            text: Raw text to classify (transcript or typed input)
            source_context: Optional context (e.g., "voice memo", "meeting notes")

        Returns:
            ClassificationResult with all metadata fields
        """
        logger.info(f"Classifying text ({len(text)} chars)")

        user_prompt = f"""Classify the following content and return a JSON object.

Source: {source_context or "raw input"}

---
CONTENT:
{text}
---

Return a JSON object with these exact fields:
{{
    "title": "Compelling descriptive title",
    "content_type": "Essay|Video|Post|Proself",
    "priority": "Active|Essential|Backlog",
    "category": "Category name",
    "tags": ["tag1", "tag2", ...],
    "main_idea": "1-2 sentence summary",
    "atomic_ideas": ["Standalone insight 1", "Standalone insight 2", ...],
    "suggested_platforms": ["Twitter", "LinkedIn", ...],
    "related_concepts": ["concept1", "concept2", ...]
}}"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        # Parse JSON response
        response_text = response.content[0].text

        # Handle potential markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        try:
            data = json.loads(response_text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse classification response: {e}")
            logger.error(f"Response was: {response_text}")
            # Return a default classification
            return ClassificationResult(
                title=text[:100] + "..." if len(text) > 100 else text,
                content_type="Essay",
                priority="Backlog",
                category="Other",
                tags=[],
                main_idea=text[:200] if len(text) > 200 else text,
                atomic_ideas=[]
            )

        return ClassificationResult(
            title=data.get("title", "Untitled"),
            content_type=data.get("content_type", "Essay"),
            priority=data.get("priority", "Backlog"),
            category=data.get("category", "Other"),
            tags=data.get("tags", []),
            main_idea=data.get("main_idea", ""),
            atomic_ideas=data.get("atomic_ideas", []),
            suggested_platforms=data.get("suggested_platforms"),
            related_concepts=data.get("related_concepts")
        )

    def classify_batch(self, texts: list[str]) -> list[ClassificationResult]:
        """Classify multiple texts (runs sequentially for now)."""
        return [self.classify(text) for text in texts]


# Convenience function
def classify_content(text: str) -> ClassificationResult:
    """Quick classification function."""
    classifier = Classifier()
    return classifier.classify(text)
