# CognosMap Automation - Implementation Plan

## Overview

This document outlines the implementation plan for the CognosMap content automation system. The goal is to automate the flow from raw voice notes/ideas to structured, publishable content in Notion.

---

## Current State Analysis

### Notion Databases

| Database | ID | Purpose | Current Issues |
|----------|-----|---------|----------------|
| **Inbox** | `2c0eba0cabd545d0a7606549cd0f3c84` | Raw captures, voice notes | 50+ items stuck at "New" status, no classification |
| **Content Objects** | `db6f21b8b26147119ae0b920861ec3c0` | Refined content for production | Manual promotion from Inbox |

### Identified Gaps

1. **No auto-classification** - All inbox items remain "New"
2. **No deduplication** - Similar ideas aren't merged
3. **No refinement pipeline** - Raw → Structured is manual
4. **No platform templating** - Each platform formatted manually
5. **Voice → Text is working** - Whisper transcription exists but classification doesn't follow

---

## Solution Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        COGNOSMAP AUTOMATION PIPELINE                         │
└─────────────────────────────────────────────────────────────────────────────┘

   INPUTS                    PROCESSING                      OUTPUTS
   ──────                    ──────────                      ───────

   Voice Memo     ──►  ┌─────────────┐
   (m4a/mp3)          │ TRANSCRIBE  │
                      │ (Whisper)   │
                      └──────┬──────┘
                             │
   Text Input    ────────────┤
                             │
                             ▼
                      ┌─────────────┐
                      │  CLASSIFY   │  ──► Type, Priority, Category, Tags
                      │  (Claude)   │
                      └──────┬──────┘
                             │
                             ▼
                      ┌─────────────┐
                      │   DEDUPE    │  ──► Check for similar existing content
                      │ (Embeddings)│
                      └──────┬──────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
       CREATE NEW                    APPEND TO EXISTING
              │                             │
              └──────────────┬──────────────┘
                             │
                             ▼
                      ┌─────────────┐
                      │   NOTION    │  ──► Inbox Database
                      │   INBOX     │
                      └──────┬──────┘
                             │
                             ▼ (Optional / Manual Trigger)
                      ┌─────────────┐
                      │   REFINE    │  ──► Structured Hypertext
                      │  (Claude)   │
                      └──────┬──────┘
                             │
                             ▼
                      ┌─────────────┐
                      │  TEMPLATE   │  ──► Platform-specific outputs
                      │   ENGINE    │
                      └──────┬──────┘
                             │
              ┌──────────────┼──────────────┬──────────────┐
              ▼              ▼              ▼              ▼
          Twitter       LinkedIn       Substack        Video
          Thread         Post          Essay          Script
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)
**Status: ✅ COMPLETE**

- [x] Project structure setup
- [x] Configuration management (settings, schema)
- [x] Transcription module (Whisper API)
- [x] Classification module (Claude)
- [x] Deduplication module (embeddings)
- [x] Notion client (API wrapper)
- [x] Pipeline orchestrator
- [x] CLI interface

### Phase 2: Testing & Validation (Week 2)
**Status: 🔲 TODO**

- [ ] Set up API keys in `.env`
- [ ] Test Notion connection
- [ ] Test classification on sample content
- [ ] Test deduplication accuracy
- [ ] Validate end-to-end pipeline
- [ ] Process 10 existing inbox items manually

**Validation Checklist:**
```bash
# 1. Check configuration
python scripts/cli.py check

# 2. List current inbox items
python scripts/cli.py inbox --status New --limit 5

# 3. Process a single text input
python scripts/cli.py process "Your test idea here"

# 4. Process a voice memo
python scripts/cli.py process --voice /path/to/memo.m4a
```

### Phase 3: Bulk Processing (Week 3)
**Status: 🔲 TODO**

- [ ] Classify all "New" inbox items
- [ ] Review classification accuracy
- [ ] Tune classification prompts if needed
- [ ] Set up automated processing

**Bulk Processing Commands:**
```bash
# Classify all new items (dry run first)
python scripts/process_inbox.py classify --status New --limit 50 --dry-run
python scripts/process_inbox.py classify --status New --limit 50

# Check stats
python scripts/process_inbox.py stats
```

### Phase 4: Refinement Integration (Week 4)
**Status: 🔲 TODO**

- [ ] Test refinement on triaged items
- [ ] Validate hypertext structure quality
- [ ] Generate sample platform outputs
- [ ] Integrate with Content Objects promotion

**Refinement Commands:**
```bash
# Refine triaged items
python scripts/process_inbox.py refine --status Triaged --limit 5 --output ./refined/

# Promote to Content Objects
python scripts/process_inbox.py promote --limit 5 --dry-run
```

### Phase 5: Automation (Week 5+)
**Status: 🔲 TODO**

