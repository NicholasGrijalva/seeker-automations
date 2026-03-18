## Add auto-wikilink insertion to close the voice→graph loop

### Problem Statement
New notes created by the pipeline arrive in the Obsidian vault as flat, isolated
Markdown files. The vault already contains 300+ notes with meaningful conceptual
overlap — atomic notes, capture essays, project notes — but nothing connects them
automatically. Every `[[wikilink]]` is inserted by hand.

The result: the knowledge graph never grows. Voice dumps get transcribed and
classified, then sit as orphans. The whole point of Obsidian's graph view is
compounding — ideas linking to ideas over time — but that only happens if links
exist.

IMPACT: Every voice dump that enters the pipeline is wasted as a graph asset.
The vault has `00_Atoms/` notes like `Courage is the first virtue.md`,
`Essentialism`, `The Obstacle is the way.md` that should be automatically cited
whenever new content touches those ideas. Currently zero of them are linked
programmatically.

PRIORITY: High — this is the feature that makes the whole pipeline worth running.

---

### Context
COMMIT: see `git log --oneline -1` in `/Users/nick/Documents/cognosmap-automation`
BRANCH: main
RELATED_ISSUES: Multimedia Triage Pipeline spec (`specs/multimedia-triage-pipeline-spec.md`)

---

### Current Behavior
Pipeline runs: voice → transcribe → classify → Notion write.
Notes are written to vault (or will be once Obsidian write is wired in).
Zero `[[wikilinks]]` are inserted. The Obsidian graph view shows isolated nodes.

```
01_Capture/Agent Frameworks Suck, and what to do about it.md
# Agent Frameworks Suck

The problem with agent frameworks is they abstract away the parts you need
to understand. Essentialism matters here — you want to know what's actually
running, not a wrapper around it.
```
→ `Essentialism` is a real note in `00_Atoms/`. Never linked. Lost.

### Expected Behavior
After pipeline runs, the same note reads:

```
The problem with agent frameworks is they abstract away the parts you need
to understand. [[Essentialism]] matters here — you want to know what's
actually running, not a wrapper around it.
```

And Obsidian's graph view shows the edge. Over hundreds of notes, the graph
becomes a real map of the creator's thinking.

---

### Technical Context

#### Affected Files
- [`src/pipeline.py`](src/pipeline.py:L141-L291) — add autolink stage after Notion write
- [`src/pipeline.py`](src/pipeline.py:L22-L40) — add `autolink_result` field to `PipelineResult`
- [`config/settings.py`](config/settings.py:L1-L106) — add 4 new config vars
- [`scripts/cli.py`](scripts/cli.py:L85-L140) — add `autolink` CLI command (follow `process` pattern)
- [`requirements.txt`](requirements.txt) — add `obsidiantools>=0.11.0`
- `.env.example` — add `OBSIDIAN_LOCAL_REST_API_KEY`

#### New Files
- `src/autolink.py` — the entire new module (~150 lines)
- `tests/test_autolink.py` — unit tests (9 tests)

#### Code References
- `Classifier.classify()` — [src/classify.py:L63-L120] — exact pattern to follow for Claude call + JSON parse + graceful fallback
- `PipelineResult` — [src/pipeline.py:L22-L40] — dataclass to extend with `autolink_result`
- `_process_text_internal()` — [src/pipeline.py:L141-L291] — where autolink stage slots in (after L240 Notion write)
- `@cli.command() process` — [scripts/cli.py:L85-L140] — Click pattern to replicate for `autolink` command
- `TestClassifier` fixture pattern — [tests/test_classify.py:L35-L65] — mock pattern to replicate

#### Dependencies
- External: `obsidiantools>=0.11.0` (MIT, pure Python, builds networkx graph from vault)
- External: `httpx>=0.25.0` (already in requirements.txt — REST API calls)
- External: `anthropic>=0.40.0` (already in requirements.txt — wikilink suggestions)
- Internal: `config/settings.py` — add `obsidian_rest_api_key`, `obsidian_vault_path`, `autolink_min_confidence`, `autolink_skip_folders`
- Obsidian plugin: `obsidian-local-rest-api` — **already installed** in vault

---

### Proposed Solution

#### Architecture

