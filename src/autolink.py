"""
Auto-Wikilink Insertion Module

Given a newly written Obsidian note path, suggests and inserts [[wikilinks]]
to semantically related notes in the vault.

Uses graph traversal to find candidates, then Claude for final selection.
Uses Obsidian Local REST API for note read/write.

Flow:
  1. Load vault index (titles + networkx graph) via obsidiantools
  2. Read the new note content via Obsidian Local REST API
  3. Find candidates via title scan + tag overlap + graph walk (~20 notes)
  4. Call Claude with (note content + candidates) -> get wikilink suggestions
  5. Insert [[wikilinks]] into note content where terms appear
  6. Write updated content back via REST API
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import anthropic
import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class VaultIndex:
    """Index of all note titles in the vault, with graph."""

    titles: list[str]
    title_to_path: dict[str, str]
    existing_links: dict[str, list[str]]
    graph: object = None  # nx.MultiDiGraph
    tags_index: dict = field(default_factory=dict)  # {stem: [tags]}


@dataclass
class WikilinkSuggestion:
    """A suggested wikilink to insert."""

    target_title: str
    anchor_phrase: str
    confidence: str  # "high" | "medium" | "low"
    reason: str


@dataclass
class AutolinkResult:
    """Result of running autolink on a note."""

    success: bool
    note_path: str
    links_added: int
    suggestions: list[WikilinkSuggestion] = field(default_factory=list)
    error: Optional[str] = None


class AutoLinker:
    """Suggests and inserts [[wikilinks]] into Obsidian notes."""

    SYSTEM_PROMPT = """You are a knowledge graph assistant for a personal Obsidian vault.
Given the content of a new note and a list of existing note titles,
identify which existing notes should be wikilinked in the new note.