- [ ] Set up cron jobs for periodic processing
- [ ] Configure voice memo folder watcher
- [ ] Monitor and tune thresholds
- [ ] Document operational procedures

---

## API Keys Required

| Service | Purpose | Get Key From |
|---------|---------|--------------|
| **Notion** | Database access | https://www.notion.so/my-integrations |
| **Anthropic** | Classification & Refinement | https://console.anthropic.com/ |
| **OpenAI** | Embeddings & Whisper | https://platform.openai.com/api-keys |

### Notion Setup Steps

1. Go to https://www.notion.so/my-integrations
2. Create new integration: "CognosMap Automation"
3. Copy the "Internal Integration Token"
4. Share both databases with the integration:
   - Open Inbox database → Share → Invite → Select integration
   - Open Content Objects database → Share → Invite → Select integration

---

## Configuration

### Environment Variables (`.env`)

```bash
# Copy from .env.example and fill in:
NOTION_API_KEY=secret_xxx
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx

# Optional tuning
DEDUPE_THRESHOLD=0.85  # Higher = stricter matching
WHISPER_MODE=api       # "api" or "local"
```

### Notion Database IDs

Already configured in `config/settings.py`:
- Inbox: `2c0eba0cabd545d0a7606549cd0f3c84`
- Content Objects: `db6f21b8b26147119ae0b920861ec3c0`

---

## Usage Patterns

### Daily Workflow

1. **Morning**: Review overnight voice memo processing
   ```bash
   python scripts/cli.py inbox --status New
   ```

2. **Midday**: Classify and triage
   ```bash
   python scripts/process_inbox.py classify --status New
   ```

3. **Afternoon**: Refine and prepare content
   ```bash
   python scripts/process_inbox.py refine --status Triaged --output ./today/
   ```

### Quick Capture

```bash
# Text idea
python scripts/cli.py process "Your idea here"

# Voice memo
python scripts/cli.py process --voice ~/Downloads/memo.m4a

# With immediate refinement
python scripts/cli.py process "Your idea" --refine --platforms twitter linkedin
```

### Bulk Operations

```bash
# Process all new items
python scripts/process_inbox.py classify --status New --limit 100

# Promote ready items to Content Objects
python scripts/process_inbox.py promote --status "Ready to Write" --limit 10

# View statistics
python scripts/process_inbox.py stats
```

---

## Monitoring & Maintenance

### Key Metrics to Track

1. **Classification Accuracy**: Review samples weekly
2. **Deduplication Rate**: Should be 10-20% (not too high, not too low)
3. **Processing Time**: Should be <30s per item
4. **Error Rate**: Should be <5%

### Log Files (when cron is enabled)

```
logs/
├── voice_memo.log    # Voice memo processing
├── classify.log      # Classification runs
├── refine.log        # Refinement runs
├── promote.log       # Promotion to Content Objects
└── daily_stats.log   # Daily statistics
```

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Classification too generic | Tune the classification prompt in `classify.py` |
| Too many duplicates detected | Lower `DEDUPE_THRESHOLD` |
| Too few duplicates detected | Raise `DEDUPE_THRESHOLD` |
| Notion API rate limits | Add delays between requests |
| Whisper transcription errors | Try local Whisper model |

---

## File Structure

```
cognosmap-automation/
├── README.md                    # Quick start guide
├── IMPLEMENTATION_PLAN.md       # This document
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment template
├── config/
│   ├── __init__.py
│   ├── settings.py              # Configuration & API keys
│   └── notion_schema.py         # Notion property mappings
├── src/
│   ├── __init__.py
│   ├── transcribe.py            # Whisper integration
│   ├── classify.py              # Claude classification
│   ├── dedupe.py                # Embedding similarity
│   ├── notion_client.py         # Notion API wrapper
│   ├── refine.py                # Content refinement
│   ├── templates.py             # Platform formatters
│   └── pipeline.py              # Main orchestrator
├── scripts/
│   ├── cli.py                   # Command-line interface
│   ├── watch_folder.py          # Voice memo watcher
│   └── process_inbox.py         # Bulk inbox processing
├── cron/
│   └── crontab.txt              # Scheduled jobs
└── tests/
    ├── __init__.py
    ├── test_classify.py
    ├── test_dedupe.py
    └── test_pipeline.py
```

---

## Next Steps

1. **Today**:
   - Copy project to your machine
   - Set up `.env` with API keys
   - Run `python scripts/cli.py check` to verify setup

2. **This Week**:
   - Process 5-10 inbox items manually to validate
   - Tune classification if needed
   - Start folder watcher for voice memos

3. **Next Week**:
   - Enable cron jobs for automation
   - Set up monitoring
   - Iterate on refinement quality

---

## Support

For issues or questions:
- Check logs in `logs/` directory
- Run `python scripts/cli.py check` to validate configuration
- Review test files for expected behavior
