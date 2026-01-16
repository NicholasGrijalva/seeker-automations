"""
Notion Database Schema Definitions

Maps your Notion database properties to Python structures.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class InboxItem:
    """Schema for Inbox database items."""

    # Required
    title: str

    # Auto-populated
    date_added: datetime = field(default_factory=datetime.now)
    status: str = "New"

    # Optional
    tags: list[str] = field(default_factory=list)
    type: Optional[str] = None
    project: Optional[str] = None
    url: Optional[str] = None

    # Content (stored in page body)
    raw_transcript: Optional[str] = None
    source_file: Optional[str] = None

    # Classification results (stored in page body or properties)
    classified_type: Optional[str] = None
    classified_priority: Optional[str] = None
    classified_category: Optional[str] = None
    extracted_tags: list[str] = field(default_factory=list)

    def to_notion_properties(self) -> dict:
        """Convert to Notion API property format."""
        properties = {
            "Title": {
                "title": [{"text": {"content": self.title}}]
            },
            "Date Added": {
                "date": {"start": self.date_added.isoformat()}
            },
            "Status": {
                "select": {"name": self.status}
            }
        }

        if self.tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in self.tags]
            }

        if self.type:
            properties["Type"] = {
                "select": {"name": self.type}
            }

        if self.url:
            properties["URL"] = {
                "url": self.url
            }

        return properties


@dataclass
class ContentObject:
    """Schema for Content Objects database items."""

    # Required
    name: str

    # Classification
    category: Optional[str] = None
    content_type: str = "Essay"
    status: str = "Backlog"

    # Dates
    date_created: datetime = field(default_factory=datetime.now)
    target_publish_date: Optional[datetime] = None

    # Content
    original_transcript: Optional[str] = None
    main_idea: Optional[str] = None

    # Relations & Links
    tags: list[str] = field(default_factory=list)
    atomic_ideas: list[str] = field(default_factory=list)  # Relation IDs
    platform: list[str] = field(default_factory=list)

    # URLs
    asset_folder_url: Optional[str] = None
    transcript_url: Optional[str] = None
    post_examples: Optional[str] = None

    def to_notion_properties(self) -> dict:
        """Convert to Notion API property format."""
        properties = {
            "Name": {
                "title": [{"text": {"content": self.name}}]
            },
            "Content Type": {
                "select": {"name": self.content_type}
            },
            "Status": {
                "select": {"name": self.status}
            },
            "Date Created": {
                "date": {"start": self.date_created.isoformat()}
            }
        }

        if self.category:
            properties["Category"] = {
                "select": {"name": self.category}
            }

        if self.tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in self.tags]
            }

        if self.main_idea:
            properties["Main Idea"] = {
                "rich_text": [{"text": {"content": self.main_idea[:2000]}}]  # Notion limit
            }

        if self.original_transcript:
            properties["Original Transcript"] = {
                "rich_text": [{"text": {"content": self.original_transcript[:2000]}}]
            }

        if self.platform:
            properties["Platform"] = {
                "multi_select": [{"name": p} for p in self.platform]
            }

        if self.target_publish_date:
            properties["Target Publish Date"] = {
                "date": {"start": self.target_publish_date.isoformat()}
            }

        return properties


class NotionSchema:
    """Schema helper for Notion database operations."""

    # Property name mappings (Notion name -> Python name)
    INBOX_PROPERTIES = {
        "Title": "title",
        "Date Added": "date_added",
        "Status": "status",
        "Tags": "tags",
        "Type": "type",
        "Project": "project",
        "URL": "url"
    }

    CONTENT_PROPERTIES = {
        "Name": "name",
        "Category": "category",
        "Content Type": "content_type",
        "Date Created": "date_created",
        "Original Transcript": "original_transcript",
        "Status": "status",
        "Tags": "tags",
        "Target Publish Date": "target_publish_date",
        "Asset Folder URL": "asset_folder_url",
        "Atomic Ideas": "atomic_ideas",
        "Main Idea": "main_idea",
        "Platform": "platform",
        "Post Examples": "post_examples",
        "Transcript URL": "transcript_url"
    }

    @staticmethod
    def parse_inbox_item(notion_page: dict) -> InboxItem:
        """Parse a Notion page into an InboxItem."""
        props = notion_page.get("properties", {})

        # Extract title
        title_prop = props.get("Title", {}).get("title", [])
        title = title_prop[0]["plain_text"] if title_prop else "Untitled"

        # Extract status
        status_prop = props.get("Status", {}).get("select")
        status = status_prop["name"] if status_prop else "New"

        # Extract tags
        tags_prop = props.get("Tags", {}).get("multi_select", [])
        tags = [t["name"] for t in tags_prop]

        # Extract type
        type_prop = props.get("Type", {}).get("select")
        item_type = type_prop["name"] if type_prop else None

        return InboxItem(
            title=title,
            status=status,
            tags=tags,
            type=item_type
        )

    @staticmethod
    def parse_content_object(notion_page: dict) -> ContentObject:
        """Parse a Notion page into a ContentObject."""
        props = notion_page.get("properties", {})

        # Extract name
        name_prop = props.get("Name", {}).get("title", [])
        name = name_prop[0]["plain_text"] if name_prop else "Untitled"

        # Extract content type
        ct_prop = props.get("Content Type", {}).get("select")
        content_type = ct_prop["name"] if ct_prop else "Essay"

        # Extract status
        status_prop = props.get("Status", {}).get("select")
        status = status_prop["name"] if status_prop else "Backlog"

        # Extract category
        cat_prop = props.get("Category", {}).get("select")
        category = cat_prop["name"] if cat_prop else None

        # Extract tags
        tags_prop = props.get("Tags", {}).get("multi_select", [])
        tags = [t["name"] for t in tags_prop]

        # Extract main idea
        mi_prop = props.get("Main Idea", {}).get("rich_text", [])
        main_idea = mi_prop[0]["plain_text"] if mi_prop else None

        return ContentObject(
            name=name,
            content_type=content_type,
            status=status,
            category=category,
            tags=tags,
            main_idea=main_idea
        )
