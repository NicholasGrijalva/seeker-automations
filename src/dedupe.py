"""
Deduplication Module

Detects similar existing content using embeddings and semantic similarity.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from openai import OpenAI
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class SimilarityMatch:
    """A similar item found in the database."""

    page_id: str
    title: str
    similarity_score: float
    database: str  # "inbox" or "content_objects"


@dataclass
class DedupeResult:
    """Result of deduplication check."""

    is_duplicate: bool
    matches: list[SimilarityMatch]
    best_match: Optional[SimilarityMatch]
    recommendation: str  # "create_new", "append_to", "merge_with"


class Deduplicator:
    """Check for duplicate/similar content using embeddings."""

    def __init__(self, notion_client=None):
        self.openai = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.embedding_model
        self.threshold = settings.dedupe_threshold
        self.notion_client = notion_client

        # Cache for embeddings (page_id -> embedding)
        self._embedding_cache: dict[str, np.ndarray] = {}

    def get_embedding(self, text: str) -> np.ndarray:
        """Get embedding vector for text."""
        # Truncate to avoid token limits
        text = text[:8000]

        response = self.openai.embeddings.create(
            model=self.model,
            input=text
        )

        return np.array(response.data[0].embedding)

    def compute_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings."""
        return float(cosine_similarity(
            embedding1.reshape(1, -1),
            embedding2.reshape(1, -1)
        )[0][0])

    def check_duplicates(
        self,
        new_text: str,
        existing_items: list[dict],
        threshold: Optional[float] = None
    ) -> DedupeResult:
        """
        Check if new text is similar to existing items.

        Args:
            new_text: The new content to check
            existing_items: List of dicts with 'page_id', 'title', 'text', 'database'
            threshold: Override default similarity threshold

        Returns:
            DedupeResult with matches and recommendation
        """
        threshold = threshold or self.threshold
        logger.info(f"Checking for duplicates (threshold={threshold})")

        # Get embedding for new text
        new_embedding = self.get_embedding(new_text)

        matches = []

        for item in existing_items:
            # Get or compute embedding for existing item
            page_id = item["page_id"]

            if page_id in self._embedding_cache:
                existing_embedding = self._embedding_cache[page_id]
            else:
                existing_embedding = self.get_embedding(item.get("text", item.get("title", "")))
                self._embedding_cache[page_id] = existing_embedding

            # Compute similarity
            similarity = self.compute_similarity(new_embedding, existing_embedding)

            if similarity >= threshold * 0.8:  # Include near-matches for review
                matches.append(SimilarityMatch(
                    page_id=page_id,
                    title=item.get("title", "Untitled"),
                    similarity_score=similarity,
                    database=item.get("database", "unknown")
                ))

        # Sort by similarity
        matches.sort(key=lambda m: m.similarity_score, reverse=True)

        # Determine recommendation
        best_match = matches[0] if matches else None
        is_duplicate = best_match and best_match.similarity_score >= threshold

        if not best_match:
            recommendation = "create_new"
        elif best_match.similarity_score >= 0.95:
            recommendation = "skip"  # Almost identical
        elif best_match.similarity_score >= threshold:
            recommendation = "append_to"  # Similar enough to merge
        elif best_match.similarity_score >= threshold * 0.8:
            recommendation = "review"  # Human should decide
        else:
            recommendation = "create_new"

        logger.info(f"Dedupe result: {recommendation} (best_score={best_match.similarity_score if best_match else 0:.3f})")

        return DedupeResult(
            is_duplicate=is_duplicate,
            matches=matches[:5],  # Top 5 matches
            best_match=best_match,
            recommendation=recommendation
        )

    async def check_against_notion(self, new_text: str) -> DedupeResult:
        """
        Check new text against all items in Notion databases.

        Requires notion_client to be set.
        """
        if not self.notion_client:
            raise ValueError("NotionClient required for check_against_notion")

        # Fetch recent items from both databases
        inbox_items = await self.notion_client.query_inbox(limit=100)
        content_items = await self.notion_client.query_content_objects(limit=100)

        # Prepare items for comparison
        existing_items = []

        for item in inbox_items:
            existing_items.append({
                "page_id": item["id"],
                "title": item.get("title", ""),
                "text": item.get("title", "") + " " + item.get("content", ""),
                "database": "inbox"
            })

        for item in content_items:
            existing_items.append({
                "page_id": item["id"],
                "title": item.get("name", ""),
                "text": item.get("name", "") + " " + item.get("main_idea", ""),
                "database": "content_objects"
            })

        return self.check_duplicates(new_text, existing_items)

    def clear_cache(self):
        """Clear the embedding cache."""
        self._embedding_cache.clear()


# Convenience function
def check_duplicate(new_text: str, existing_items: list[dict]) -> DedupeResult:
    """Quick deduplication check."""
    deduplicator = Deduplicator()
    return deduplicator.check_duplicates(new_text, existing_items)