```
autolink_note(vault_relative_path)
        │
        ├─ 1. build_vault_index()        ← obsidiantools scans vault
        │       returns VaultIndex:
        │         titles: list[str]       ← all note stems, filtered to active folders
        │         title_to_path: dict
        │
        ├─ 2. get_note_content()          ← GET /vault/{path} via REST API
        │
        ├─ 3. suggest_wikilinks()         ← Claude: (content + titles) → JSON suggestions
        │       returns list[WikilinkSuggestion]:
        │         target_title, anchor_phrase, confidence, reason
        │
        ├─ 4. insert_wikilinks()          ← pure string manipulation, no I/O
        │       filter to HIGH/MEDIUM only
        │       process in reverse position order (no offset drift)
        │       skip already-[[linked]] phrases
        │
        └─ 5. update_note()              ← PUT /vault/{path} via REST API
```

#### Step 1: New file `src/autolink.py`

```python
"""
Auto-Wikilink Insertion Module

Given a newly written Obsidian note path, suggests and inserts [[wikilinks]]
to semantically related notes in the vault.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import anthropic
import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

VAULT_PATH = Path("/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault")
REST_API_BASE = "https://127.0.0.1:27124"
ACTIVE_FOLDERS = {"00_Atoms", "01_Capture", "02_Projects", "03_Next", "04_Resources"}


@dataclass
class VaultIndex:
    titles: list[str]
    title_to_path: dict[str, str]
    existing_links: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class WikilinkSuggestion:
    target_title: str
    anchor_phrase: str
    confidence: str   # "high" | "medium" | "low"
    reason: str


@dataclass
class AutolinkResult:
    success: bool
    note_path: str
    links_added: int
    suggestions: list[WikilinkSuggestion]
    error: Optional[str] = None


class AutoLinker:

    SYSTEM_PROMPT = """You are a knowledge graph assistant for a personal Obsidian vault.
Given a new note's content and a list of existing note titles, identify which
existing notes should be wikilinked within the new note.

Rules:
- Only suggest links where the concept is GENUINELY referenced in the note content
- anchor_phrase must appear VERBATIM (case-insensitive) in the note content
- Prefer atomic concept notes (short title, philosophical/principle-style) over
  project or capture notes as link targets
- Maximum 8 suggestions, confidence HIGH or MEDIUM only
- Do NOT suggest links to the note itself
- Do NOT suggest if the phrase is already inside [[...]]
- Return valid JSON array only — no markdown fences, no explanation"""

    def build_vault_index(self) -> VaultIndex:
        """Build index of all note titles from active vault folders."""
        import obsidiantools.api as otools
        vault = otools.Vault(VAULT_PATH).connect().gather()

        titles = []
        title_to_path = {}

        for stem, path in vault.md_file_index.items():
            path_str = str(path)
            # Only include notes from active folders
            parts = Path(path_str).parts
            if not parts:
                continue
            top_folder = parts[0] if len(parts) > 1 else ""
            if any(path_str.startswith(f) for f in ACTIVE_FOLDERS):
                titles.append(stem)
                title_to_path[stem] = path_str

        # Also capture existing wikilinks per note for context
        existing_links = {}
        for stem in titles:
            try:
                wikilinks = vault.get_wikilinks(stem)
                if wikilinks:
                    existing_links[stem] = list(wikilinks)
            except Exception:
                pass

        logger.info(f"Vault index built: {len(titles)} notes across active folders")
        return VaultIndex(titles=titles, title_to_path=title_to_path, existing_links=existing_links)

    def get_note_content(self, vault_relative_path: str) -> str:
        """Read note content via Obsidian Local REST API."""
        headers = {"Authorization": f"Bearer {settings.obsidian_rest_api_key}"}
        resp = httpx.get(
            f"{REST_API_BASE}/vault/{vault_relative_path}",
            headers=headers,
            verify=False,
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.text

    def suggest_wikilinks(
        self, note_content: str, index: VaultIndex
    ) -> list[WikilinkSuggestion]:
        """Call Claude to suggest wikilinks for a note."""
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        user_prompt = f"""New note content:
---
{note_content[:4000]}
---

Existing vault note titles (ONLY these are valid link targets):
{json.dumps(index.titles, indent=2)}

Return JSON array:
[
  {{
    "target_title": "Exact Note Title",
    "anchor_phrase": "exact phrase from note text",
    "confidence": "high|medium|low",
    "reason": "one line"
  }}
]"""

        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )

        response_text = response.content[0].text.strip()
        # Strip markdown fences if present
        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]

        try:
            raw = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse wikilink suggestions: {e}")
            return []

        suggestions = []
        for item in raw:
            try:
                suggestions.append(WikilinkSuggestion(
                    target_title=item["target_title"],
                    anchor_phrase=item["anchor_phrase"],
                    confidence=item["confidence"],
                    reason=item.get("reason", "")
                ))
            except KeyError:
                continue

        return suggestions
```

    def insert_wikilinks(
        self, content: str, suggestions: list[WikilinkSuggestion]
    ) -> str:
        """Insert [[wikilinks]] into note content for high/medium confidence suggestions."""
        # Filter to high and medium only
        filtered = [s for s in suggestions if s.confidence in ("high", "medium")]

        # Find positions of each anchor phrase (case-insensitive)
        positioned = []
        for suggestion in filtered:
            pattern = re.compile(re.escape(suggestion.anchor_phrase), re.IGNORECASE)
            for match in pattern.finditer(content):
                start = match.start()
                # Check not already inside [[...]]
                before = content[max(0, start - 2):start]
                if "[[" not in before:
                    positioned.append((start, suggestion, match.group()))
                    break  # First occurrence only

        # Sort by position descending to avoid offset drift
        positioned.sort(key=lambda x: x[0], reverse=True)

        for start, suggestion, matched_text in positioned:
            end = start + len(matched_text)
            # Build wikilink: [[Title|phrase]] if different, [[phrase]] if same
            if suggestion.target_title.lower() == matched_text.lower():
                link = f"[[{matched_text}]]"
            else:
                link = f"[[{suggestion.target_title}|{matched_text}]]"
            content = content[:start] + link + content[end:]

        return content

    def update_note(self, vault_relative_path: str, new_content: str) -> bool:
        """Write updated note content back via REST API."""
        headers = {
            "Authorization": f"Bearer {settings.obsidian_rest_api_key}",
            "Content-Type": "text/markdown"
        }
        resp = httpx.put(
            f"{REST_API_BASE}/vault/{vault_relative_path}",
            headers=headers,
            content=new_content.encode("utf-8"),
            verify=False,
            timeout=10.0
        )
        return resp.status_code == 200

    def autolink_note(
        self, vault_relative_path: str, dry_run: bool = False
    ) -> AutolinkResult:
        """Full autolink flow for a single note."""
        try:
            index = self.build_vault_index()
            content = self.get_note_content(vault_relative_path)
            suggestions = self.suggest_wikilinks(content, index)

            if dry_run:
                high_med = [s for s in suggestions if s.confidence in ("high", "medium")]
                return AutolinkResult(
                    success=True,
                    note_path=vault_relative_path,
                    links_added=0,
                    suggestions=suggestions
                )

            new_content = self.insert_wikilinks(content, suggestions)
            links_added = new_content.count("[[") - content.count("[[")

            if links_added > 0:
                self.update_note(vault_relative_path, new_content)
                logger.info(f"Autolink: inserted {links_added} wikilinks in {vault_relative_path}")

            return AutolinkResult(
                success=True,
                note_path=vault_relative_path,
                links_added=links_added,
                suggestions=suggestions
            )

        except Exception as e:
            logger.error(f"Autolink failed for {vault_relative_path}: {e}")
            return AutolinkResult(
                success=False,
                note_path=vault_relative_path,
                links_added=0,
                suggestions=[],
                error=str(e)
            )
