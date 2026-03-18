# Issue: Auto-Wikilink Insertion for New Vault Notes

## Summary

Add `src/autolink.py` — a module that takes a newly created Obsidian note and
automatically inserts `[[wikilinks]]` to semantically related notes already in
the vault. Called at the end of the pipeline after a note is written to disk.

This closes the loop: voice dump → transcribe → classify → **write to vault →
autolink → graph grows**.

---

## Context

- **Vault path**: `/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault`
- **Obsidian Local REST API plugin**: already installed, runs on `https://127.0.0.1:27124` (self-signed cert, use `verify=False`)
- **API key**: stored in `.env` as `OBSIDIAN_LOCAL_REST_API_KEY` (add this variable)
- **Existing pipeline**: `src/pipeline.py` — the new module slots in after the Notion write step
- **Existing pattern**: Claude calls follow `src/classify.py` exactly — `anthropic.Anthropic()`, raw JSON response, graceful fallback

---

## What to Build

### New file: `src/autolink.py`

```python
"""
Auto-Wikilink Insertion Module

Given a newly written Obsidian note path, suggests and inserts [[wikilinks]]
to semantically related notes in the vault.

Flow:
  1. Load vault index (all note titles) via obsidiantools
  2. Read the new note content via Obsidian Local REST API
  3. Call Claude with (note content + vault titles) → get wikilink suggestions
  4. Insert [[wikilinks]] into note content where terms appear
  5. Write updated content back via REST API
"""

### Classes / Functions

#### `VaultIndex`
```python
@dataclass
class VaultIndex:
    titles: list[str]          # all note titles (filename without .md)
    title_to_path: dict[str, str]  # title -> relative vault path
    existing_links: dict[str, list[str]]  # note title -> its existing [[wikilinks]]
```

#### `WikilinkSuggestion`
```python
@dataclass
class WikilinkSuggestion:
    target_title: str          # the note to link to (exact title)
    anchor_phrase: str         # the phrase in the new note to wrap with [[]]
    confidence: str            # "high" | "medium" | "low"
    reason: str                # one-line explanation
```

#### `AutoLinker`

```python
class AutoLinker:
    VAULT_PATH = Path("/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault")
    REST_API_BASE = "https://127.0.0.1:27124"

    def build_vault_index(self) -> VaultIndex
    def get_note_content(self, vault_relative_path: str) -> str   # via REST API
    def suggest_wikilinks(self, note_content: str, index: VaultIndex) -> list[WikilinkSuggestion]
    def insert_wikilinks(self, content: str, suggestions: list[WikilinkSuggestion]) -> str
    def update_note(self, vault_relative_path: str, new_content: str) -> bool  # via REST API
    def autolink_note(self, vault_relative_path: str) -> AutolinkResult
```

#### `AutolinkResult`
```python
@dataclass
class AutolinkResult:
    success: bool
    note_path: str
    links_added: int
    suggestions: list[WikilinkSuggestion]
    error: Optional[str] = None
```

---

## Implementation Details

### 1. Build vault index with obsidiantools

```python
import obsidiantools.api as otools

vault = otools.Vault(VAULT_PATH).connect().gather()
titles = list(vault.md_file_index.keys())  # all note stems (no .md)
# Map title -> relative path
title_to_path = {stem: str(path) for stem, path in vault.md_file_index.items()}
```

**Skip** notes in: `.obsidian/`, `.smart-env/`, `.trash/`, `05_Utils/`, `06_Archive/`  
**Include**: `00_Atoms/`, `01_Capture/`, `02_Projects/`, `03_Next/`, `04_Resources/`

### 2. Read note via REST API

```python
import httpx

headers = {"Authorization": f"Bearer {settings.obsidian_rest_api_key}"}
resp = httpx.get(
    f"{REST_API_BASE}/vault/{vault_relative_path}",
    headers=headers,
    verify=False  # self-signed cert
)
content = resp.text
```

### 3. Claude prompt for wikilink suggestions

System prompt:
```
You are a knowledge graph assistant for a personal Obsidian vault.
Given the content of a new note and a list of existing note titles,
identify which existing notes should be wikilinked in the new note.

Rules:
- Only suggest links where the concept is genuinely referenced in the note
- Suggest the exact phrase in the note text that should become the wikilink
- anchor_phrase must appear VERBATIM (case-insensitive) in the note content
- Prefer atomic/concept notes over project or capture notes as link targets
- Max 8 suggestions, only HIGH or MEDIUM confidence
- Do NOT suggest links to the note itself
- Do NOT suggest links if the phrase is already [[linked]]
- Return valid JSON only, no markdown fences
```

User prompt:
```
New note content:
---
{note_content}
---

Existing vault note titles (these are the only valid link targets):
{json.dumps(titles, indent=2)}

Return JSON array:
[
  {
    "target_title": "Exact Note Title",
    "anchor_phrase": "exact phrase from note text",
    "confidence": "high|medium|low",
    "reason": "one line"
  }
]
```

### 4. Insert wikilinks into content

For each suggestion (HIGH and MEDIUM confidence only):
- Do a **case-insensitive** search for `anchor_phrase` in content
- Skip if the phrase is already inside `[[...]]`
- Replace first occurrence with `[[target_title|anchor_phrase]]` if titles differ,
  or `[[anchor_phrase]]` if they match exactly
- Process suggestions in reverse order of position to avoid offset drift

```python
import re

def insert_wikilinks(content: str, suggestions: list[WikilinkSuggestion]) -> str:
    # Filter to high/medium only
    # Sort by position descending (process from end to avoid offset issues)
    # For each: check not already linked, then insert
