# CognosMap Automation -- Architecture Analysis

## Executive Summary

The cognosmap-automation codebase is a well-structured personal content pipeline with clear separation of concerns across ~1,600 lines of application code. The architecture follows a linear pipeline pattern with optional late stages, orchestrated by a central `Pipeline` class. The codebase is functional and coherent for its current scale but has several areas worth noting:

**Strengths:**
- Clean dataclass-based contracts between stages (ClassificationResult, DedupeResult, RefinedContent, etc.)
- Good fallback handling -- every Claude JSON parse has a graceful degradation path
- The autolink candidate selection algorithm is well-designed with a multi-signal scoring approach
- Comprehensive test coverage for the autolink module specifically

**Areas for improvement:**
- Hardcoded Notion database IDs in `config/settings.py` (should be env vars)
- The `.env` file is checked into git with live API keys (critical security issue -- the `.gitignore` lists `.env` but the file exists in the repo)
- No test coverage for `refine.py`, `templates.py`, `clean.py`, `notion_client.py`, or any scripts
- Synchronous API calls throughout -- batch processing could benefit from async
- JSON response parsing from Claude is duplicated across 4 modules (classify, refine, autolink, suggest_wikilinks)

---

## Detailed Analysis

### Security: API Keys in Version Control

[settings.py](config/settings.py) (Line 27-31): Notion database IDs are hardcoded rather than loaded from `.env`.

The `.env` file contains live API keys for Notion, Anthropic, OpenAI, Gemini, and Obsidian REST API. While `.gitignore` lists `.env`, the file is present in the git repository (confirmed by `git status` showing a clean working tree with the file present). If this repo has ever been pushed to a remote, all keys should be rotated immediately.

**Recommendation:** Verify with `git log --all --full-history -- .env` whether the file was ever committed. If so, rotate all keys. Move the four database/data-source IDs to `.env` as well.

### Duplicated JSON Parsing Pattern

The following pattern appears in 4 places with minor variations:

```python
response_text = response.content[0].text
if "```json" in response_text:
    response_text = response_text.split("```json")[1].split("```")[0]
elif "```" in response_text:
    response_text = response_text.split("```")[1].split("```")[0]
try:
    data = json.loads(response_text.strip())
except json.JSONDecodeError as e:
    # fallback
```

Locations:
- [classify.py](src/classify.py) (Line 134-141)
- [refine.py](src/refine.py) (Line 132-139)
- [autolink.py](src/autolink.py) (Line 225-235)

A shared utility function would reduce this to a single call site and make error handling consistent.

### Pipeline Orchestrator Design

[pipeline.py](src/pipeline.py) (Line 46-265): The `Pipeline` class instantiates all components in `__init__` regardless of which stages will be used. For example, constructing a `Pipeline` to only run `refine_existing` still creates a `Transcriber`, `Deduplicator`, etc. This is not a problem at current scale but would matter if components had expensive initialization (e.g., loading a local Whisper model).

The autolink stage (Stage 7) uses a lazy import inside the method body, which is a good pattern for optional dependencies.

### Notion Client: Dual ID System

[notion_client.py](src/notion_client.py) (Line 33-35): The 2025 Notion API split between `data_source_id` (for queries) and `database_id` (for creation) is handled correctly but is a potential confusion point. The IDs are documented in settings.py comments but could benefit from a validation check at startup.

The `check_against_notion` method (Line 144-176) in `dedupe.py` is declared `async` but the `NotionClient` it calls uses the synchronous `Client` by default. This method would fail if called without the `async_mode=True` client.

### Autolink: Graph Traversal Scoring

[autolink.py](src/autolink.py) (Line 121-179): The four-step candidate scoring is well-designed:
1. Title scan (+3) catches direct references
2. Tag overlap (+N) catches thematic relations
3. Graph walk (+2) catches structural neighbors
4. Backlink fan-in (+1) catches convergence hubs

One edge case: Step 4 iterates over `list(scores.keys())` while potentially adding new keys to `scores` inside the loop. This works because `list()` creates a snapshot, but the intent could be clearer.

### Template Engine: Unused Import

[templates.py](src/templates.py) (Line 147-148): The `format_substack` method imports `Refiner` and calls `to_markdown()`, but then builds its own markdown from scratch without using the result. The `markdown` variable is assigned but never referenced.

### Test Coverage Gaps

Tests exist for: autolink, classify, dedupe, pipeline. Tests are missing for:
- `refine.py` -- No tests for the refinement logic or markdown generation
- `templates.py` -- No tests for any platform formatter
- `clean.py` -- No tests for transcript cleaning
- `notion_client.py` -- No tests (reasonable given API dependency, but property mapping could be tested)
- `merge_vaults.py` -- No tests for vault merging (filesystem operations)

The existing tests are well-structured with proper mocking and cover the most complex logic (autolink candidate selection, wikilink insertion, cosine similarity math).

---

## Comprehensive Summary

The codebase is a focused, single-purpose automation tool that does its job well for personal use. The linear pipeline architecture is appropriate for the problem -- there are no complex branching workflows or concurrent processing needs that would justify more sophisticated orchestration.

The most impactful improvements would be:
1. Removing API keys from version control (security)
2. Extracting the duplicated JSON parsing into a shared utility
3. Adding tests for refine.py and templates.py (the two modules with the most complex output formatting)
4. Moving hardcoded Notion IDs to environment variables

The autolink module is the most sophisticated component and is also the best-tested, which is appropriate given its complexity.
