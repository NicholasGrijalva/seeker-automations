#!/usr/bin/env python3
"""
Notion -> CognosMap Exporter

Watches Notion databases for items matching a trigger status, exports them
as persistent .md files with YAML frontmatter, downloads audio files, and
pushes to CognosMap's synthesis API.

Pipeline position: [capture] -> [cleanup/triage] -> ||| [THIS] ||| -> CognosMap

Usage:
    python scripts/notion_exporter.py export                    # One-shot export
    python scripts/notion_exporter.py export --dry-run          # Preview
    python scripts/notion_exporter.py export --limit 3          # Export first 3
    python scripts/notion_exporter.py watch                     # Long-running poll
    python scripts/notion_exporter.py watch --interval 30       # Poll every 30s
    python scripts/notion_exporter.py status                    # Show export state
"""

import hashlib
import json
import logging
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import httpx
import yaml
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings, ExportSource
from src.notion_client import NotionClient

logger = logging.getLogger(__name__)
console = Console()

SCHEMA_VERSION = 1


@dataclass
class ExportMetrics:
    exported: int = 0
    skipped: int = 0
    failed: int = 0
    details: list = field(default_factory=list)


class NotionExporter:
    """Exports Notion database pages to .md files and syncs to CognosMap."""

    def __init__(
        self,
        notion: NotionClient,
        vault_path: Path,
        api_base: str,
        dry_run: bool = False,
    ):
        self.notion = notion
        self.vault_path = vault_path
        self.api_base = api_base
        self.dry_run = dry_run
        self.state_file = vault_path / ".export-state.json"
        self.state = self._load_state()

    # ── State Management ────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load state file: {e}")
        return {"version": 1, "exports": {}}

    def _save_state(self):
        if self.dry_run:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2, default=str))

    # ── Content Hashing ─────────────────────────────────────────────────────

    def _compute_hash(self, page: dict, body_text: str) -> str:
        """Hash page properties + body for change detection."""
        props_json = json.dumps(page.get("properties", {}), sort_keys=True, default=str)
        combined = f"{props_json}|{body_text}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    # ── Property Extraction ─────────────────────────────────────────────────

    def _extract_property(self, props: dict, name: str, expected_type: str) -> any:
        """Safely extract a Notion property value."""
        prop = props.get(name, {})

        if expected_type == "title":
            title_arr = prop.get("title", [])
            return title_arr[0]["plain_text"] if title_arr else "Untitled"

        elif expected_type == "select":
            select_val = prop.get("select")
            return select_val["name"] if select_val else None

        elif expected_type == "multi_select":
            return [t["name"] for t in prop.get("multi_select", [])]

        elif expected_type == "rich_text":
            text_arr = prop.get("rich_text", [])
            return text_arr[0]["plain_text"] if text_arr else ""

        elif expected_type == "date":
            date_val = prop.get("date")
            return date_val["start"] if date_val else None

        elif expected_type == "url":
            return prop.get("url")

        return None

    def _extract_all_properties(self, page: dict, source: ExportSource) -> dict:
        """Extract all relevant properties from a Notion page."""
        props = page.get("properties", {})

        metadata = {
            "notion_id": page["id"],
            "notion_database": source.name,
            "title": self._extract_property(props, source.title_prop, "title"),
            "status": self._extract_property(props, source.status_prop, "select"),
            "tags": self._extract_property(props, source.tag_prop, "multi_select"),
        }

        # Extract additional known properties (safe -- skips missing ones)
        extra_props = {
            "Type": ("type", "select"),
            "Date Added": ("date_added", "date"),
            "Source": ("source_ref", "rich_text"),
            "Source Filename": ("source_filename", "rich_text"),
            "URL": ("source_url", "url"),
            "Processing Time (s)": ("processing_time", "rich_text"),
        }

        for prop_name, (key, ptype) in extra_props.items():
            val = self._extract_property(props, prop_name, ptype)
            if val:
                metadata[key] = val

        return metadata

    # ── Body Content ────────────────────────────────────────────────────────

    def _get_body_content(self, page: dict, source: ExportSource) -> str:
        """Get the text content for the .md body."""
        page_id = page["id"]

        # If source specifies a content property, use that
        if source.content_prop:
            props = page.get("properties", {})
            text_arr = props.get(source.content_prop, {}).get("rich_text", [])
            content = text_arr[0]["plain_text"] if text_arr else ""
            if content:
                return content

        # Fallback: extract from page blocks
        return self.notion.get_page_content(page_id)

    # ── Audio Download ──────────────────────────────────────────────────────

    def _download_audio(
        self, page_id: str, output_dir: Path, notion_id_short: str
    ) -> Optional[str]:
        """Download audio/file attachments from a page. Returns filename or None."""
        try:
            blocks = self.notion.get_page_blocks(page_id)
            file_blocks = self.notion.get_file_block_urls(blocks)

            if not file_blocks:
                return None

            # Take the first audio/file block
            file_info = file_blocks[0]
            url = file_info["url"]

            # Determine extension from original filename or URL
            orig_name = file_info.get("filename", "")
            ext = Path(orig_name).suffix if orig_name else ".mp3"
            if not ext or ext == ".":
                ext = ".mp3"

            filename = f"{notion_id_short}{ext}"
            filepath = output_dir / filename

            resp = httpx.get(url, timeout=60.0, follow_redirects=True)
            if resp.status_code == 200:
                filepath.write_bytes(resp.content)
                logger.info(f"Downloaded audio: {filename} ({len(resp.content)} bytes)")
                return filename
            else:
                logger.warning(f"Audio download failed: {resp.status_code}")
                return None

        except Exception as e:
            logger.warning(f"Audio download error for {page_id}: {e}")
            return None

    # ── Markdown Generation ─────────────────────────────────────────────────

    def _slugify(self, text: str) -> str:
        """Convert text to filesystem-safe slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[-\s]+", "-", text)
        return text[:60].strip("-")

    def _page_to_markdown(
        self, metadata: dict, body: str, audio_file: Optional[str], content_hash: str
    ) -> str:
        """Build .md file content with YAML frontmatter."""
        frontmatter = {
            "schema_version": SCHEMA_VERSION,
            "source": "notion",
            "notion_id": metadata["notion_id"],
            "notion_database": metadata["notion_database"],
            "content_hash": content_hash,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        # Add optional metadata fields
        for key in [
            "type", "status", "tags", "date_added", "source_url",
            "source_filename", "source_ref",
        ]:
            if key in metadata and metadata[key]:
                frontmatter[key] = metadata[key]

        if audio_file:
            frontmatter["has_audio"] = True
            frontmatter["audio_file"] = audio_file

        # Build markdown
        yaml_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        title = metadata.get("title", "Untitled")
        md = f"---\n{yaml_str}---\n\n# {title}\n\n{body}\n"

        return md

    def _make_filename(self, metadata: dict) -> str:
        """Generate stable filename: {slug}--{id_short8}.md"""
        title = metadata.get("title", "untitled")
        notion_id = metadata["notion_id"]
        slug = self._slugify(title)
        id_short = notion_id.split("-")[0] if "-" in notion_id else notion_id[:8]
        return f"{slug}--{id_short}.md"

    # ── CognosMap Sync ──────────────────────────────────────────────────────

    def _sync_to_cognosmap(
        self,
        metadata: dict,
        body: str,
        source: ExportSource,
        filename: str,
    ) -> bool:
        """Push note to CognosMap synthesis API."""
        notion_id = metadata["notion_id"]
        tags = metadata.get("tags", [])

        # Build frontmatter dict for CognosMap (stored on VaultNote node)
        cm_frontmatter = {
            "notion_id": notion_id,
            "source": "notion",
            "notion_database": source.name,
        }
        for key in ["type", "date_added", "source_url", "source_filename"]:
            if key in metadata and metadata[key]:
                cm_frontmatter[key] = metadata[key]

        try:
            resp = httpx.post(
                f"{self.api_base}/api/synthesis/ingest",
                json={
                    "note_id": f"notion:{notion_id}",
                    "title": metadata.get("title", "Untitled"),
                    "vault_path": f"notion/{source.output_dir}/{filename}",
                    "content": body,
                    "wikilinks": [],
                    "tags": tags,
                    "frontmatter": cm_frontmatter,
                },
                timeout=30.0,
            )
            if resp.status_code == 201:
                data = resp.json()
                logger.info(f"Synced to CognosMap: {data.get('links_created', 0)} links")
                return True
            else:
                logger.warning(f"CognosMap sync failed: {resp.status_code} {resp.text[:200]}")
                return False
        except Exception as e:
            logger.warning(f"CognosMap sync error: {e}")
            return False

    # ── Main Export Logic ───────────────────────────────────────────────────

    def export_source(self, source: ExportSource, limit: int = 50) -> ExportMetrics:
        """Export all qualifying pages from a single Notion database."""
        metrics = ExportMetrics()

        # Ensure output directory exists
        output_dir = self.vault_path / source.output_dir
        if not self.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Query Notion for pages matching trigger status
        pages = self.notion.query_by_status(
            data_source_id=source.data_source_id,
            status_prop=source.status_prop,
            status_value=source.trigger_status,
            limit=limit,
        )

        if not pages:
            console.print(f"  No {source.trigger_status} items in {source.name}")
            return metrics

        console.print(f"  Found {len(pages)} {source.trigger_status} items in {source.name}")

        for page in pages:
            page_id = page["id"]
            notion_id_short = page_id.split("-")[0] if "-" in page_id else page_id[:8]

            try:
                # Extract properties
                metadata = self._extract_all_properties(page, source)
                title = metadata.get("title", "Untitled")

                # Get body content
                body = self._get_body_content(page, source)

                # Compute content hash for change detection
                content_hash = self._compute_hash(page, body)

                # Check state -- skip if unchanged
                existing = self.state.get("exports", {}).get(page_id)
                if existing and existing.get("content_hash") == content_hash:
                    metrics.skipped += 1
                    metrics.details.append(f"  SKIP {title} (unchanged)")
                    continue

                # Generate filename
                filename = self._make_filename(metadata)

                if self.dry_run:
                    console.print(
                        f"  [dim]WOULD EXPORT[/dim] {title} "
                        f"({len(body)} chars) -> {filename}"
                    )
                    metrics.exported += 1
                    continue

                # Delete old file if filename changed (title rename)
                if existing and existing.get("filename") != filename:
                    old_path = output_dir / existing["filename"]
                    if old_path.exists():
                        old_path.unlink()
                        logger.info(f"Removed old file: {existing['filename']}")

                # Download audio (before writing .md so we know the audio filename)
                audio_file = self._download_audio(page_id, output_dir, notion_id_short)

                # Write .md file
                md_content = self._page_to_markdown(metadata, body, audio_file, content_hash)
                filepath = output_dir / filename
                filepath.write_text(md_content, encoding="utf-8")

                # Sync to CognosMap
                synced = self._sync_to_cognosmap(metadata, body, source, filename)

                # Update Notion status
                try:
                    self.notion.update_inbox_item(page_id, {
                        source.status_prop: {"select": {"name": source.post_export_status}},
                    })
                except Exception as e:
                    logger.warning(f"Failed to update Notion status: {e}")

                # Update local state
                self.state.setdefault("exports", {})[page_id] = {
                    "content_hash": content_hash,
                    "filename": filename,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "synced_to_cognosmap": synced,
                    "database": source.name,
                }
                self._save_state()

                metrics.exported += 1
                metrics.details.append(
                    f"  OK {title} -> {filename}"
                    + (f" + {audio_file}" if audio_file else "")
                    + (" [synced]" if synced else " [sync failed]")
                )

            except Exception as e:
                logger.error(f"Failed to export page {page_id}: {e}")
                metrics.failed += 1
                metrics.details.append(f"  FAIL {page_id}: {e}")

        return metrics

    def export_all(self, limit: int = 50) -> dict[str, ExportMetrics]:
        """Export from all configured sources."""
        results = {}
        for source in settings.export_sources:
            console.print(f"\n[bold]Exporting: {source.name}[/bold]")
            metrics = self.export_source(source, limit=limit)
            results[source.name] = metrics

            for detail in metrics.details:
                console.print(detail)

            console.print(
                f"  Exported: {metrics.exported}  "
                f"Skipped: {metrics.skipped}  "
                f"Failed: {metrics.failed}"
            )

        return results

    def watch(self, interval: int = 60):
        """Long-running poll loop."""
        running = True

        def handle_signal(sig, frame):
            nonlocal running
            console.print("\nShutting down...")
            running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        console.print(
            f"[bold]Watching Notion databases every {interval}s[/bold]\n"
            f"  Sources: {', '.join(s.name for s in settings.export_sources)}\n"
            f"  Vault: {self.vault_path}\n"
            f"  API: {self.api_base}\n"
            f"  Press Ctrl+C to stop\n"
        )

        while running:
            try:
                self.export_all()
            except Exception as e:
                logger.error(f"Export cycle failed: {e}")
                console.print(f"[red]Error: {e}[/red]")

            # Sleep in small increments so we can catch signals
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)

    def show_status(self):
        """Display export state summary."""
        exports = self.state.get("exports", {})

        if not exports:
            console.print("No exports yet.")
            return

        table = Table(title="Export State")
        table.add_column("Database", max_width=15)
        table.add_column("Filename", max_width=40)
        table.add_column("Synced", max_width=8)
        table.add_column("Exported At", max_width=22)

        for page_id, info in sorted(
            exports.items(), key=lambda x: x[1].get("exported_at", ""), reverse=True
        ):
            table.add_row(
                info.get("database", "?"),
                info.get("filename", "?"),
                "yes" if info.get("synced_to_cognosmap") else "no",
                info.get("exported_at", "?")[:19],
            )

        console.print(table)
        console.print(f"\nTotal exports: {len(exports)}")
        console.print(f"State file: {self.state_file}")


# ── CLI ─────────────────────────────────────────────────────────────────────


@click.group()
def cli():
    """Notion -> CognosMap export pipeline."""
    pass


@cli.command()
@click.option("--source", "-s", default=None, help="Export source name (default: all)")
@click.option("--limit", "-l", default=50, help="Max pages per source")
@click.option("--dry-run", "-d", is_flag=True, help="Preview without writing files")
def export(source: Optional[str], limit: int, dry_run: bool):
    """One-shot export of qualifying pages."""
    errors = settings.validate()
    if errors:
        for e in errors:
            console.print(f"[red]{e}[/red]")
        return

    notion = NotionClient()
    exporter = NotionExporter(
        notion=notion,
        vault_path=settings.notion_vault_path,
        api_base=settings.cognosmap_api_base,
        dry_run=dry_run,
    )

    if dry_run:
        console.print("[yellow]DRY RUN -- no files will be written[/yellow]\n")

    if source:
        # Find specific source
        matched = [s for s in settings.export_sources if s.name == source]
        if not matched:
            names = ", ".join(s.name for s in settings.export_sources)
            console.print(f"[red]Unknown source '{source}'. Available: {names}[/red]")
            return
        console.print(f"\n[bold]Exporting: {matched[0].name}[/bold]")
        metrics = exporter.export_source(matched[0], limit=limit)
        for detail in metrics.details:
            console.print(detail)
        console.print(
            f"\n  Exported: {metrics.exported}  "
            f"Skipped: {metrics.skipped}  "
            f"Failed: {metrics.failed}"
        )
    else:
        exporter.export_all(limit=limit)


@cli.command()
@click.option("--interval", "-i", default=None, type=int, help="Poll interval in seconds")
def watch(interval: Optional[int]):
    """Long-running watch mode."""
    errors = settings.validate()
    if errors:
        for e in errors:
            console.print(f"[red]{e}[/red]")
        return

    poll_interval = interval or settings.export_poll_interval

    notion = NotionClient()
    exporter = NotionExporter(
        notion=notion,
        vault_path=settings.notion_vault_path,
        api_base=settings.cognosmap_api_base,
    )
    exporter.watch(interval=poll_interval)


@cli.command()
def status():
    """Show export state."""
    exporter = NotionExporter(
        notion=None,  # No API calls needed for status
        vault_path=settings.notion_vault_path,
        api_base=settings.cognosmap_api_base,
    )
    exporter.show_status()


if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cli()