```

### 5. Write back via REST API

```python
resp = httpx.put(
    f"{REST_API_BASE}/vault/{vault_relative_path}",
    headers={**headers, "Content-Type": "text/markdown"},
    content=new_content.encode("utf-8"),
    verify=False
)
```

---

## Pipeline Integration

In `src/pipeline.py`, after the Notion write step, add:

```python
# Stage N: Autolink (if note was written to Obsidian vault)
if obsidian_note_path:
    from .autolink import AutoLinker
    linker = AutoLinker()
    autolink_result = linker.autolink_note(obsidian_note_path)
    logger.info(f"Autolink: added {autolink_result.links_added} wikilinks")
    result.autolink_result = autolink_result
```

Also add `autolink_result: Optional[AutolinkResult] = None` to `PipelineResult`.

---

## Settings changes

Add to `config/settings.py`:
```python
# Obsidian Local REST API
self.obsidian_rest_api_key = os.getenv("OBSIDIAN_LOCAL_REST_API_KEY", "")
self.obsidian_vault_path = Path(
    "/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault"
)

# Autolink settings
self.autolink_min_confidence = "medium"  # "high" | "medium" | "low"
self.autolink_max_suggestions = 8
self.autolink_skip_folders = [".obsidian", ".smart-env", ".trash", "05_Utils", "06_Archive"]
```

Add to `.env.example`:
```
OBSIDIAN_LOCAL_REST_API_KEY=your_key_here
```

---

## Requirements changes

Add to `requirements.txt`:
```
obsidiantools>=0.11.0
```

Note: obsidiantools requires `networkx` and `pandas` — add if not already present.

---

## Standalone CLI usage

```bash
# Autolink a single note (for testing)
python scripts/cli.py autolink "01_Capture/My New Note.md"

# Dry-run (shows suggestions, doesn't write)
python scripts/cli.py autolink "01_Capture/My New Note.md" --dry-run
```

Add `autolink` command to `scripts/cli.py` using the same Click pattern as existing commands.

---

## Unit Tests

**File**: `tests/test_autolink.py`

| Test | Description |
|------|-------------|
| `test_insert_wikilinks_basic` | Phrase in content → gets wrapped in `[[]]` |
| `test_insert_wikilinks_already_linked` | Already `[[linked]]` phrase → skipped |
| `test_insert_wikilinks_case_insensitive` | "essentialism" matches "Essentialism.md" |
| `test_insert_wikilinks_no_double_wrap` | Running twice doesn't double-wrap |
| `test_insert_wikilinks_title_differs_from_phrase` | Uses `[[Title|phrase]]` format |
| `test_suggest_wikilinks_mock_claude` | Mock Claude response → returns WikilinkSuggestion list |
| `test_suggest_wikilinks_filters_low_confidence` | LOW confidence suggestions excluded |
| `test_autolink_note_dry_run` | Dry run returns suggestions, doesn't call PUT |
| `test_vault_index_excludes_skip_folders` | `.trash`, `05_Utils` not in index titles |

Mock pattern (follow `tests/test_classify.py`):
```python
@pytest.fixture
def mock_claude():
    with patch("src.autolink.anthropic.Anthropic") as mock:
        client = MagicMock()
        mock.return_value = client
        response = MagicMock()
        response.content = [MagicMock(text='[{"target_title": "Essentialism", "anchor_phrase": "essentialism", "confidence": "high", "reason": "direct reference"}]')]
        client.messages.create.return_value = response
        yield client

@pytest.fixture
def mock_obsidian_api():
    with patch("src.autolink.httpx") as mock:
        mock.get.return_value.text = "Some note content about essentialism and focus."
        mock.get.return_value.status_code = 200
        mock.put.return_value.status_code = 200
        yield mock
```

---

## Acceptance Criteria

- [ ] `AutoLinker.build_vault_index()` returns all note titles from the 5 active folders
- [ ] `AutoLinker.suggest_wikilinks()` returns `WikilinkSuggestion` list from Claude
- [ ] `AutoLinker.insert_wikilinks()` wraps matching phrases correctly, skips already-linked
- [ ] `AutoLinker.autolink_note()` full flow works on a real vault note
- [ ] CLI command `autolink` with `--dry-run` works
- [ ] Pipeline integration: `PipelineResult` includes `autolink_result`
- [ ] All unit tests pass
- [ ] No regressions in existing tests (`pytest tests/ -v`)

## Verification Steps

```bash
cd /Users/nick/Documents/cognosmap-automation
source venv/bin/activate

# 1. Install new dep
pip install obsidiantools

# 2. Add OBSIDIAN_LOCAL_REST_API_KEY to .env
# (get key from Obsidian → Settings → Local REST API → Copy Key)

# 3. Run tests
python -m pytest tests/test_autolink.py -v

# 4. Dry run on a real note
python scripts/cli.py autolink "01_Capture/CognosMap Knowledge Product.md" --dry-run

# 5. Live run on a test note
python scripts/cli.py autolink "01_Capture/Agent Frameworks Suck, and what to do about it.md"

# 6. Open Obsidian and verify [[wikilinks]] were inserted
```

## Key File Paths

| What | Where |
|------|-------|
| New module | `src/autolink.py` |
| Settings | `config/settings.py` (add 4 new vars) |
| Pipeline integration | `src/pipeline.py` (add autolink stage) |
| CLI command | `scripts/cli.py` (add `autolink` command) |
| Tests | `tests/test_autolink.py` |
| Requirements | `requirements.txt` (add `obsidiantools`) |
| Env example | `.env.example` (add `OBSIDIAN_LOCAL_REST_API_KEY`) |
| Vault path | `/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault` |
| REST API | `https://127.0.0.1:27124` (self-signed, `verify=False`) |
