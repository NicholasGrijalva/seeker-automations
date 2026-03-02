# Multimedia Capture, Triage & Content Pipeline - Implementation Spec

## Summary

A modular pipeline for capturing multimedia ideas (voice memos, images, videos, links) into a Notion Inbox and automatically triaging them to the correct Notion database (Atomic Ideas, Content Objects, Projects, or Systems) with AI-powered classification and deduplication. Extends the existing seeker-automations Python codebase with multi-database routing, while voice-to-notion (Node.js) remains the separate capture service.

**Problem:** 4+ repos each solve a piece of the same workflow but none covers the full loop. The classifier only tags items with Essay/Video/Post type but doesn't route to the correct destination database. Dozens of Inbox items sit untriaged.

**Outcome:** Inbox items are automatically routed to the correct Notion database with proper properties set, duplicates are caught, and the whole thing runs as a background watcher.

## Current State

| Component | Location | Status |
|-----------|----------|--------|
| Claude classifier (4-type) | `src/classify.py:36-169` | Exists, needs rewrite for routing |
| Notion client (2 DBs) | `src/notion_client.py:19-301` | Exists, needs extension to 5 DBs |
| Pipeline orchestrator | `src/pipeline.py:45-291` | Exists, needs new flow |
| Embedding dedup | `src/dedupe.py:40-181` | Exists, reuse as-is |
| Transcript cleaner | `src/clean.py:18-106` | Exists, reuse as-is |
| Batch processor CLI | `scripts/process_inbox.py:1-473` | Exists, needs routing integration |
| Notion schema models | `config/notion_schema.py:1-247` | Exists, needs 3 new models |
| Settings/config | `config/settings.py:1-107` | Exists, needs new DB IDs |
| Tests | `tests/test_classify.py`, `test_dedupe.py`, `test_pipeline.py` | Minimal, need expansion |
| **OCR endpoint** | notion-pipeline `src/services/notion_ingest.py:194-229` | **Exists in other repo** |
| **Telegram bot** | voice-to-notion `src/telegram-bot.js` | **WIP, uncommitted** |
| **Inbox watcher** | `scripts/watch_folder.py` (file watcher exists, inbox watcher does not) | **NOT BUILT** |
| **Multi-DB routing** | N/A | **NOT BUILT** |

## Notion Database Schemas (verified from API)

```
INBOX (collection://418b91e7-0c93-45b7-b905-c4715ab25964)
  database_id: 2c0eba0c-abd5-45d0-a760-6549cd0f3c84
  Title (title), Status (select: New|Triaged|Processed|Needs verification|Done),
  Type (select: Idea|Post|Audio|Video|YouTube), Tags (multi_select),
  Source (text), Transcript (text), URL (url), Source Filename (text),
  Date Added (date), Processing Time (s) (number), Project (relation -> Projects)

ATOMIC IDEAS (collection://cab1ca22-05d8-4c60-a5bc-5175b4008f75)
  database_id: 52c73f47-189a-4471-973c-2e440fdf0068
  Title (title), Status (select: Backlog|Planning|To-Do|Active|Done|Archived),
  Category (select: Raw|Developing|Refined|Evergreen|Deprecated),
  Tags (multi_select), Topic Tags (multi_select),
  Source (relation -> Inbox), Original Inbox Item (relation -> Inbox),
  Linked Ideas (relation -> self), Date Created (created_time)

CONTENT OBJECTS (collection://15d28d70-ca5f-4183-b0fb-667af249ac20)
  database_id: db6f21b8-b261-4711-9ae0-b920861ec3c0
  Name (title), Status (select: Backlog|Planning|To-Do|Scheduled|Done|Archived),
  Category (select: New|Draft|Essay Done|Video Done|Posts Done|Deprecated),
  Content Type (select: Essay|Video|Thread|Post), Tags (multi_select),
  Platform (select: YouTube|Shorts|Instagram|TikTok|LinkedIn|Twitter|Blog),
  Atomic Ideas (relation -> Atomic Ideas), Main Idea (relation -> Atomic Ideas, single),
  Original Transcript (relation -> Inbox), Post Examples (relation -> Post Examples),
  Target Publish Date (date), Asset Folder URL (url), Transcript URL (url),
  Date Created (created_time)

PROJECTS (collection://2ce207a3-926a-80ba-b4c7-000b21d1ed60)
  database_id: 2ce207a3-926a-8025-98ce-d89e113211e8
  Name (title), Status (status: To Do|Backlog|In Progress|Done),
  Priority 1 (select: NOW|ESSENTIAL|LOW),
  Domain (multi_select: Business|Relationships|Health|Spiritual|Personal|Meta),
  Work Type (multi_select: Software|System upgrades|Research),
  Due (date), Assignee (person)

SYSTEMS (collection://b9018ec6-e829-4686-bd1d-55b455fd6baf)
  database_id: 0c27f2ee-7480-4d8d-a620-ab729a5b3e0c
  System (title), Category (select: Relationships|Personality|Health|Business|Work),
  Summary (text), Notes (text), Source (url), Last reviewed (date)
```