```

#### Step 2: Extend `config/settings.py`

Add after `self.claude_model` line (~L80):

```python
# Obsidian Local REST API (plugin: obsidian-local-rest-api)
# Get key: Obsidian → Settings → Community Plugins → Local REST API → Copy Key
self.obsidian_rest_api_key = os.getenv("OBSIDIAN_LOCAL_REST_API_KEY", "")
self.obsidian_vault_path = Path(
    "/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault"
)

# Autolink settings
self.autolink_min_confidence = "medium"   # "high" | "medium" | "low"
self.autolink_max_suggestions = 8
self.autolink_skip_folders = [
    ".obsidian", ".smart-env", ".trash", "05_Utils", "06_Archive"
]
```

#### Step 3: Integrate into `src/pipeline.py`

Add to `PipelineResult` dataclass (after `platform_outputs` field, ~L38):
```python
autolink_result: Optional["AutolinkResult"] = None
```

Add to `_process_text_internal()` after the Notion write block (~L240), before `result.success = True`:
```python
# Stage N: Autolink (Obsidian wikilink insertion)
if obsidian_note_path and settings.obsidian_rest_api_key:
    logger.info("Stage N: Auto-linking Obsidian note")
    from .autolink import AutoLinker
    linker = AutoLinker()
    result.autolink_result = linker.autolink_note(obsidian_note_path)
    result.stage_reached = "autolink"
    logger.info(f"Autolink complete: {result.autolink_result.links_added} links added")
