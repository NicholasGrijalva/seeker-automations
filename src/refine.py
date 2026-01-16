"""
Content Refinement Module

Transforms raw transcripts into structured hypertext.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class HypertextFragment:
    """A structured piece of content with links."""

    fragment_type: str  # "core_claim", "supporting", "example", "source", "counter"
    content: str
    linked_concepts: list[str] = field(default_factory=list)
    source_reference: Optional[str] = None


@dataclass
class RefinedContent:
    """Fully refined content structure."""

    title: str
    core_aphorism: str  # The tweetable insight
    fragments: list[HypertextFragment]
    suggested_connections: list[str]
    structure_notes: str  # How pieces fit together


class Refiner:
    """Refine raw content into structured hypertext."""

    SYSTEM_PROMPT = """You are a content refinement assistant that transforms raw, stream-of-consciousness text into structured hypertext.

Your output philosophy:
- "Digital aphorisms linked to longer meditations"
- "A constellation, not a monolith"
- The reader chooses their path; you provide the nodes

Refinement Process:
1. Extract the CORE CLAIM - the single most important insight (tweetable)
2. Identify SUPPORTING FRAGMENTS - evidence, examples, elaborations
3. Find LINKABLE CONCEPTS - terms that should link to other ideas
4. Note SOURCE REFERENCES - citations, inspirations, related work
5. Consider COUNTER-ARGUMENTS - steelman opposing views

Output Format:
Create structured fragments that can be reassembled for any platform:
- Twitter thread = Core claim + key fragments
- Essay = All fragments in logical order with links
- Video script = Fragments as timestamped segments

Each fragment should be able to stand alone while linking to others."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def refine(self, raw_text: str, context: Optional[dict] = None) -> RefinedContent:
        """
        Refine raw text into structured hypertext.

        Args:
            raw_text: Raw transcript or idea
            context: Optional dict with 'title', 'category', 'tags' from classification

        Returns:
            RefinedContent with structured fragments
        """
        logger.info(f"Refining content ({len(raw_text)} chars)")

        context_str = ""
        if context:
            context_str = f"""
Context from classification:
- Title: {context.get('title', 'Unknown')}
- Category: {context.get('category', 'Unknown')}
- Tags: {', '.join(context.get('tags', []))}
"""

        user_prompt = f"""Refine the following raw content into structured hypertext.
{context_str}
---
RAW CONTENT:
{raw_text}
---

Return a JSON object with this structure:
{{
    "title": "Refined title",
    "core_aphorism": "The single tweetable insight (max 280 chars)",
    "fragments": [
        {{
            "fragment_type": "core_claim|supporting|example|source|counter",
            "content": "The fragment text",
            "linked_concepts": ["concept1", "concept2"],
            "source_reference": "optional source"
        }}
    ],
    "suggested_connections": ["Related idea 1", "Related idea 2"],
    "structure_notes": "How these pieces fit together"
}}

Guidelines:
- Core aphorism should be memorable and standalone
- Each fragment should be 1-3 sentences max
- Linked concepts are terms that should hyperlink to other ideas
- Include at least one counter-argument fragment if applicable"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=self.SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        # Parse response
        response_text = response.content[0].text

        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        try:
            data = json.loads(response_text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse refinement response: {e}")
            return RefinedContent(
                title=context.get("title", "Untitled") if context else "Untitled",
                core_aphorism=raw_text[:280],
                fragments=[HypertextFragment(
                    fragment_type="core_claim",
                    content=raw_text
                )],
                suggested_connections=[],
                structure_notes="Refinement failed - raw content preserved"
            )

        # Build fragments
        fragments = []
        for frag_data in data.get("fragments", []):
            fragments.append(HypertextFragment(
                fragment_type=frag_data.get("fragment_type", "supporting"),
                content=frag_data.get("content", ""),
                linked_concepts=frag_data.get("linked_concepts", []),
                source_reference=frag_data.get("source_reference")
            ))

        return RefinedContent(
            title=data.get("title", "Untitled"),
            core_aphorism=data.get("core_aphorism", ""),
            fragments=fragments,
            suggested_connections=data.get("suggested_connections", []),
            structure_notes=data.get("structure_notes", "")
        )

    def to_markdown(self, refined: RefinedContent) -> str:
        """Convert refined content to markdown format."""
        lines = [
            f"# {refined.title}",
            "",
            f"> {refined.core_aphorism}",
            "",
            "---",
            ""
        ]

        # Group fragments by type
        core_claims = [f for f in refined.fragments if f.fragment_type == "core_claim"]
        supporting = [f for f in refined.fragments if f.fragment_type == "supporting"]
        examples = [f for f in refined.fragments if f.fragment_type == "example"]
        sources = [f for f in refined.fragments if f.fragment_type == "source"]
        counters = [f for f in refined.fragments if f.fragment_type == "counter"]

        if core_claims:
            lines.append("## Core Claims")
            for frag in core_claims:
                lines.append(f"- {frag.content}")
                if frag.linked_concepts:
                    lines.append(f"  - *Links: {', '.join(frag.linked_concepts)}*")
            lines.append("")

        if supporting:
            lines.append("## Supporting Points")
            for frag in supporting:
                lines.append(f"- {frag.content}")
            lines.append("")

        if examples:
            lines.append("## Examples")
            for frag in examples:
                lines.append(f"- {frag.content}")
            lines.append("")

        if counters:
            lines.append("## Counter-Arguments")
            for frag in counters:
                lines.append(f"- {frag.content}")
            lines.append("")

        if sources:
            lines.append("## Sources")
            for frag in sources:
                ref = f" ({frag.source_reference})" if frag.source_reference else ""
                lines.append(f"- {frag.content}{ref}")
            lines.append("")

        if refined.suggested_connections:
            lines.append("## Related Ideas")
            for conn in refined.suggested_connections:
                lines.append(f"- [[{conn}]]")
            lines.append("")

        if refined.structure_notes:
            lines.append("---")
            lines.append(f"*Structure: {refined.structure_notes}*")

        return "\n".join(lines)


# Convenience function
def refine_content(raw_text: str) -> RefinedContent:
    """Quick refinement function."""
    refiner = Refiner()
    return refiner.refine(raw_text)