## Implementation Plan

### Issue 1: Add routing classifier (rewrite `src/classify.py`)

**File:** `src/classify.py`
**Lines:** Replace `SYSTEM_PROMPT` (39-80) and `ClassificationResult` (19-33)

**What changes:**
- New `RoutingResult` dataclass replaces `ClassificationResult`
- New system prompt that understands all 4 target databases and their schemas
- Returns `target_database` field + DB-specific properties
- Keeps Claude Sonnet 4, raw JSON parsing pattern (no structured output change)

```python
@dataclass
class RoutingResult:
    target_database: str  # "atomic_ideas" | "content_objects" | "projects" | "systems"
    title: str
    summary: str          # 1-2 sentence core insight/action
    tags: list[str]
    # DB-specific (only relevant fields populated):
    # Atomic Ideas
    topic_tags: list[str] = field(default_factory=list)
    # Content Objects
    content_type: Optional[str] = None   # Essay|Video|Thread|Post
    platform: Optional[str] = None
    # Projects
    priority: Optional[str] = None       # NOW|ESSENTIAL|LOW
    domain: Optional[str] = None
    work_type: Optional[str] = None
    # Systems
    system_category: Optional[str] = None  # Relationships|Personality|Health|Business|Work
    system_summary: Optional[str] = None
```

**Routing heuristics for the prompt:**
- Standalone insight, belief, observation, philosophy -> `atomic_ideas`
- "I should write about X", content idea, essay plan -> `content_objects`
- "This should be a system", repeatable process, SOP, strategy -> `systems`
- "I need to build X", active project, task with deadline -> `projects`
- If item contains stored reference material / research / consumption queue -> `atomic_ideas` (with tag `research`)
- Default when unclear: `atomic_ideas` (safest catch-all)

**Backward compatibility:** Keep `classify_content()` convenience function but have it return `RoutingResult`. The `ClassificationResult` can be kept as a deprecated alias initially.

### Issue 2: Add Notion schema models for Projects + Systems (`config/notion_schema.py`)

**File:** `config/notion_schema.py`
**Lines:** After line 247 (append)

**What changes:** Add `ProjectItem`, `SystemItem` dataclasses + `to_notion_properties()` methods following the exact same pattern as `InboxItem` (line 13) and `ContentObject` (line 71).

```python
@dataclass
class AtomicIdeaItem:
    title: str
    status: str = "Backlog"
    category: str = "Raw"
    tags: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    source_inbox_page_id: Optional[str] = None  # Relation back to Inbox

@dataclass
class ProjectItem:
    name: str
    status: str = "To Do"
    priority: str = "LOW"           # NOW|ESSENTIAL|LOW
    domain: list[str] = field(default_factory=list)
    work_type: list[str] = field(default_factory=list)
    due: Optional[datetime] = None

@dataclass
class SystemItem:
    system: str                      # title field is called "System"
    category: Optional[str] = None   # Relationships|Personality|Health|Business|Work
    summary: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None     # URL
```