```

Note: `obsidian_note_path` is a new parameter — the vault-relative path of the
note written to disk. Wire this in when Obsidian file write is implemented; for
now the stage is gated on `obsidian_note_path` being set.

#### Step 4: Add CLI command to `scripts/cli.py`

Add after the `check` command, following the exact Click pattern of existing commands:

```python
@cli.command()
@click.argument("note_path")
@click.option("--dry-run", is_flag=True, help="Show suggestions without writing")
def autolink(note_path: str, dry_run: bool):
    """Insert [[wikilinks]] into an Obsidian note."""

    if not settings.obsidian_rest_api_key:
        console.print("[red]OBSIDIAN_LOCAL_REST_API_KEY not set in .env[/red]")
        console.print("Get it: Obsidian → Settings → Community Plugins → Local REST API → Copy Key")
        sys.exit(1)

    from src.autolink import AutoLinker
    linker = AutoLinker()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        progress.add_task(
            f"{'[DRY RUN] ' if dry_run else ''}Autolinking {note_path}...",
            total=None
        )
        result = linker.autolink_note(note_path, dry_run=dry_run)

    if not result.success:
        console.print(f"[red]Autolink failed:[/red] {result.error}")
        sys.exit(1)

    table = Table(title=f"Wikilink Suggestions ({len(result.suggestions)} total)")
    table.add_column("Target Note", style="cyan")
    table.add_column("Anchor Phrase", style="white")
    table.add_column("Confidence", style="yellow")
    table.add_column("Reason", style="dim")

    for s in result.suggestions:
        color = "green" if s.confidence == "high" else "yellow" if s.confidence == "medium" else "red"
        table.add_row(s.target_title, s.anchor_phrase, f"[{color}]{s.confidence}[/{color}]", s.reason)

    console.print(table)

    if dry_run:
        console.print(f"\n[yellow]DRY RUN — no changes written.[/yellow]")
    else:
        console.print(f"\n[green]✓[/green] Inserted {result.links_added} wikilinks into {note_path}")
