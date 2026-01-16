"""
Platform Template Engine

Formats refined content for specific platforms.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .refine import RefinedContent, HypertextFragment

logger = logging.getLogger(__name__)


@dataclass
class PlatformOutput:
    """Formatted output for a specific platform."""

    platform: str
    content: str
    metadata: dict  # Platform-specific metadata (char count, thread count, etc.)


class TemplateEngine:
    """Format content for different platforms."""

    # Platform character limits
    LIMITS = {
        "twitter": 280,
        "twitter_thread": 280,
        "linkedin": 3000,
        "substack": None,  # No limit
        "video_script": None
    }

    def __init__(self):
        pass

    def format_twitter_thread(self, refined: RefinedContent) -> PlatformOutput:
        """Format as a Twitter thread."""
        tweets = []

        # Tweet 1: Hook with core aphorism
        hook = refined.core_aphorism
        if len(hook) > 275:
            hook = hook[:272] + "..."
        tweets.append(f"{hook}\n\n🧵")

        # Subsequent tweets from fragments
        core_claims = [f for f in refined.fragments if f.fragment_type == "core_claim"]
        supporting = [f for f in refined.fragments if f.fragment_type == "supporting"]
        examples = [f for f in refined.fragments if f.fragment_type == "example"]

        for frag in core_claims + supporting:
            tweet = frag.content
            if len(tweet) > 280:
                # Split into multiple tweets
                words = tweet.split()
                current = ""
                for word in words:
                    if len(current) + len(word) + 1 <= 275:
                        current += (" " if current else "") + word
                    else:
                        tweets.append(current + "...")
                        current = "..." + word
                if current:
                    tweets.append(current)
            else:
                tweets.append(tweet)

        # Add examples
        for frag in examples[:2]:  # Max 2 examples
            tweet = f"Example:\n{frag.content}"
            if len(tweet) <= 280:
                tweets.append(tweet)

        # Final tweet: CTA
        tweets.append(f"That's the thread.\n\nIf this resonated, follow for more on {refined.suggested_connections[0] if refined.suggested_connections else 'ideas like this'}.")

        # Number the tweets
        numbered = [f"{i+1}/{len(tweets)}\n\n{t}" if i > 0 else t for i, t in enumerate(tweets)]

        return PlatformOutput(
            platform="twitter_thread",
            content="\n\n---\n\n".join(numbered),
            metadata={
                "tweet_count": len(tweets),
                "total_chars": sum(len(t) for t in tweets)
            }
        )

    def format_linkedin(self, refined: RefinedContent) -> PlatformOutput:
        """Format as a LinkedIn post."""
        lines = []

        # Hook line
        lines.append(refined.core_aphorism)
        lines.append("")

        # Body - select key fragments
        core_claims = [f for f in refined.fragments if f.fragment_type == "core_claim"]
        supporting = [f for f in refined.fragments if f.fragment_type == "supporting"]

        for frag in core_claims[:2]:
            lines.append(frag.content)
            lines.append("")

        for frag in supporting[:3]:
            lines.append(f"→ {frag.content}")

        lines.append("")

        # Takeaway
        if refined.structure_notes:
            lines.append(f"The key insight: {refined.structure_notes}")
            lines.append("")

        # CTA
        lines.append("---")
        lines.append("")
        lines.append("What's your take? Let me know in the comments.")
        lines.append("")

        # Hashtags from linked concepts
        all_concepts = set()
        for frag in refined.fragments:
            all_concepts.update(frag.linked_concepts)

        hashtags = [f"#{c.replace(' ', '')}" for c in list(all_concepts)[:5]]
        if hashtags:
            lines.append(" ".join(hashtags))

        content = "\n".join(lines)

        return PlatformOutput(
            platform="linkedin",
            content=content,
            metadata={
                "char_count": len(content),
                "hashtag_count": len(hashtags)
            }
        )

    def format_substack(self, refined: RefinedContent) -> PlatformOutput:
        """Format as a Substack essay."""
        from .refine import Refiner
        refiner = Refiner()
        markdown = refiner.to_markdown(refined)

        # Add newsletter-specific elements
        lines = [
            f"# {refined.title}",
            "",
            f"*{refined.core_aphorism}*",
            "",
            "---",
            "",
        ]

        # Introduction
        lines.append("## The Insight")
        lines.append("")
        core_claims = [f for f in refined.fragments if f.fragment_type == "core_claim"]
        for frag in core_claims:
            lines.append(frag.content)
            lines.append("")

        # Main body
        lines.append("## Going Deeper")
        lines.append("")
        supporting = [f for f in refined.fragments if f.fragment_type == "supporting"]
        examples = [f for f in refined.fragments if f.fragment_type == "example"]

        for frag in supporting:
            lines.append(frag.content)
            lines.append("")

        if examples:
            lines.append("### Examples")
            lines.append("")
            for frag in examples:
                lines.append(f"- {frag.content}")
            lines.append("")

        # Counter-arguments
        counters = [f for f in refined.fragments if f.fragment_type == "counter"]
        if counters:
            lines.append("## The Other Side")
            lines.append("")
            for frag in counters:
                lines.append(frag.content)
                lines.append("")

        # Conclusion
        lines.append("## The Takeaway")
        lines.append("")
        lines.append(refined.core_aphorism)
        lines.append("")

        if refined.suggested_connections:
            lines.append("---")
            lines.append("")
            lines.append("*Related ideas to explore:*")
            for conn in refined.suggested_connections:
                lines.append(f"- {conn}")

        content = "\n".join(lines)

        return PlatformOutput(
            platform="substack",
            content=content,
            metadata={
                "word_count": len(content.split()),
                "section_count": content.count("## ")
            }
        )

    def format_video_script(self, refined: RefinedContent) -> PlatformOutput:
        """Format as a timestamped video script."""
        segments = []
        current_time = 0

        # Segment 1: Hook (0:00 - 0:15)
        segments.append({
            "start": "0:00",
            "end": "0:15",
            "type": "HOOK",
            "script": refined.core_aphorism,
            "notes": "[Quick cut, direct to camera, bold statement]"
        })
        current_time = 15

        # Segment 2: Problem/Setup (0:15 - 1:00)
        core_claims = [f for f in refined.fragments if f.fragment_type == "core_claim"]
        if core_claims:
            script = " ".join([f.content for f in core_claims[:2]])
            segments.append({
                "start": f"{current_time//60}:{current_time%60:02d}",
                "end": f"{(current_time+45)//60}:{(current_time+45)%60:02d}",
                "type": "PROBLEM",
                "script": script,
                "notes": "[Establish the problem or misconception]"
            })
            current_time += 45

        # Segment 3: Main Content (1:00 - 2:30)
        supporting = [f for f in refined.fragments if f.fragment_type == "supporting"]
        for i, frag in enumerate(supporting[:3]):
            duration = 30
            segments.append({
                "start": f"{current_time//60}:{current_time%60:02d}",
                "end": f"{(current_time+duration)//60}:{(current_time+duration)%60:02d}",
                "type": f"POINT {i+1}",
                "script": frag.content,
                "notes": f"[B-roll suggestion: {frag.linked_concepts[0] if frag.linked_concepts else 'relevant imagery'}]"
            })
            current_time += duration

        # Segment 4: Examples (if any)
        examples = [f for f in refined.fragments if f.fragment_type == "example"]
        if examples:
            script = examples[0].content
            segments.append({
                "start": f"{current_time//60}:{current_time%60:02d}",
                "end": f"{(current_time+30)//60}:{(current_time+30)%60:02d}",
                "type": "EXAMPLE",
                "script": script,
                "notes": "[Show example visually if possible]"
            })
            current_time += 30

        # Segment 5: CTA
        segments.append({
            "start": f"{current_time//60}:{current_time%60:02d}",
            "end": f"{(current_time+15)//60}:{(current_time+15)%60:02d}",
            "type": "CTA",
            "script": f"If this changed how you think about {refined.suggested_connections[0] if refined.suggested_connections else 'this topic'}, subscribe for more.",
            "notes": "[End screen, subscribe button]"
        })

        # Format output
        lines = [
            f"# VIDEO SCRIPT: {refined.title}",
            f"Estimated duration: {(current_time+15)//60}:{(current_time+15)%60:02d}",
            "",
            "---",
            ""
        ]

        for seg in segments:
            lines.extend([
                f"## {seg['type']} ({seg['start']} - {seg['end']})",
                "",
                seg['script'],
                "",
                f"*{seg['notes']}*",
                "",
                "---",
                ""
            ])

        content = "\n".join(lines)

        return PlatformOutput(
            platform="video_script",
            content=content,
            metadata={
                "duration_seconds": current_time + 15,
                "segment_count": len(segments)
            }
        )

    def format_all(self, refined: RefinedContent) -> dict[str, PlatformOutput]:
        """Generate outputs for all platforms."""
        return {
            "twitter_thread": self.format_twitter_thread(refined),
            "linkedin": self.format_linkedin(refined),
            "substack": self.format_substack(refined),
            "video_script": self.format_video_script(refined)
        }


# Convenience function
def format_for_platform(refined: RefinedContent, platform: str) -> PlatformOutput:
    """Format content for a specific platform."""
    engine = TemplateEngine()

    formatters = {
        "twitter": engine.format_twitter_thread,
        "twitter_thread": engine.format_twitter_thread,
        "linkedin": engine.format_linkedin,
        "substack": engine.format_substack,
        "video": engine.format_video_script,
        "video_script": engine.format_video_script
    }

    formatter = formatters.get(platform.lower())
    if not formatter:
        raise ValueError(f"Unknown platform: {platform}")

    return formatter(refined)