Each needs a `to_notion_properties()` method matching the exact Notion property names from the schemas above.

### Issue 3: Extend Notion client to 5 databases (`src/notion_client.py`)

**File:** `src/notion_client.py`
**Lines:** Extend class starting at line 19

**What changes:**
- Add database/data-source IDs for Atomic Ideas, Projects, Systems to constructor
- Add `create_atomic_idea(item: AtomicIdeaItem)`, `create_project(item: ProjectItem)`, `create_system(item: SystemItem)` methods
- Add `query_atomic_ideas()`, `query_projects()`, `query_systems()` methods
- Add generic `create_in_database(target: str, properties: dict, content_blocks: list)` router method
- Add `search_database(target: str, text: str, limit: int)` for dedup across any DB

**New IDs to add to `config/settings.py`:**
```python
# Atomic Ideas
atomic_ideas_database_id = "52c73f47-189a-4471-973c-2e440fdf0068"
atomic_ideas_data_source_id = "cab1ca22-05d8-4c60-a5bc-5175b4008f75"
# Projects
projects_database_id = "2ce207a3-926a-8025-98ce-d89e113211e8"
projects_data_source_id = "2ce207a3-926a-80ba-b4c7-000b21d1ed60"
# Systems
systems_database_id = "0c27f2ee-7480-4d8d-a620-ab729a5b3e0c"
systems_data_source_id = "b9018ec6-e829-4686-bd1d-55b455fd6baf"
```

### Issue 4: Update pipeline with routing flow (`src/pipeline.py`)

**File:** `src/pipeline.py`
**Lines:** Modify `_process_text_internal` (line 141)

**Current flow:** transcribe -> classify -> dedup (inbox+content only) -> notion (inbox only) -> refine -> template

**New flow:** transcribe -> clean (if voice) -> **route** -> **dedup (target DB)** -> **create/append (target DB)** -> **link back (update inbox)**

Key changes:
- Replace `self.classifier.classify()` with `self.classifier.route()` returning `RoutingResult`
- Dedup now searches the TARGET database (not just inbox + content objects)
- Create step writes to the target database using `notion.create_in_database(routing_result.target_database, ...)`
- After creating in target DB, update Inbox item: set Status="Processed", add relation to new page
- Refine + template stages only trigger for `content_objects` target (not for atomic ideas, systems, or projects)

### Issue 5: Update batch processor with routing (`scripts/process_inbox.py`)

**File:** `scripts/process_inbox.py`
**Lines:** Modify `classify` command (line 34)

**What changes:**
- `classify` command now calls the routing classifier instead of the simple classifier
- Dry-run output shows: `[ROUTE] "item title" -> atomic_ideas (Category: Raw, Tags: [x, y])`
- Actually runs: creates item in target DB, updates inbox status
- Add `--target` filter to only process items that would route to a specific DB

### Issue 6: Add inbox watcher (`scripts/watch_inbox.py`)

**File:** `scripts/watch_inbox.py` (NEW)
**Lines:** New file, ~100 lines

**What it does:**
- Polls Notion Inbox for Status=New every 60s
- For each new item: read content -> route -> dedup -> create/append -> link back
- Tracks processed page IDs in `.watch-state.json` to avoid re-processing
- Logs each routing decision with timestamp
- Graceful shutdown on SIGINT/SIGTERM
- Click CLI: `python scripts/watch_inbox.py [--interval 60] [--state-file .watch-state.json] [--dry-run]`

Pattern reference: `scripts/watch_folder.py` already exists (line 1-172) and uses a similar file-based state tracking pattern. Reuse the logging and graceful shutdown patterns from there.

### Issue 7: OCR endpoint in notion-pipeline (separate repo)

**Repo:** `/Users/nick/Downloads/notion-pipeline`
**File:** `src/api/routes/notion.py` (add new endpoint)

**What changes:** Add `POST /ocr` endpoint that accepts image bytes (multipart) and returns `{ text: string }`. Reuses the existing Gemini 2.5 Flash call from `notion_ingest.py:194-229` but without the Notion write or LLM cleanup.