```

#### Step 5: New file `tests/test_autolink.py`

```python
"""Tests for the autolink module."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_claude():
    with patch("src.autolink.anthropic.Anthropic") as mock:
        client = MagicMock()
        mock.return_value = client
        response = MagicMock()
        response.content = [MagicMock(text='''[
            {
                "target_title": "Essentialism",
                "anchor_phrase": "essentialism",
                "confidence": "high",
                "reason": "direct reference to essentialism concept"
            },
            {
                "target_title": "The Obstacle is the way.",
                "anchor_phrase": "obstacles",
                "confidence": "medium",
                "reason": "stoic concept referenced"
            }
        ]''')]
        client.messages.create.return_value = response
        yield client


@pytest.fixture
def mock_httpx():
    with patch("src.autolink.httpx") as mock:
        mock.get.return_value.text = (
            "Some note content about essentialism and how obstacles make us stronger."
        )
        mock.get.return_value.status_code = 200
        mock.get.return_value.raise_for_status = MagicMock()
        mock.put.return_value.status_code = 200
        yield mock


@pytest.fixture
def mock_vault_index():
    from src.autolink import VaultIndex
    return VaultIndex(
        titles=["Essentialism", "The Obstacle is the way.", "Courage is the first virtue."],
        title_to_path={
            "Essentialism": "00_Atoms/Essentialism.md",
            "The Obstacle is the way.": "00_Atoms/The Obstacle is the way..md",
            "Courage is the first virtue.": "00_Atoms/Courage is the first virtue..md"
        }
    )


class TestInsertWikilinks:

    def test_insert_wikilinks_basic(self):
        """Phrase in content → gets wrapped in [[]]."""
        from src.autolink import AutoLinker, WikilinkSuggestion
        linker = AutoLinker()
        content = "This is about essentialism and focus."
        suggestions = [WikilinkSuggestion(
            target_title="Essentialism",
            anchor_phrase="essentialism",
            confidence="high",
            reason="test"
        )]
        result = linker.insert_wikilinks(content, suggestions)
        assert "[[essentialism]]" in result or "[[Essentialism|essentialism]]" in result

    def test_insert_wikilinks_already_linked(self):
        """Already [[linked]] phrase → skipped."""
        from src.autolink import AutoLinker, WikilinkSuggestion
        linker = AutoLinker()
        content = "This is about [[essentialism]] and focus."
        suggestions = [WikilinkSuggestion(
            target_title="Essentialism",
            anchor_phrase="essentialism",
            confidence="high",
            reason="test"
        )]
        result = linker.insert_wikilinks(content, suggestions)
        # Should not double-wrap
        assert result.count("[[") == 1

    def test_insert_wikilinks_case_insensitive(self):
        """'essentialism' in text matches 'Essentialism.md' title."""
        from src.autolink import AutoLinker, WikilinkSuggestion
        linker = AutoLinker()
        content = "Essentialism is the practice of focusing only on what matters."
        suggestions = [WikilinkSuggestion(
            target_title="Essentialism",
            anchor_phrase="Essentialism",
            confidence="high",
            reason="test"
        )]
        result = linker.insert_wikilinks(content, suggestions)
        assert "[[" in result

    def test_insert_wikilinks_no_double_wrap(self):
        """Running insert_wikilinks twice doesn't produce nested [[[]]] ."""
        from src.autolink import AutoLinker, WikilinkSuggestion
        linker = AutoLinker()
        content = "This is about essentialism."
        suggestions = [WikilinkSuggestion(
            target_title="Essentialism",
            anchor_phrase="essentialism",
            confidence="high",
            reason="test"
        )]
        once = linker.insert_wikilinks(content, suggestions)
        twice = linker.insert_wikilinks(once, suggestions)
        assert twice.count("[[") == 1

    def test_insert_wikilinks_filters_low_confidence(self):
        """LOW confidence suggestions are not inserted."""
        from src.autolink import AutoLinker, WikilinkSuggestion
        linker = AutoLinker()
        content = "This is about essentialism."
        suggestions = [WikilinkSuggestion(
            target_title="Essentialism",
            anchor_phrase="essentialism",
            confidence="low",
            reason="test"
        )]
        result = linker.insert_wikilinks(content, suggestions)
        assert "[[" not in result

    def test_insert_wikilinks_title_differs_from_phrase(self):
        """When title != phrase, uses [[Title|phrase]] format."""
        from src.autolink import AutoLinker, WikilinkSuggestion
        linker = AutoLinker()
        content = "obstacles are what shape us."
        suggestions = [WikilinkSuggestion(
            target_title="The Obstacle is the way.",
            anchor_phrase="obstacles",
            confidence="high",
            reason="test"
        )]
        result = linker.insert_wikilinks(content, suggestions)
        assert "[[The Obstacle is the way.|obstacles]]" in result


class TestSuggestWikilinks:

    def test_suggest_wikilinks_returns_list(self, mock_claude, mock_vault_index):
        """Mock Claude response → returns WikilinkSuggestion list."""
        from src.autolink import AutoLinker
        linker = AutoLinker()
        content = "Some note content about essentialism and how obstacles make us stronger."
        suggestions = linker.suggest_wikilinks(content, mock_vault_index)
        assert isinstance(suggestions, list)
        assert len(suggestions) == 2
        assert suggestions[0].target_title == "Essentialism"

    def test_suggest_wikilinks_malformed_json_returns_empty(self, mock_vault_index):
        """Malformed Claude JSON → returns empty list, no crash."""
        from src.autolink import AutoLinker
        with patch("src.autolink.anthropic.Anthropic") as mock:
            client = MagicMock()
            mock.return_value = client
            response = MagicMock()
            response.content = [MagicMock(text="not json at all")]
            client.messages.create.return_value = response

            linker = AutoLinker()
            suggestions = linker.suggest_wikilinks("some content", mock_vault_index)
            assert suggestions == []


