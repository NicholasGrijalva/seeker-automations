"""
Notion API Client

Handles all interactions with Notion databases.
"""

import logging
from typing import Optional, AsyncIterator
from datetime import datetime

from notion_client import Client, AsyncClient

from config.settings import settings
from config.notion_schema import InboxItem, ContentObject, NotionSchema

logger = logging.getLogger(__name__)


class NotionClient:
    """Client for Notion API operations."""

    def __init__(self, async_mode: bool = False):
        self.async_mode = async_mode

        if async_mode:
            self.client = AsyncClient(auth=settings.notion_api_key)
        else:
            self.client = Client(auth=settings.notion_api_key)

        # Database IDs for page creation (pages.create)
        self.inbox_db_id = settings.inbox_database_id
        self.content_db_id = settings.content_objects_database_id
        # Data Source IDs for queries (data_sources.query) - 2025 API format
        self.inbox_ds_id = settings.inbox_data_source_id
        self.content_ds_id = settings.content_data_source_id

    # ==================== INBOX OPERATIONS ====================

    def create_inbox_item(self, item: InboxItem) -> dict:
        """Create a new item in the Inbox database."""
        logger.info(f"Creating inbox item: {item.title[:50]}...")

        properties = item.to_notion_properties()

        # Create page
        response = self.client.pages.create(
            parent={"database_id": self.inbox_db_id},
            properties=properties
        )

        page_id = response["id"]

        # Add content to page body if we have transcript
        if item.raw_transcript:
            self._append_page_content(page_id, [
                {"type": "heading_2", "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Raw Transcript"}}]
                }},
                {"type": "paragraph", "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": item.raw_transcript}}]
                }}
            ])

        logger.info(f"Created inbox item: {page_id}")
        return response

    def update_inbox_item(self, page_id: str, updates: dict) -> dict:
        """Update an existing inbox item."""
        logger.info(f"Updating inbox item: {page_id}")

        return self.client.pages.update(
            page_id=page_id,
            properties=updates
        )

    def query_inbox(
        self,
        status: Optional[str] = None,
        limit: int = 100
    ) -> list[dict]:
        """Query items from the Inbox database."""
        filter_obj = None

        if status:
            filter_obj = {
                "property": "Status",
                "select": {"equals": status}
            }

        query_params = {
            "data_source_id": self.inbox_ds_id,
            "page_size": min(limit, 100),
            "sorts": [{"property": "Date Added", "direction": "descending"}]
        }
        if filter_obj:
            query_params["filter"] = filter_obj

        response = self.client.data_sources.query(**query_params)

        return self._parse_query_results(response["results"], "inbox")

    def get_inbox_item(self, page_id: str) -> dict:
        """Get a specific inbox item by ID."""
        page = self.client.pages.retrieve(page_id=page_id)
        return NotionSchema.parse_inbox_item(page).__dict__

    # ==================== CONTENT OBJECTS OPERATIONS ====================

    def create_content_object(self, obj: ContentObject) -> dict:
        """Create a new item in Content Objects database."""
        logger.info(f"Creating content object: {obj.name[:50]}...")

        properties = obj.to_notion_properties()

        response = self.client.pages.create(
            parent={"database_id": self.content_db_id},
            properties=properties
        )

        page_id = response["id"]

        # Add structured content to page body
        content_blocks = []

        if obj.main_idea:
            content_blocks.extend([
                {"type": "heading_2", "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Main Idea"}}]
                }},
                {"type": "callout", "callout": {
                    "rich_text": [{"type": "text", "text": {"content": obj.main_idea}}],
                    "icon": {"emoji": "💡"}
                }}
            ])

        if obj.original_transcript:
            content_blocks.extend([
                {"type": "heading_2", "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Original Transcript"}}]
                }},
                {"type": "toggle", "toggle": {
                    "rich_text": [{"type": "text", "text": {"content": "Click to expand transcript"}}],
                    "children": [
                        {"type": "paragraph", "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": obj.original_transcript[:2000]}}]
                        }}
                    ]
                }}
            ])

        if content_blocks:
            self._append_page_content(page_id, content_blocks)

        logger.info(f"Created content object: {page_id}")
        return response

    def update_content_object(self, page_id: str, updates: dict) -> dict:
        """Update an existing content object."""
        logger.info(f"Updating content object: {page_id}")

        return self.client.pages.update(
            page_id=page_id,
            properties=updates
        )

    def query_content_objects(
        self,
        status: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 100
    ) -> list[dict]:
        """Query items from Content Objects database."""
        filters = []

        if status:
            filters.append({
                "property": "Status",
                "select": {"equals": status}
            })

        if content_type:
            filters.append({
                "property": "Content Type",
                "select": {"equals": content_type}
            })

        filter_obj = None
        if len(filters) == 1:
            filter_obj = filters[0]
        elif len(filters) > 1:
            filter_obj = {"and": filters}

        query_params = {
            "data_source_id": self.content_ds_id,
            "page_size": min(limit, 100),
            "sorts": [{"property": "Date Created", "direction": "descending"}]
        }
        if filter_obj:
            query_params["filter"] = filter_obj

        response = self.client.data_sources.query(**query_params)

        return self._parse_query_results(response["results"], "content_objects")

    # ==================== HELPER METHODS ====================

    def _append_page_content(self, page_id: str, blocks: list[dict]):
        """Append blocks to a page."""
        try:
            self.client.blocks.children.append(
                block_id=page_id,
                children=blocks
            )
        except Exception as e:
            logger.error(f"Failed to append content to page: {e}")

    def _parse_query_results(self, results: list[dict], database: str) -> list[dict]:
        """Parse query results into simplified dicts."""
        parsed = []

        for page in results:
            if database == "inbox":
                item = NotionSchema.parse_inbox_item(page)
                parsed.append({
                    "id": page["id"],
                    "title": item.title,
                    "status": item.status,
                    "tags": item.tags,
                    "type": item.type,
                    "database": database
                })
            else:
                item = NotionSchema.parse_content_object(page)
                parsed.append({
                    "id": page["id"],
                    "name": item.name,
                    "status": item.status,
                    "content_type": item.content_type,
                    "category": item.category,
                    "tags": item.tags,
                    "main_idea": item.main_idea,
                    "database": database
                })

        return parsed

    def get_page_content(self, page_id: str) -> str:
        """Get the text content of a page's blocks."""
        blocks = self.get_page_blocks(page_id)
        text_parts = []

        for block in blocks:
            block_type = block["type"]
            block_data = block.get(block_type, {})

            # Extract text from common block types
            if "rich_text" in block_data:
                for text_obj in block_data["rich_text"]:
                    if "plain_text" in text_obj:
                        text_parts.append(text_obj["plain_text"])

        return "\n".join(text_parts)

    # ==================== EXPORT METHODS ====================

    def query_by_status(
        self,
        data_source_id: str,
        status_prop: str,
        status_value: str,
        limit: int = 50,
    ) -> list[dict]:
        """Query a database for pages matching a status. Returns raw page dicts."""
        query_params = {
            "data_source_id": data_source_id,
            "page_size": min(limit, 100),
            "filter": {
                "property": status_prop,
                "select": {"equals": status_value},
            },
        }

        response = self.client.data_sources.query(**query_params)
        return response.get("results", [])

    def get_page_blocks(self, page_id: str) -> list[dict]:
        """Get all blocks for a page. Handles pagination."""
        all_blocks = []
        cursor = None

        while True:
            kwargs = {"block_id": page_id}
            if cursor:
                kwargs["start_cursor"] = cursor

            response = self.client.blocks.children.list(**kwargs)
            all_blocks.extend(response.get("results", []))

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

        return all_blocks

    def get_file_block_urls(self, blocks: list[dict]) -> list[dict]:
        """Extract file/audio block URLs from a block list.

        Returns list of dicts with keys: url, filename, block_type.
        Notion file URLs are temporary signed URLs (~1hr validity).
        """
        files = []
        file_block_types = {"file", "audio", "video", "image", "pdf"}

        for block in blocks:
            block_type = block.get("type", "")
            if block_type not in file_block_types:
                continue

            block_data = block.get(block_type, {})

            # Notion files can be "file" (uploaded) or "external" (URL)
            file_info = block_data.get("file") or block_data.get("external")
            if not file_info:
                continue

            url = file_info.get("url", "")
            if not url:
                continue

            # Try to extract filename from URL or use block ID
            name = block_data.get("name", "")
            if not name:
                # Extract from URL path before query params
                url_path = url.split("?")[0]
                name = url_path.split("/")[-1] if "/" in url_path else block["id"]

            files.append({
                "url": url,
                "filename": name,
                "block_type": block_type,
            })

        return files

    def append_to_page(self, page_id: str, text: str, heading: Optional[str] = None):
        """Append text to an existing page."""
        blocks = []

        if heading:
            blocks.append({
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": heading}}]
                }
            })

        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            }
        })

        # Add timestamp
        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"Added: {datetime.now().strftime('%Y-%m-%d %H:%M')}"},
                    "annotations": {"color": "gray"}
                }]
            }
        })

        self._append_page_content(page_id, blocks)


# Convenience functions
def get_notion_client() -> NotionClient:
    """Get a configured Notion client."""
    return NotionClient()
