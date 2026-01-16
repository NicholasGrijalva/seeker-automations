#!/usr/bin/env python3
"""
CognosMap CLI

Command-line interface for processing content.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.syntax import Syntax

from src.pipeline import Pipeline, PipelineResult
from config.settings import settings

console = Console()


def print_result(result: PipelineResult):
    """Pretty print pipeline result."""

    if result.success:
        console.print(Panel(
            f"[green]Success![/green] Reached stage: {result.stage_reached}",
            title="Pipeline Complete"
        ))
    else:
        console.print(Panel(
            f"[red]Failed[/red] at stage: {result.stage_reached}\n\nError: {result.error}",
            title="Pipeline Error"
        ))
        return

    # Classification table
    if result.classification:
        table = Table(title="Classification Results")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")

        c = result.classification
        table.add_row("Title", c.title)
        table.add_row("Type", c.content_type)
        table.add_row("Priority", c.priority)
        table.add_row("Category", c.category)
        table.add_row("Tags", ", ".join(c.tags))
        table.add_row("Main Idea", c.main_idea[:100] + "..." if len(c.main_idea) > 100 else c.main_idea)

        console.print(table)

    # Dedupe result
    if result.dedupe_result:
        console.print(f"\n[bold]Deduplication:[/bold] {result.dedupe_result.recommendation}")
        if result.dedupe_result.best_match:
            m = result.dedupe_result.best_match
            console.print(f"  Best match: '{m.title}' (score: {m.similarity_score:.2f})")

    # Notion page
    if result.notion_page_id:
        console.print(f"\n[bold]Notion Page:[/bold] https://notion.so/{result.notion_page_id.replace('-', '')}")

    # Refined content
    if result.refined_content:
        console.print(Panel(
            result.refined_content.core_aphorism,
            title="Core Insight"
        ))

    # Platform outputs
    if result.platform_outputs:
        console.print("\n[bold]Generated Outputs:[/bold]")
        for platform, output in result.platform_outputs.items():
            console.print(f"\n[cyan]{platform.upper()}[/cyan]")
            console.print(f"  {output.metadata}")

    console.print(f"\n[dim]Processing time: {result.processing_time_ms}ms[/dim]")


@click.group()
def cli():
    """CognosMap Content Automation CLI"""
    pass


@cli.command()
@click.argument("text", required=False)
@click.option("--voice", "-v", type=click.Path(exists=True), help="Path to voice memo file")
@click.option("--refine", "-r", is_flag=True, help="Auto-refine content")
@click.option("--platforms", "-p", multiple=True, help="Generate platform outputs (twitter, linkedin, substack, video)")
def process(text: str, voice: str, refine: bool, platforms: tuple):
    """Process text or voice memo through the pipeline."""

    # Validate settings
    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors:[/red]")
        for err in errors:
            console.print(f"  - {err}")
        console.print("\nPlease set up your .env file. See .env.example")
        sys.exit(1)

    pipeline = Pipeline()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:

        if voice:
            progress.add_task("Processing voice memo...", total=None)
            result = pipeline.process_audio(
                voice,
                auto_refine=refine,
                platforms=list(platforms) if platforms else None
            )
        elif text:
            progress.add_task("Processing text...", total=None)
            result = pipeline.process_text(
                text,
                auto_refine=refine,
                platforms=list(platforms) if platforms else None
            )
        else:
            # Read from stdin
            console.print("[yellow]Enter your idea (Ctrl+D when done):[/yellow]")
            text = sys.stdin.read().strip()
            if not text:
                console.print("[red]No input provided[/red]")
                sys.exit(1)

            progress.add_task("Processing input...", total=None)
            result = pipeline.process_text(
                text,
                auto_refine=refine,
                platforms=list(platforms) if platforms else None
            )

    print_result(result)


@cli.command()
@click.argument("page_id")
@click.option("--platforms", "-p", multiple=True, default=["twitter", "linkedin"], help="Platforms to generate")
def refine(page_id: str, platforms: tuple):
    """Refine an existing Notion page."""

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    pipeline = Pipeline()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        progress.add_task("Refining content...", total=None)
        result = pipeline.refine_existing(page_id, list(platforms))

    print_result(result)

    # Show platform outputs
    if result.platform_outputs:
        for platform, output in result.platform_outputs.items():
            console.print(f"\n[bold cyan]═══ {platform.upper()} ═══[/bold cyan]\n")
            console.print(output.content)


@cli.command()
@click.option("--status", "-s", default="New", help="Filter by status")
@click.option("--limit", "-l", default=10, help="Number of items to show")
def inbox(status: str, limit: int):
    """List items in the Notion Inbox."""

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    from src.notion_client import NotionClient
    notion = NotionClient()

    items = notion.query_inbox(status=status, limit=limit)

    table = Table(title=f"Inbox Items (status={status})")
    table.add_column("Title", style="white", max_width=50)
    table.add_column("Status", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Tags", style="dim")

    for item in items:
        table.add_row(
            item["title"][:50],
            item["status"],
            item.get("type", "-"),
            ", ".join(item.get("tags", []))[:30]
        )

    console.print(table)


@cli.command()
@click.option("--limit", "-l", default=10, help="Number of items to show")
def content(limit: int):
    """List Content Objects."""

    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors. Please set up .env[/red]")
        sys.exit(1)

    from src.notion_client import NotionClient
    notion = NotionClient()

    items = notion.query_content_objects(limit=limit)

    table = Table(title="Content Objects")
    table.add_column("Name", style="white", max_width=40)
    table.add_column("Type", style="yellow")
    table.add_column("Status", style="cyan")
    table.add_column("Category", style="dim")

    for item in items:
        table.add_row(
            item["name"][:40],
            item.get("content_type", "-"),
            item["status"],
            item.get("category", "-")
        )

    console.print(table)


@cli.command()
def check():
    """Check configuration and API connections."""

    console.print("[bold]Checking configuration...[/bold]\n")

    # Check env vars
    errors = settings.validate()
    if errors:
        console.print("[red]Missing configuration:[/red]")
        for err in errors:
            console.print(f"  [red]✗[/red] {err}")
    else:
        console.print("[green]✓[/green] All API keys configured")

    # Check Notion connection
    console.print("\n[bold]Testing Notion connection...[/bold]")
    try:
        from src.notion_client import NotionClient
        notion = NotionClient()
        inbox_items = notion.query_inbox(limit=1)
        console.print(f"[green]✓[/green] Inbox database connected ({settings.inbox_database_id[:8]}...)")

        content_items = notion.query_content_objects(limit=1)
        console.print(f"[green]✓[/green] Content Objects database connected ({settings.content_objects_database_id[:8]}...)")
    except Exception as e:
        console.print(f"[red]✗[/red] Notion connection failed: {e}")

    # Check Claude
    console.print("\n[bold]Testing Claude connection...[/bold]")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        # Just verify the client initializes
        console.print(f"[green]✓[/green] Anthropic client configured (model: {settings.claude_model})")
    except Exception as e:
        console.print(f"[red]✗[/red] Anthropic connection failed: {e}")

    # Check OpenAI
    console.print("\n[bold]Testing OpenAI connection...[/bold]")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        console.print(f"[green]✓[/green] OpenAI client configured (embedding: {settings.embedding_model})")
    except Exception as e:
        console.print(f"[red]✗[/red] OpenAI connection failed: {e}")


if __name__ == "__main__":
    cli()