class TestAutolinkNote:

    def test_autolink_dry_run_does_not_call_put(self, mock_claude, mock_httpx, mock_vault_index):
        """Dry run returns suggestions, does not call PUT."""
        from src.autolink import AutoLinker
        with patch.object(AutoLinker, "build_vault_index", return_value=mock_vault_index):
            linker = AutoLinker()
            result = linker.autolink_note("01_Capture/test.md", dry_run=True)

        assert result.success
        assert result.links_added == 0
        mock_httpx.put.assert_not_called()
```

---

### Acceptance Criteria
- [ ] `AutoLinker.build_vault_index()` returns titles from `00_Atoms`, `01_Capture`, `02_Projects`, `03_Next`, `04_Resources` only
- [ ] `AutoLinker.suggest_wikilinks()` calls Claude with (note content + vault titles) and returns typed `WikilinkSuggestion` list
- [ ] `AutoLinker.insert_wikilinks()` wraps matching phrases, skips already-linked, uses `[[Title|phrase]]` when title ≠ phrase
- [ ] Running `insert_wikilinks` twice produces no double-wrapping
- [ ] LOW confidence suggestions are never inserted
- [ ] `AutoLinker.autolink_note()` full flow works end-to-end on a real vault note
- [ ] `python scripts/cli.py autolink "01_Capture/CognosMap Knowledge Product.md" --dry-run` runs without error and prints suggestion table
- [ ] Live run inserts at least one `[[wikilink]]` in a note that has content matching an Atom
- [ ] `PipelineResult` has `autolink_result` field
- [ ] All 9 unit tests pass
- [ ] `pytest tests/ -v` shows no regressions in existing tests

---

### Verification Steps

```bash
cd /Users/nick/Documents/cognosmap-automation
source venv/bin/activate

# 1. Install new dependency
pip install obsidiantools networkx pandas

# 2. Add to .env:
# OBSIDIAN_LOCAL_REST_API_KEY=<key from Obsidian → Settings → Local REST API>

# 3. Run unit tests
python -m pytest tests/test_autolink.py -v

# 4. Full test suite — no regressions
python -m pytest tests/ -v

# 5. Dry run against a real note
python scripts/cli.py autolink "01_Capture/CognosMap Knowledge Product.md" --dry-run

# 6. Live run against a known-rich note
python scripts/cli.py autolink "01_Capture/Agent Frameworks Suck, and what to do about it.md"

# 7. Open Obsidian → verify [[wikilinks]] visible in the note
# 8. Open Graph View → verify new edges appear
```

---

### Additional Notes

**Self-signed cert**: The Obsidian Local REST API uses a self-signed cert. All
`httpx` calls must use `verify=False`. This is expected and documented.

**Vault path with spaces**: The iCloud path contains spaces
(`iCloud~md~obsidian`). Python's `pathlib.Path` handles this fine. Do not
shell-escape; pass as a `Path` object.

**Context window**: Claude is sent at most 4000 chars of note content. Long notes
are truncated to avoid hitting context limits. The vault title list for a ~300
note vault is ~10KB — fits comfortably.

**obsidiantools build time**: First call scans all vault files. On 300 notes,
expect ~1-2s. Result is not cached between pipeline runs — acceptable for now.

**Idempotent**: Running autolink twice on the same note is safe. The
`already-linked` check prevents double-wrapping.

**Font of truth for note titles**: `obsidiantools` uses the file stem (filename
without `.md`) as the canonical title. This matches how Obsidian resolves
`[[wikilinks]]` — shortest path first.

---

### For AI Implementation

REQUIRED_READING:
- Full reads:
  - `src/classify.py` — Claude call pattern, JSON parse, graceful fallback
  - `tests/test_classify.py` — mock fixture pattern to replicate exactly
  - `scripts/cli.py` — Click command structure, Rich console pattern
  - `config/settings.py` — where to add new config vars
- Partial reads:
  - `src/pipeline.py:L22-L40` — PipelineResult dataclass fields
  - `src/pipeline.py:L220-L260` — where autolink stage inserts after Notion write
  - `requirements.txt:L1-L36` — check before adding deps

LABELS: `feature`, `enhancement`