This is a separate service -- voice-to-notion calls it over HTTP when the Telegram bot receives an image.

### Issue 8: Telegram bot reply-chain + OCR (separate repo)

**Repo:** `/Users/nick/Downloads/voice-to-notion`
**File:** `src/telegram-bot.js` (extend WIP)

**What changes:**
- Commit existing WIP (10 uncommitted files)
- Add reply-chain state tracking (pending sources by chat_id + message_id)
- When image received: call notion-pipeline `/ocr` endpoint
- When reply with voice to tracked source: pair into single Notion page with Source + My Take sections
- 30min timeout for unpaired sources -> create source-only page

## Unit Tests Required

**Location:** `tests/` (existing directory)

### test_classify.py (extend)

| Test | Description |
|------|-------------|
| `test_routing_result_fields` | Verify RoutingResult has all required fields with correct defaults |
| `test_route_standalone_insight` | Mock Claude to return atomic_ideas target for a philosophical observation |
| `test_route_content_idea` | Mock Claude to return content_objects for "I should write about X" |
| `test_route_system_process` | Mock Claude to return systems for "repeatable workflow for X" |
| `test_route_project_task` | Mock Claude to return projects for "I need to build X by Friday" |
| `test_route_unclear_defaults_atomic` | Mock ambiguous text -> defaults to atomic_ideas |
| `test_route_malformed_json_fallback` | Claude returns garbage -> graceful fallback RoutingResult |
| `test_route_with_db_specific_properties` | Content Objects route includes content_type and platform |

### test_notion_schema.py (new)

| Test | Description |
|------|-------------|
| `test_atomic_idea_to_notion_properties` | Verify AtomicIdeaItem.to_notion_properties() produces valid Notion format |
| `test_project_to_notion_properties` | Verify ProjectItem.to_notion_properties() with all fields |
| `test_system_to_notion_properties` | Verify SystemItem.to_notion_properties() with category and summary |
| `test_properties_handle_empty_optionals` | None fields don't produce Notion errors |

### test_notion_client.py (new)

| Test | Description |
|------|-------------|
| `test_create_in_database_routes_correctly` | Mock Notion API, verify correct database_id used per target |
| `test_search_database_atomic_ideas` | Verify query builds correct filter for Atomic Ideas DB |
| `test_search_database_systems` | Verify query builds correct filter for Systems DB |

### test_pipeline.py (extend)

| Test | Description |
|------|-------------|
| `test_full_routing_flow` | Mock all stages, verify route -> dedup -> create -> link back |
| `test_route_to_atomic_ideas_creates_correctly` | End-to-end with mocked APIs for atomic ideas path |
| `test_route_to_content_objects_triggers_refine` | Content objects path optionally triggers refine stage |
| `test_route_to_projects_skips_refine` | Projects path does NOT trigger refine/template |
| `test_dedup_searches_target_db` | Verify dedup searches the routed target DB, not just inbox |

### Mocking Strategy

```python
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_claude():
    with patch("src.classify.anthropic.Anthropic") as mock:
        client = MagicMock()
        mock.return_value = client
        # Set up default routing response
        response = MagicMock()
        response.content = [MagicMock(text='{"target_database": "atomic_ideas", "title": "Test", "summary": "Test idea", "tags": ["test"]}')]
        client.messages.create.return_value = response
        yield client

@pytest.fixture
def mock_notion():
    with patch("src.notion_client.Client") as mock:
        client = MagicMock()
        mock.return_value = client
        client.pages.create.return_value = {"id": "test-page-id", "url": "https://notion.so/test"}
        yield client
```

## Environment Variables

```bash
# Already in .env (no changes needed):
NOTION_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...

# No new env vars -- new database IDs are hardcoded in settings.py
# (same pattern as existing inbox_database_id and content_objects_database_id)
```

## Files to Modify

