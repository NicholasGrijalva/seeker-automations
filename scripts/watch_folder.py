#!/usr/bin/env python3
"""
Voice Memo Folder Watcher

Monitors a folder for new voice memos and processes them automatically.
"""

import sys
import time
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from rich.console import Console
from rich.logging import RichHandler

from src.pipeline import Pipeline
from config.settings import settings

console = Console()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, rich_tracebacks=True)]
)
logger = logging.getLogger(__name__)


class VoiceMemoHandler(FileSystemEventHandler):
    """Handler for new voice memo files."""

    AUDIO_EXTENSIONS = {".m4a", ".mp3", ".mp4", ".wav", ".webm", ".ogg"}

    def __init__(self, pipeline: Pipeline, processed_dir: Path = None):
        self.pipeline = pipeline
        self.processed_dir = processed_dir
        self.processing = set()  # Track files being processed

    def on_created(self, event: FileCreatedEvent):
        """Handle new file creation."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Check if it's an audio file
        if file_path.suffix.lower() not in self.AUDIO_EXTENSIONS:
            return

        # Skip if already processing
        if str(file_path) in self.processing:
            return

        # Wait a moment for file to be fully written
        time.sleep(2)

        if not file_path.exists():
            return

        self.process_file(file_path)

    def process_file(self, file_path: Path):
        """Process a voice memo file."""
        self.processing.add(str(file_path))

        try:
            logger.info(f"Processing: {file_path.name}")

            result = self.pipeline.process_audio(file_path)

            if result.success:
                logger.info(f"[green]Success![/green] Created: {result.classification.title}")
                logger.info(f"  Type: {result.classification.content_type}")
                logger.info(f"  Priority: {result.classification.priority}")
                logger.info(f"  Notion: https://notion.so/{result.notion_page_id.replace('-', '')}")

                # Move to processed folder if configured
                if self.processed_dir:
                    self.processed_dir.mkdir(exist_ok=True)
                    dest = self.processed_dir / f"{datetime.now().strftime('%Y%m%d_%H%M')}_{file_path.name}"
                    file_path.rename(dest)
                    logger.info(f"  Moved to: {dest}")

            else:
                logger.error(f"[red]Failed![/red] {result.error}")

        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")

        finally:
            self.processing.discard(str(file_path))


@click.command()
@click.argument("folder", type=click.Path(exists=True), default=None, required=False)
@click.option("--processed", "-p", type=click.Path(), help="Move processed files to this folder")
@click.option("--once", "-o", is_flag=True, help="Process existing files once and exit")
def main(folder: str, processed: str, once: bool):
    """
    Watch a folder for new voice memos and process them.

    If no folder is specified, uses VOICE_MEMO_FOLDER from .env
    """

    # Validate settings
    errors = settings.validate()
    if errors:
        console.print("[red]Configuration errors:[/red]")
        for err in errors:
            console.print(f"  - {err}")
        sys.exit(1)

    # Determine watch folder
    if folder:
        watch_path = Path(folder)
    else:
        watch_path = settings.voice_memo_folder

    if not watch_path.exists():
        console.print(f"[red]Folder does not exist: {watch_path}[/red]")
        sys.exit(1)

    processed_path = Path(processed) if processed else None

    console.print(f"[bold]CognosMap Voice Memo Watcher[/bold]")
    console.print(f"Watching: {watch_path}")
    if processed_path:
        console.print(f"Processed folder: {processed_path}")
    console.print()

    # Initialize pipeline
    pipeline = Pipeline()
    handler = VoiceMemoHandler(pipeline, processed_path)

    if once:
        # Process existing files and exit
        console.print("[yellow]Processing existing files...[/yellow]")
        for ext in handler.AUDIO_EXTENSIONS:
            for file_path in watch_path.glob(f"*{ext}"):
                handler.process_file(file_path)
        console.print("[green]Done![/green]")
        return

    # Start watching
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=False)
    observer.start()

    console.print("[green]Watching for new voice memos... (Ctrl+C to stop)[/green]")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping...[/yellow]")
        observer.stop()

    observer.join()
    console.print("[green]Stopped.[/green]")


if __name__ == "__main__":
    main()
