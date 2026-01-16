"""
Transcript Cleaning Module

Cleans voice transcripts by removing filler words and formatting into paragraphs
while preserving the original wording and meaning.
"""

import logging
from typing import Optional

import anthropic

from config.settings import settings

logger = logging.getLogger(__name__)


class TranscriptCleaner:
    """Clean transcripts while preserving original wording."""

    SYSTEM_PROMPT = """You are a transcript cleaning assistant. Your ONLY job is to clean up voice transcripts.

STRICT RULES:
1. PRESERVE the speaker's exact words and phrasing - do NOT rephrase or rewrite
2. REMOVE filler words: um, uh, like, you know, so, basically, actually, literally, right, I mean, kind of, sort of, anyway, well (when used as filler)
3. REMOVE false starts and repeated words (e.g., "I I think" -> "I think")
4. FORMAT into logical paragraphs based on topic shifts or natural pauses
5. FIX obvious transcription errors (e.g., "gonna" can stay, but "gunna" -> "gonna")
6. DO NOT summarize, add commentary, or change the meaning
7. DO NOT add headers, bullet points, or any formatting beyond paragraphs
8. Return ONLY the cleaned text - no explanations or metadata

The output should read like a cleaned-up version of someone speaking - natural but without the verbal tics."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def clean(self, raw_transcript: str) -> str:
        """
        Clean a transcript by removing filler words and formatting into paragraphs.

        Args:
            raw_transcript: Raw transcript text (possibly with filler words, no formatting)

        Returns:
            Cleaned transcript with same wording but better formatting
        """
        if not raw_transcript or not raw_transcript.strip():
            return raw_transcript

        logger.info(f"Cleaning transcript ({len(raw_transcript)} chars)")

        user_prompt = f"""Clean the following transcript. Remove filler words and format into paragraphs, but keep the exact wording and meaning intact.

---
TRANSCRIPT:
{raw_transcript}
---

Return ONLY the cleaned transcript text, nothing else."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self.SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        cleaned = response.content[0].text.strip()

        # Log compression ratio
        original_len = len(raw_transcript)
        cleaned_len = len(cleaned)
        reduction = ((original_len - cleaned_len) / original_len) * 100 if original_len > 0 else 0

        logger.info(f"Cleaned transcript: {original_len} -> {cleaned_len} chars ({reduction:.1f}% reduction)")

        return cleaned

    def preview_clean(self, raw_transcript: str, max_preview: int = 500) -> dict:
        """
        Preview what cleaning would do without full processing.

        Returns dict with original preview, would-be-cleaned preview, and stats.
        """
        # For preview, just show a sample
        sample = raw_transcript[:max_preview] if len(raw_transcript) > max_preview else raw_transcript

        # Count potential filler words
        filler_words = [
            "um", "uh", "like", "you know", "so", "basically",
            "actually", "literally", "right", "i mean", "kind of", "sort of"
        ]

        text_lower = raw_transcript.lower()
        filler_count = sum(text_lower.count(f" {fw} ") + text_lower.count(f" {fw},") for fw in filler_words)

        return {
            "original_preview": sample + ("..." if len(raw_transcript) > max_preview else ""),
            "original_length": len(raw_transcript),
            "estimated_filler_words": filler_count,
            "has_paragraphs": "\n\n" in raw_transcript
        }


# Convenience function
def clean_transcript(raw_text: str) -> str:
    """Quick function to clean a transcript."""
    cleaner = TranscriptCleaner()
    return cleaner.clean(raw_text)