Rules:
- Only suggest links where the concept is genuinely referenced in the note
- Suggest the exact phrase in the note text that should become the wikilink
- anchor_phrase must appear VERBATIM (case-insensitive) in the note content
- Prefer atomic/concept notes over project or capture notes as link targets
- Max {max_suggestions} suggestions, only HIGH or MEDIUM confidence
- Do NOT suggest links to the note itself
- Do NOT suggest links if the phrase is already [[linked]]
- Return valid JSON only, no markdown fences"""

    def __init__(self):
        self.vault_path = settings.obsidian_vault_path
        self.api_base = f"https://127.0.0.1:{settings.obsidian_rest_api_port}"
        self.api_key = settings.obsidian_rest_api_key
        self.max_suggestions = settings.autolink_max_suggestions
        self.min_confidence = settings.autolink_min_confidence
        self.skip_folders = settings.autolink_skip_folders

        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def build_vault_index(self) -> VaultIndex:
        """Build index of all note titles + graph from vault."""
        import obsidiantools.api as otools

        vault = otools.Vault(self.vault_path).connect().gather()

        titles = []
        title_to_path = {}
        existing_links = {}

        for stem, path in vault.md_file_index.items():
            rel_path = str(path)
            if any(rel_path.startswith(skip) for skip in self.skip_folders):
                continue
            titles.append(stem)
            title_to_path[stem] = rel_path
            links = vault.get_wikilinks(stem) or []
            existing_links[stem] = links

        return VaultIndex(
            titles=titles,
            title_to_path=title_to_path,
            existing_links=existing_links,
            graph=vault.graph,
            tags_index=dict(vault.tags_index) if vault.tags_index else {},
        )

    def find_candidates(
        self,
        note_content: str,
        note_stem: str,
        index: VaultIndex,
        max_candidates: int = 20,
    ) -> list[str]:
        """Find candidate link targets via title scan + tag overlap + graph walk."""
        scores: dict[str, float] = {}
        title_set = set(index.titles)
        content_lower = note_content.lower()

        # Step 1: Title scan -- titles that appear verbatim in content
        for title in index.titles:
            if title == note_stem:
                continue
            if len(title) < 3:
                continue  # skip tiny titles (noise)
            if title.lower() in content_lower:
                scores[title] = scores.get(title, 0) + 3

        # Step 2: Tag overlap -- notes sharing tags with this note
        note_tags = set(index.tags_index.get(note_stem, []))
        if note_tags:
            for other, other_tags in index.tags_index.items():
                if other == note_stem or other not in title_set:
                    continue
                overlap = note_tags & set(other_tags)
                if overlap:
                    scores[other] = scores.get(other, 0) + len(overlap)

        # Step 3: Graph walk -- neighbors of already-linked notes (1 hop)
        g = index.graph
        if g is not None:
            existing = set(index.existing_links.get(note_stem, []))
            for linked in existing:
                if not g.has_node(linked):
                    continue
                for neighbor in list(g.successors(linked)) + list(g.predecessors(linked)):
                    if neighbor == note_stem or neighbor in existing:
                        continue
                    if neighbor in title_set:
                        scores[neighbor] = scores.get(neighbor, 0) + 2

            # Step 4: Backlink fan-in -- notes pointed to by multiple candidates
            for candidate in list(scores.keys()):
                if not g.has_node(candidate):
                    continue
                for target in g.successors(candidate):
                    if target != note_stem and target in title_set:
                        scores[target] = scores.get(target, 0) + 1

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        candidates = [title for title, _ in ranked[:max_candidates]]

        logger.info(
            f"Found {len(scores)} candidate notes, sending top {len(candidates)} to Claude"
        )
        return candidates

    def get_note_content(self, vault_relative_path: str) -> str:
        """Read note content via Obsidian Local REST API."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        encoded_path = quote(vault_relative_path, safe="/")
        resp = httpx.get(
            f"{self.api_base}/vault/{encoded_path}",
            headers=headers,
            verify=False,
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.text

    def suggest_wikilinks(
        self, note_content: str, index: VaultIndex, note_stem: str = ""
    ) -> list[WikilinkSuggestion]:
        """Find candidates via graph, then call Claude for final selection."""
        system = self.SYSTEM_PROMPT.format(max_suggestions=self.max_suggestions)

        candidates = self.find_candidates(note_content, note_stem, index)
        if not candidates:
            logger.info("No candidates found via graph traversal")
            return []

        titles_block = "\n".join(candidates)

        user_prompt = f"""New note content:
---
{note_content}
---

Existing vault note titles (one per line, ONLY these are valid link targets):
{titles_block}

Return a JSON array. Keep reasons under 10 words."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = response.content[0].text

        # Strip markdown fences if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        try:
            data = json.loads(response_text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            logger.error(f"Response was: {response_text}")
            return []

        min_levels = {
            "high": ["high"],
            "medium": ["high", "medium"],
            "low": ["high", "medium", "low"],
        }
        allowed = min_levels.get(self.min_confidence, ["high", "medium"])

        suggestions = []
        for item in data:
            if not isinstance(item, dict):
                continue
            conf = item.get("confidence", "low").lower()
            if conf in allowed:
                title = (
                    item.get("target_title")
                    or item.get("target_note")
                    or item.get("link_target")
                    or item.get("title", "")
                )
                phrase = item.get("anchor_phrase") or item.get("phrase", "")
                if not title or not phrase:
                    continue
                suggestions.append(
                    WikilinkSuggestion(
                        target_title=title,
                        anchor_phrase=phrase,
                        confidence=conf,
                        reason=item.get("reason", ""),
                    )
                )

        return suggestions[: self.max_suggestions]

    def insert_wikilinks(
        self, content: str, suggestions: list[WikilinkSuggestion]
    ) -> str:
        """Insert [[wikilinks]] into content for matching phrases.

        Protects YAML frontmatter. Processes from end to start to avoid offset drift.
        """
        # Split off YAML frontmatter so we don't corrupt it
        body = content
        frontmatter = ""
        if content.startswith("---"):
            end_idx = content.find("---", 3)
            if end_idx != -1:
                fm_end = end_idx + 3
                frontmatter = content[:fm_end]
                body = content[fm_end:]

        # Pre-compute all [[...]] spans in the body to avoid inserting inside existing links
        linked_spans = [
            (m.start(), m.end()) for m in re.finditer(r"\[\[.*?\]\]", body)
        ]

        def is_inside_link(pos_start: int, pos_end: int) -> bool:
            return any(ls <= pos_start and pos_end <= le for ls, le in linked_spans)

        insertions = []
        for s in suggestions:
            pattern = re.compile(re.escape(s.anchor_phrase), re.IGNORECASE)
            for match in pattern.finditer(body):
                start, end = match.start(), match.end()
                if is_inside_link(start, end):
                    continue
                insertions.append((start, end, s))
                break  # Only first occurrence

        insertions.sort(key=lambda x: x[0], reverse=True)

        for start, end, s in insertions:
            original = body[start:end]
            if original.lower() == s.target_title.lower():
                replacement = f"[[{original}]]"
            else:
                replacement = f"[[{s.target_title}|{original}]]"
            body = body[:start] + replacement + body[end:]

        return frontmatter + body

    def update_note(self, vault_relative_path: str, new_content: str) -> bool:
        """Write updated note content via Obsidian Local REST API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "text/markdown",
        }
        encoded_path = quote(vault_relative_path, safe="/")
        resp = httpx.put(
            f"{self.api_base}/vault/{encoded_path}",
            headers=headers,
            content=new_content.encode("utf-8"),
            verify=False,
            timeout=10.0,
        )
        resp.raise_for_status()
        return True

    def autolink_note(
        self, vault_relative_path: str, dry_run: bool = False
    ) -> AutolinkResult:
        """Full autolink flow for a single note."""
        try:
            try:
                httpx.get(self.api_base, verify=False, timeout=5)
            except httpx.ConnectError:
                return AutolinkResult(
                    success=False,
                    note_path=vault_relative_path,
                    links_added=0,
                    error="Obsidian Local REST API not reachable. Is Obsidian running?",
                )

            logger.info("Building vault index...")
            index = self.build_vault_index()
            logger.info(f"Indexed {len(index.titles)} notes")

            content = self.get_note_content(vault_relative_path)
            note_stem = Path(vault_relative_path).stem

            logger.info("Getting wikilink suggestions via graph traversal + Claude...")
            suggestions = self.suggest_wikilinks(content, index, note_stem=note_stem)
            logger.info(f"Got {len(suggestions)} suggestions")

            if dry_run:
                return AutolinkResult(
                    success=True,
                    note_path=vault_relative_path,
                    links_added=0,
                    suggestions=suggestions,
                )

            new_content = self.insert_wikilinks(content, suggestions)
            links_added = new_content.count("[[") - content.count("[[")

            if links_added > 0:
                self.update_note(vault_relative_path, new_content)
                logger.info(
                    f"Added {links_added} wikilinks to {vault_relative_path}"
                )

            return AutolinkResult(
                success=True,
                note_path=vault_relative_path,
                links_added=links_added,
                suggestions=suggestions,
            )

        except Exception as e:
            logger.error(f"Autolink failed for {vault_relative_path}: {e}")
            return AutolinkResult(
                success=False,
                note_path=vault_relative_path,
                links_added=0,
                error=str(e),
            )
