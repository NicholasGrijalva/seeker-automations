#!/usr/bin/env python3
"""
Inbox Processor

Bulk process items in the Notion Inbox.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from src.notion_client import NotionClient
from src.classify import Classifier
from src.refine import Refiner
from config.settings import settings

console = Console()


@click.group()
def cli():
    """Process and manage Notion Inbox items."""
    pass


@cli.command()
@click.option("--status", "-s", default="New", help="Filter by status")
@click.option("--limit", "-l", default=10, help="Number of items to process")
@click.option("--dry-run", "-d", is_flag=True, help="Show what would be done without making changes")
def classify(status: str, limit: int, dry_run: bool):
    """
    Classify unprocessed inbox items.

    Updates items with:
    - Proper title (if auto-generated)
    - Type (Essay, Video, Post, Proself)
    - Tags (extracted from content)
    """

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    notion = NotionClient()
    classifier = Classifier()

    console.print(f"[bold]Classifying inbox items (status={status}, limit={limit})[/bold]\n")

    items = notion.query_inbox(status=status, limit=limit)

    if not items:
        console.print("[yellow]No items found matching criteria[/yellow]")
        return

    console.print(f"Found {len(items)} items to process\n")

    if dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]\n")

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:

        task = progress.add_task("Processing...", total=len(items))

        for item in items:
            page_id = item["id"]
            current_title = item["title"]

            # Get page content for classification
            content = notion.get_page_content(page_id)

            if not content:
                content = current_title  # Fall back to title

            # Classify
            classification = classifier.classify(content)

            results.append({
                "page_id": page_id,
                "old_title": current_title,
                "new_title": classification.title,
                "type": classification.content_type,
                "priority": classification.priority,
                "category": classification.category,
                "tags": classification.tags
            })

            if not dry_run:
                # Update the item
                updates = {
                    "Title": {
                        "title": [{"text": {"content": classification.title}}]
                    },
                    "Status": {
                        "select": {"name": "Triaged"}
                    }
                }

                if classification.tags:
                    updates["Tags"] = {
                        "multi_select": [{"name": tag} for tag in classification.tags[:5]]
                    }

                if classification.content_type:
                    updates["Type"] = {
                        "select": {"name": classification.content_type}
                    }

                notion.update_inbox_item(page_id, updates)

            progress.update(task, advance=1)

    # Show results
    table = Table(title="Classification Results")
    table.add_column("Old Title", style="dim", max_width=30)
    table.add_column("New Title", style="white", max_width=30)
    table.add_column("Type", style="yellow")
    table.add_column("Priority", style="cyan")
    table.add_column("Tags", style="dim", max_width=20)

    for r in results:
        table.add_row(
            r["old_title"][:30],
            r["new_title"][:30],
            r["type"],
            r["priority"],
            ", ".join(r["tags"][:3])
        )

    console.print(table)

    if not dry_run:
        console.print(f"\n[green]Updated {len(results)} items[/green]")


@cli.command()
@click.option("--status", "-s", default="Triaged", help="Filter by status")
@click.option("--limit", "-l", default=5, help="Number of items to refine")
@click.option("--output", "-o", type=click.Path(), help="Output directory for refined content")
def refine(status: str, limit: int, output: str):
    """
    Refine triaged items into structured content.

    Creates structured hypertext with:
    - Core aphorism
    - Supporting fragments
    - Linked concepts
    """

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    notion = NotionClient()
    refiner = Refiner()

    console.print(f"[bold]Refining inbox items (status={status}, limit={limit})[/bold]\n")

    items = notion.query_inbox(status=status, limit=limit)

    if not items:
        console.print("[yellow]No items found matching criteria[/yellow]")
        return

    output_dir = Path(output) if output else None
    if output_dir:
        output_dir.mkdir(exist_ok=True)

    for item in items:
        page_id = item["id"]
        title = item["title"]

        console.print(f"\n[cyan]Refining: {title}[/cyan]")

        # Get content
        content = notion.get_page_content(page_id)

        if not content:
            console.print("  [yellow]No content found, skipping[/yellow]")
            continue

        # Refine
        refined = refiner.refine(content)

        console.print(f"  [green]Core insight:[/green] {refined.core_aphorism}")
        console.print(f"  [dim]Fragments: {len(refined.fragments)}[/dim]")
        console.print(f"  [dim]Connections: {', '.join(refined.suggested_connections[:3])}[/dim]")

        # Save to file if output dir specified
        if output_dir:
            markdown = refiner.to_markdown(refined)
            filename = f"{title[:50].replace(' ', '_').replace('/', '-')}.md"
            filepath = output_dir / filename
            filepath.write_text(markdown)
            console.print(f"  [dim]Saved: {filepath}[/dim]")

        # Update Notion item status
        notion.update_inbox_item(page_id, {
            "Status": {"select": {"name": "Ready to Write"}}
        })


@cli.command()
@click.option("--from-status", "-f", default="Ready to Write", help="Source status")
@click.option("--limit", "-l", default=5, help="Number of items to promote")
@click.option("--dry-run", "-d", is_flag=True, help="Show what would be done")
def promote(from_status: str, limit: int, dry_run: bool):
    """
    Promote inbox items to Content Objects database.

    Moves refined items from Inbox to Content Objects for production.
    """

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    from config.notion_schema import ContentObject

    notion = NotionClient()
    classifier = Classifier()

    console.print(f"[bold]Promoting items to Content Objects (status={from_status})[/bold]\n")

    items = notion.query_inbox(status=from_status, limit=limit)

    if not items:
        console.print("[yellow]No items found matching criteria[/yellow]")
        return

    if dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]\n")

    for item in items:
        page_id = item["id"]
        title = item["title"]

        console.print(f"\n[cyan]Promoting: {title}[/cyan]")

        # Get content
        content = notion.get_page_content(page_id)

        # Get classification for metadata
        classification = classifier.classify(content or title)

        if dry_run:
            console.print(f"  Would create Content Object:")
            console.print(f"    Name: {classification.title}")
            console.print(f"    Type: {classification.content_type}")
            console.print(f"    Category: {classification.category}")
            continue

        # Create Content Object
        content_obj = ContentObject(
            name=classification.title,
            category=classification.category,
            content_type=classification.content_type,
            status="To-Do",
            tags=classification.tags,
            main_idea=classification.main_idea,
            original_transcript=content
        )

        response = notion.create_content_object(content_obj)
        new_page_id = response["id"]

        console.print(f"  [green]Created:[/green] https://notion.so/{new_page_id.replace('-', '')}")

        # Update inbox item status
        notion.update_inbox_item(page_id, {
            "Status": {"select": {"name": "Processed"}}
        })

    if not dry_run:
        console.print(f"\n[green]Promoted {len(items)} items[/green]")


@cli.command()
def stats():
    """Show inbox statistics."""

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    notion = NotionClient()

    console.print("[bold]Inbox Statistics[/bold]\n")

    # Count by status
    statuses = ["New", "Triaged", "Ready to Write", "Processed"]

    table = Table(title="Items by Status")
    table.add_column("Status", style="cyan")
    table.add_column("Count", style="white", justify="right")

    total = 0
    for status in statuses:
        items = notion.query_inbox(status=status, limit=100)
        count = len(items)
        total += count
        table.add_row(status, str(count))

    table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")

    console.print(table)


if __name__ == "__main__":
    cli()
