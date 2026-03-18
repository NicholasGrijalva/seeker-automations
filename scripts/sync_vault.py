#!/usr/bin/env python3
"""
Vault -> CognosMap Sync

Reads Obsidian vault via obsidiantools and POSTs each note to
CognosMap's /api/synthesis/ingest endpoint.

Usage:
    python scripts/sync_vault.py                    # Full sync
    python scripts/sync_vault.py --dry-run          # Preview
    python scripts/sync_vault.py --limit 10         # Sync first 10 notes
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings

SKIP_FOLDERS = [".obsidian", ".smart-env", ".trash", "05_Utils", "06_Archive"]


def sync_vault(
    vault_path: Path,
    api_base: str = "http://localhost:8000",
    dry_run: bool = False,
    limit: int = 0,
):
    """Sync vault notes to CognosMap synthesis API."""
    import obsidiantools.api as otools

    print(f"Scanning vault: {vault_path}")
    vault = otools.Vault(vault_path).connect().gather()

    notes = []
    for stem, path in vault.md_file_index.items():
        rel_path = str(path)
        if any(rel_path.startswith(skip) for skip in SKIP_FOLDERS):
            continue
        notes.append((stem, rel_path))

    if limit > 0:
        notes = notes[:limit]

    print(f"Found {len(notes)} notes to sync\n")

    synced = 0
    skipped = 0
    failed = 0

    for i, (stem, rel_path) in enumerate(notes, 1):
        content = vault.get_source_text(stem) or ""
        wikilinks = vault.get_wikilinks(stem) or []
        tags = vault.get_tags(stem) or []

        note_id = f"vault:{stem}"

        if dry_run:
            print(f"  [{i}/{len(notes)}] {stem} ({len(content)} chars, {len(wikilinks)} links)")
            synced += 1
            continue

        try:
            resp = httpx.post(
                f"{api_base}/api/synthesis/ingest",
                json={
                    "note_id": note_id,
                    "title": stem,
                    "vault_path": rel_path,
                    "content": content,
                    "wikilinks": wikilinks,
                    "tags": tags,
                    "frontmatter": {},
                },
                timeout=30.0,
            )
            if resp.status_code == 201:
                data = resp.json()
                print(f"  [{i}/{len(notes)}] {stem} -> {data['links_created']} links")
                synced += 1
            else:
                print(f"  [{i}/{len(notes)}] {stem} FAILED: {resp.status_code} {resp.text[:100]}")
                failed += 1
        except Exception as e:
            print(f"  [{i}/{len(notes)}] {stem} ERROR: {e}")
            failed += 1

    print(f"\nDone. Synced: {synced}, Skipped: {skipped}, Failed: {failed}")


def main():
    parser = argparse.ArgumentParser(description="Sync Obsidian vault to CognosMap")
    parser.add_argument(
        "--vault",
        type=Path,
        default=settings.obsidian_vault_path,
        help="Vault path",
    )
    parser.add_argument(
        "--api",
        default="http://localhost:8000",
        help="CognosMap API base URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without syncing")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of notes")
    args = parser.parse_args()

    if not args.vault.exists():
        print(f"Error: Vault not found at {args.vault}")
        return 1

    sync_vault(args.vault, args.api, args.dry_run, args.limit)
    return 0


if __name__ == "__main__":
    exit(main())
