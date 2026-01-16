# CognosMap Automation Pipeline

A Python automation system for processing voice notes and raw ideas into structured content in Notion.

## Overview

This pipeline automates the CognosMap Creation Flow:
1. **Transcribe** - Convert voice memos to text (Whisper)
2. **Classify** - Determine type, priority, category, tags (Claude)
3. **Dedupe** - Check for similar existing ideas (embeddings)
4. **Create/Update** - Add to Notion Inbox or append to existing
5. **Refine** - Transform raw → structured hypertext (optional)
6. **Template** - Format for specific platforms (optional)

## Architecture

```
Voice/Text Input
       │
       ▼
┌──────────────┐
│  Transcribe  │ (Whisper API/local)
└──────┬───────┘
       ▼
┌──────────────┐
│   Classify   │ (Claude API)
└──────┬───────┘
       ▼
┌──────────────┐
│    Dedupe    │ (Embeddings + Notion query)
└──────┬───────┘
       ▼
┌──────────────┐
│ Notion Inbox │ (Create or append)
└──────────────┘
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Required API Keys

- `NOTION_API_KEY` - Notion integration token
- `ANTHROPIC_API_KEY` - Claude API key
- `OPENAI_API_KEY` - For embeddings (or use Voyage)

### 4. Notion Setup

1. Create a Notion integration at https://www.notion.so/my-integrations
2. Share your Inbox and Content Objects databases with the integration
3. Database IDs are pre-configured in `config/settings.py`

## Usage

### Manual input via CLI

```bash
python scripts/cli.py "Your raw idea or thought here"
python scripts/cli.py --voice /path/to/voice-memo.m4a
```

### Watch folder for voice memos

```bash
python scripts/watch_folder.py /path/to/voice-memos/
```

### Process existing Inbox items

```bash
python scripts/process_inbox.py --status New --limit 10
```

### Cron jobs

Add to crontab for automated processing:
```bash
crontab cron/crontab.txt
```

## Notion Database Schema

### Inbox Database
- Title, Date Added, Status, Tags, Type, Project, URL

### Content Objects Database
- Name, Category, Content Type, Status, Tags, Atomic Ideas, Main Idea, Platform

## Configuration

Edit `config/settings.py` to customize:
- Classification categories and types
- Deduplication similarity threshold
- Default status values
- Template formats

## License

Private - Nicholas Grijalva