| File | Change |
|------|--------|
| `config/settings.py` | Add 6 new database/data-source IDs for Atomic Ideas, Projects, Systems |
| `config/notion_schema.py` | Add `AtomicIdeaItem`, `ProjectItem`, `SystemItem` dataclasses |
| `src/classify.py` | Replace `ClassificationResult` with `RoutingResult`, rewrite system prompt |
| `src/notion_client.py` | Add create/query methods for 3 new databases + generic router |
| `src/pipeline.py` | Replace classify stage with route stage, update dedup + create logic |
| `scripts/process_inbox.py` | Update `classify` command to use routing, add `--target` filter |
| `scripts/watch_inbox.py` | **NEW** -- inbox polling watcher |
| `tests/test_classify.py` | Extend with routing tests |
| `tests/test_notion_schema.py` | **NEW** -- schema model tests |
| `tests/test_notion_client.py` | **NEW** -- multi-DB client tests |
| `tests/test_pipeline.py` | Extend with routing flow tests |

## Acceptance Criteria

- [ ] Routing classifier correctly identifies target DB for: insights, content ideas, systems, projects
- [ ] Notion client can create pages in all 4 target databases
- [ ] Pipeline flow: route -> dedup (target DB) -> create/append -> link back to inbox
- [ ] Batch processor shows routing decisions in dry-run mode
- [ ] Inbox watcher auto-triages new items within 60s
- [ ] Dedup searches the target database (not just inbox)
- [ ] Inbox status updated to "Processed" after successful routing
- [ ] All unit tests passing
- [ ] No regressions in existing tests

## Verification Steps

1. `cd /Users/nick/Documents/cognosmap-automation`
2. `python -m pytest tests/ -v` -- all tests pass
3. `python scripts/process_inbox.py stats` -- see current inbox counts
4. `python scripts/process_inbox.py classify --dry-run --limit 5` -- verify routing decisions look correct
5. `python scripts/process_inbox.py classify --limit 3` -- actually route 3 items, check Notion
6. `python scripts/watch_inbox.py --dry-run --interval 10` -- test watcher with 10s polling
7. Create a test Inbox page manually in Notion -> verify watcher picks it up and routes it

## Issue Breakdown for GitHub

| # | Title | Scope | Dependencies |
|---|-------|-------|-------------|
| 1 | Routing classifier | `classify.py` rewrite | None |
| 2 | Schema models for 3 new DBs | `notion_schema.py`, `settings.py` | None |
| 3 | Multi-DB Notion client | `notion_client.py` | Issue 2 |
| 4 | Pipeline routing flow | `pipeline.py` | Issues 1, 3 |
| 5 | Batch processor routing | `process_inbox.py` | Issue 4 |
| 6 | Inbox watcher | `watch_inbox.py` (new) | Issue 4 |
| 7 | OCR endpoint (notion-pipeline) | Separate repo | None |
| 8 | Telegram reply-chain + OCR | Separate repo | Issue 7 |

Issues 1 and 2 can be done in parallel (no deps). Issues 7 and 8 are in separate repos and independent of 1-6.

## Key File Paths (seeker-automations)

| What | Where |
|------|-------|
| Classifier | `/Users/nick/Documents/cognosmap-automation/src/classify.py` |
| Notion client | `/Users/nick/Documents/cognosmap-automation/src/notion_client.py` |
| Pipeline | `/Users/nick/Documents/cognosmap-automation/src/pipeline.py` |
| Deduplicator | `/Users/nick/Documents/cognosmap-automation/src/dedupe.py` |
| Transcript cleaner | `/Users/nick/Documents/cognosmap-automation/src/clean.py` |
| Schema models | `/Users/nick/Documents/cognosmap-automation/config/notion_schema.py` |
| Settings | `/Users/nick/Documents/cognosmap-automation/config/settings.py` |
| Batch processor | `/Users/nick/Documents/cognosmap-automation/scripts/process_inbox.py` |
| File watcher (pattern ref) | `/Users/nick/Documents/cognosmap-automation/scripts/watch_folder.py` |
| Tests | `/Users/nick/Documents/cognosmap-automation/tests/` |
