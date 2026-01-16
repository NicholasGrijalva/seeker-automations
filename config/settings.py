"""
CognosMap Automation Settings

Central configuration for all pipeline components.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables (override=True to override existing empty vars)
load_dotenv(override=True)


class Settings:
    """Application settings loaded from environment."""

    def __init__(self):
        # API Keys - use override=True in load_dotenv AND check for empty strings
        self.notion_api_key = os.getenv("NOTION_API_KEY") or ""
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or ""
        self.openai_api_key = os.getenv("OPENAI_API_KEY") or ""
        self.voyage_api_key = os.getenv("VOYAGE_API_KEY", "")

        # Notion Data Source IDs (new API format as of 2025)
        # These are different from the database IDs shown in URLs
        self.inbox_database_id = "418b91e7-0c93-45b7-b905-c4715ab25964"
        self.content_objects_database_id = "15d28d70-ca5f-4183-b0fb-667af249ac20"

        # Whisper settings
        self.whisper_mode = os.getenv("WHISPER_MODE", "api")  # "api" or "local"
        self.whisper_model = os.getenv("WHISPER_MODEL", "whisper-1")

        # Deduplication
        self.dedupe_threshold = float(os.getenv("DEDUPE_THRESHOLD", "0.85"))

        # Voice memo folder
        self.voice_memo_folder = Path(os.getenv("VOICE_MEMO_FOLDER", "~/voice-memos")).expanduser()

        # Logging
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        # Classification options (aligned with your Notion schema)
        self.content_types = [
            "Essay",
            "Video",
            "Post",
            "Proself",  # Personal development
        ]

        self.status_options = {
            "inbox": ["New", "Triaged", "Processed", "Ready to Write"],
            "content": ["Backlog", "To-Do", "Planning", "Draft", "Published"]
        }

        self.priority_levels = [
            "Active",      # Do now
            "Essential",   # Important, do soon
            "Backlog",     # Eventually
        ]

        self.categories = [
            "AI/Technology",
            "Philosophy/Spirituality",
            "Leadership/Business",
            "Personal Development",
            "Content Strategy",
            "Relationships",
            "Health/Fitness",
            "Other"
        ]

        # Claude model for classification
        self.claude_model = "claude-sonnet-4-20250514"

        # Embedding model
        self.embedding_model = "text-embedding-3-small"  # OpenAI
        self.embedding_dimensions = 1536

    def validate(self) -> list[str]:
        """Validate required settings are present."""
        errors = []

        if not self.notion_api_key:
            errors.append("NOTION_API_KEY is required")
        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY is required")
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is required for embeddings/whisper")

        return errors


# Global settings instance
settings = Settings()
