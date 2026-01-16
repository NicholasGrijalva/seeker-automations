# CognosMap Automation Pipeline

A Python automation system that transforms voice memos and raw ideas into structured content in Notion, with intelligent classification, deduplication, and multi-platform output generation.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Pipeline Stages](#pipeline-stages)
7. [Notion Database Schema](#notion-database-schema)
8. [Platform Templates](#platform-templates)
9. [Transcript Cleaning](#transcript-cleaning)
10. [Automation Options](#automation-options)
11. [Troubleshooting](#troubleshooting)

---

## Overview

This pipeline automates the CognosMap Creation Flow - converting raw voice memos and typed ideas into structured, searchable content in Notion.

```
                     INPUT SOURCES
                          |
        +-----------------+-----------------+
        |                 |                 |
   Voice Memo         Raw Text          Clipboard
   (m4a/mp3)          (txt/md)          (stdin)
        |                 |                 |
        +-----------------+-----------------+
                          |
                          v
              +-------------------+
              |  1. TRANSCRIBE    |  Whisper API or local model
              +--------+----------+
                       |
                       v
              +-------------------+
              |  2. CLASSIFY      |  Claude determines:
              |  - Type           |  Essay/Video/Post/Proself
              |  - Priority       |  Active/Essential/Backlog
              |  - Category       |  AI, Philosophy, etc.
              |  - Tags           |  Auto-extracted topics
              +--------+----------+
                       |
                       v
              +-------------------+
              |  3. DEDUPE        |  Embeddings check against
              |                   |  existing Notion content
              +--------+----------+
                       |
           +-----------+-----------+
           |                       |
      DUPLICATE?              NEW IDEA
           |                       |
           v                       v
      APPEND TO               CREATE NEW
      EXISTING                NOTION PAGE
           |                       |
           +-----------+-----------+
                       |
                       v
              +-------------------+
              |  4. REFINE        |  (Optional) Transform to
              |                   |  structured hypertext
              +--------+----------+
                       |
                       v
              +-------------------+
              |  5. TEMPLATE      |  (Optional) Format for
              |                   |  Twitter/LinkedIn/etc.
              +-------------------+
```

---

## Architecture

### Core Modules

| Module | Tech | Purpose |
|--------|------|---------|
| `transcribe.py` | Whisper (API/local) | Voice memo to text |
| `classify.py` | Claude API | Determine type, priority, category, tags |
| `dedupe.py` | OpenAI Embeddings | Check if idea already exists |
| `notion_client.py` | notion-client | CRUD with Notion databases |
| `refine.py` | Claude API | Raw text to structured hypertext |
| `templates.py` | Custom formatters | Platform-specific outputs |
| `pipeline.py` | Orchestrator | Coordinates all stages |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/cli.py` | Main command-line interface |
| `scripts/watch_folder.py` | Monitor folder for new voice memos |
| `scripts/process_inbox.py` | Batch process existing Notion items |

---

## Installation

### Prerequisites

- Python 3.10+
- Notion account with API integration
- API keys for: Notion, Anthropic (Claude), OpenAI

### Quick Setup

```bash
cd ~/Documents/cognosmap-automation
./setup.sh
```

### Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Verify Installation

```bash
source venv/bin/activate
python scripts/cli.py check
```

Expected output:
```
Checking configuration...

[OK] All API keys configured

Testing Notion connection...
[OK] Inbox database connected
[OK] Content Objects database connected

Testing Claude connection...
[OK] Anthropic client configured

Testing OpenAI connection...
[OK] OpenAI client configured
```

---

## Configuration

### Environment Variables (.env)

```bash
# Required API Keys
NOTION_API_KEY=ntn_xxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxx

# Optional: Better embeddings
VOYAGE_API_KEY=voyage-xxxxxxxxxxxxxxxxxxxxx

# Whisper Settings
WHISPER_MODE=api          # "api" (OpenAI) or "local" (whisper model)
WHISPER_MODEL=whisper-1   # For API mode
# WHISPER_MODEL=base      # For local: tiny, base, small, medium, large

# Deduplication
DEDUPE_THRESHOLD=0.85     # 0.0-1.0, higher = stricter matching

# Automation
VOICE_MEMO_FOLDER=/Users/nick/voice-memos

# Logging
LOG_LEVEL=INFO
```

### Notion Setup

1. Create an integration at https://www.notion.so/my-integrations
2. Copy the "Internal Integration Token" to `NOTION_API_KEY`
3. Share your databases with the integration:
   - Open each database in Notion
   - Click `...` menu > "Connections" > Add your integration
4. Database IDs are configured in `config/settings.py`

**Important (Notion 2025 API):** The code handles two ID formats automatically:
- `data_source_id` - for querying (new 2025 format)
- `database_id` - for page creation (legacy format)

### Classification Options

Edit `config/settings.py` to customize:

```python
# Content Types
content_types = ["Essay", "Video", "Post", "Proself"]

# Priority Levels
priority_levels = ["Active", "Essential", "Backlog"]

# Categories
categories = [
    "AI/Technology",
    "Philosophy/Spirituality",
    "Leadership/Business",
    "Personal Development",
    "Content Strategy",
    "Relationships",
    "Health/Fitness",
    "Other"
]
```

---

## Usage

### Command Line Interface

```bash
# Activate environment
cd ~/Documents/cognosmap-automation
source venv/bin/activate

# Show all commands
python scripts/cli.py --help
```

### Process Text

```bash
# Basic - just process and add to Notion
python scripts/cli.py process "Your idea or thought here"

# From clipboard/stdin
echo "Your idea" | python scripts/cli.py process

# Multi-line input
python scripts/cli.py process
# Then type your content, press Ctrl+D when done
```

### Process Voice Memo

```bash
python scripts/cli.py process --voice /path/to/recording.m4a
```

### With Refinement + Platform Outputs

```bash
# Refine and generate Twitter thread
python scripts/cli.py process "Your idea" --refine --platforms twitter

# Multiple platforms
python scripts/cli.py process "Your idea" -r -p twitter -p linkedin -p substack
```

### View Notion Databases

```bash
# List inbox items
python scripts/cli.py inbox --status New --limit 20

# List content objects
python scripts/cli.py content --limit 10
```

### Refine Existing Page

```bash
# Get page ID from Notion URL
python scripts/cli.py refine "page-id-here" --platforms twitter,linkedin
```

### Check Configuration

```bash
python scripts/cli.py check
```

---

## Pipeline Stages

### Stage 1: Transcribe

**Module:** `src/transcribe.py`

Converts voice memos to text using OpenAI Whisper.

- **API Mode** (default): Uses OpenAI's Whisper API
- **Local Mode**: Runs whisper model locally (requires more setup)

Supports: `.m4a`, `.mp3`, `.wav`, `.webm`, `.mp4`, `.mpeg`, `.mpga`, `.oga`, `.ogg`

### Stage 2: Classify

**Module:** `src/classify.py`

Uses Claude to analyze content and extract:

| Field | Description |
|-------|-------------|
| `title` | Compelling, descriptive title |
| `content_type` | Essay, Video, Post, or Proself |
| `priority` | Active (urgent), Essential (soon), Backlog (later) |
| `category` | Best-fit category from predefined list |
| `tags` | 2-5 specific topic tags |
| `main_idea` | 1-2 sentence summary |
| `atomic_ideas` | Standalone insights that could be separate posts |
| `suggested_platforms` | Recommended platforms for this content |
| `related_concepts` | Concepts to link to other ideas |

### Stage 3: Dedupe

**Module:** `src/dedupe.py`

Checks for similar existing content using embeddings:

1. Generates embedding for new content (OpenAI `text-embedding-3-small`)
2. Queries recent items from Notion Inbox and Content Objects
3. Computes cosine similarity against existing items
4. Returns recommendation:

| Score | Recommendation | Action |
|-------|----------------|--------|
| >= 0.95 | `skip` | Nearly identical, don't create |
| >= threshold | `append_to` | Add to existing page |
| >= threshold * 0.8 | `review` | Human should decide |
| < threshold * 0.8 | `create_new` | Create new page |

Default threshold: `0.85` (configurable via `DEDUPE_THRESHOLD`)

### Stage 4: Notion

**Module:** `src/notion_client.py`

Creates or updates Notion pages:

- **New ideas**: Creates page in Inbox database
- **Duplicates**: Appends content to existing page with timestamp
- **Page body**: Includes raw transcript in collapsible section

### Stage 5: Refine (Optional)

**Module:** `src/refine.py`

Transforms raw content into structured hypertext:

```
"Digital aphorisms linked to longer meditations"
"A constellation, not a monolith"
```

Output structure:
- **Core Aphorism**: Single tweetable insight (< 280 chars)
- **Fragments**: Typed content pieces
  - `core_claim` - Main arguments
  - `supporting` - Evidence and elaboration
  - `example` - Concrete examples
  - `source` - Citations and references
  - `counter` - Steelmanned opposing views
- **Linked Concepts**: Terms that should hyperlink to other ideas
- **Suggested Connections**: Related ideas to explore

### Stage 6: Template (Optional)

**Module:** `src/templates.py`

Formats refined content for specific platforms.

---

## Notion Database Schema

### Inbox Database

| Property | Type | Description |
|----------|------|-------------|
| Title | Title | Item title |
| Date Added | Date | Auto-populated |
| Status | Select | New, Triaged, Processed, Ready to Write |
| Tags | Multi-select | Topic tags |
| Type | Select | Essay, Video, Post, Proself |
| Project | Select | Optional project assignment |
| URL | URL | Source URL if applicable |

### Content Objects Database

| Property | Type | Description |
|----------|------|-------------|
| Name | Title | Content piece name |
| Category | Select | Content category |
| Content Type | Select | Essay, Video, Post, Proself |
| Status | Select | Backlog, To-Do, Planning, Draft, Published |
| Date Created | Date | Auto-populated |
| Tags | Multi-select | Topic tags |
| Main Idea | Rich Text | Core insight summary |
| Platform | Multi-select | Target platforms |
| Target Publish Date | Date | Optional deadline |

---

## Platform Templates

### Twitter Thread

```
1/n

[Core aphorism - the hook]

---

2/n

[Core claims and supporting points as individual tweets]

---

n/n

That's the thread.

If this resonated, follow for more on [topic].
```

Metadata: Tweet count, total characters

### LinkedIn Post

```
[Core aphorism - hook line]

[Key claims expanded]

-> Supporting point 1
-> Supporting point 2
-> Supporting point 3

The key insight: [structure notes]

---

What's your take? Let me know in the comments.

#hashtag1 #hashtag2
```

Metadata: Character count, hashtag count

### Substack Essay

Full markdown essay with:
- Title and pull quote
- "The Insight" section (core claims)
- "Going Deeper" section (supporting points)
- Examples section
- "The Other Side" (counter-arguments)
- "The Takeaway" (conclusion)
- Related ideas

Metadata: Word count, section count

### Video Script

Timestamped segments:
- **HOOK** (0:00-0:15): Core aphorism, direct to camera
- **PROBLEM** (0:15-1:00): Establish the problem
- **POINT 1-3** (1:00-2:30): Main content with B-roll suggestions
- **EXAMPLE** (2:30-3:00): Concrete example
- **CTA** (3:00-3:15): Subscribe call-to-action

Metadata: Duration, segment count

---

## Transcript Cleaning

A dedicated feature for cleaning voice transcripts that come from external transcription services (e.g., auto-transcription tools). This preserves your original wording while removing verbal tics and formatting into readable paragraphs.

### What It Does

- **Removes filler words**: um, uh, like, you know, so, basically, actually, literally, right, I mean, kind of, sort of
- **Removes false starts**: "I I think" becomes "I think"
- **Formats into paragraphs**: Breaks wall-of-text into logical paragraphs based on topic shifts
- **Preserves your words**: Does NOT rephrase, summarize, or change meaning

### Usage

Tag-based processing - items tagged with `voice-transcript` get cleaned:

```bash
# Preview what would be cleaned (no changes made)
python scripts/process_inbox.py clean --tag voice-transcript --dry-run --limit 5

# Clean all tagged items
python scripts/process_inbox.py clean --tag voice-transcript --limit 10

# Use a different tag
python scripts/process_inbox.py clean --tag raw-transcript --limit 10
```

### Workflow Integration

```
External Transcription Service
         |
         v
Notion Inbox (tagged "voice-transcript")
         |
         v
python scripts/process_inbox.py clean --tag voice-transcript
         |
         v
Cleaned transcript (same words, formatted)
Status: New -> Triaged
         |
         v
Continue with classify/refine/etc.
```

### Example

**Before (raw transcript):**
```
so um like I was thinking you know that the biggest problem with knowledge work is actually um not about having access to information right its its about the synthesis step like we have infinite inputs but um basically finite attention and so the solution isnt better search you know its its about structuring what we already know
```

**After (cleaned):**
```
I was thinking that the biggest problem with knowledge work is not about having access to information. It's about the synthesis step.

We have infinite inputs but finite attention. So the solution isn't better search - it's about structuring what we already know.
```

### Configuration

In `config/settings.py`:

```python
# Default trigger tag
self.clean_trigger_tag = "voice-transcript"

# Filler words to remove
self.filler_words = [
    "um", "uh", "like", "you know", "so", "basically",
    "actually", "literally", "right", "i mean", "kind of", "sort of"
]
```

---

## Automation Options

### Folder Watcher

Monitor a folder for new voice memos:

```bash
python scripts/watch_folder.py /path/to/voice-memos/
```

Processes new files automatically as they appear.

### Cron Jobs

Add to crontab for scheduled processing:

```bash
# Edit crontab
crontab -e

# Add entries from cron/crontab.txt:
# Process inbox every hour
0 * * * * cd /path/to/cognosmap-automation && ./venv/bin/python scripts/process_inbox.py

# Watch for voice memos (runs as daemon)
@reboot cd /path/to/cognosmap-automation && ./venv/bin/python scripts/watch_folder.py ~/voice-memos/
```

### Batch Processing

Process existing Notion inbox items:

```bash
python scripts/process_inbox.py --status New --limit 10
```

---

## Troubleshooting

### "Could not find database" Error

1. Verify databases are shared with your integration in Notion
2. Check that IDs in `config/settings.py` match your workspace
3. Run `python scripts/cli.py check` to test connections

### Classification Returns Generic Results

- Ensure `ANTHROPIC_API_KEY` is valid
- Check that input text is substantial (very short inputs get generic results)
- Review logs: `LOG_LEVEL=DEBUG python scripts/cli.py process "test"`

### Deduplication Too Aggressive/Permissive

Adjust `DEDUPE_THRESHOLD` in `.env`:
- Higher (0.90-0.95): Stricter, fewer matches
- Lower (0.75-0.85): More permissive, more matches

### Voice Transcription Fails

- Verify `OPENAI_API_KEY` is valid
- Check file format is supported
- For large files, consider `WHISPER_MODE=local`

### Rate Limits

If hitting API rate limits:
- Add delays between batch processing
- Use local Whisper for transcription
- Consider caching embeddings

---

## Repository

**GitHub:** https://github.com/NicholasGrijalva/seeker-automations

---

## License

Private - Nicholas Grijalva
