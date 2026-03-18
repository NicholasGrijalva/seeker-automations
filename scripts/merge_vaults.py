#!/usr/bin/env python3
"""
Vault Merge Script

Merges Providence vault into RealIcloudVault as a dedicated subfolder.
Preserves all frontmatter, rewrites Dataview queries, handles attachments.

Usage:
    python scripts/merge_vaults.py --dry-run   # Preview operations
    python scripts/merge_vaults.py              # Execute merge
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import frontmatter

# Default paths
PROVIDENCE_PATH = Path(
    "/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/Providence"
)
REALVAULT_PATH = Path(
    "/Users/nick/Library/Mobile Documents/iCloud~md~obsidian/Documents/RealIcloudVault"
)

# Folder mapping: Providence folder -> target subfolder under 04_Resources/07_Providence/
FOLDER_MAP = {
    "00-inbox": "04_Resources/07_Providence/00-inbox",
    "01-journal": "04_Resources/07_Providence/01-journal",
    "02-providence": "04_Resources/07_Providence/02-providence",
    "03-scripture": "04_Resources/07_Providence/03-scripture",
    "05-concepts": "04_Resources/07_Providence/05-concepts",
    "06-sources": "04_Resources/07_Providence/06-sources",
    "07-projects": "04_Resources/07_Providence/07-projects",
}

# Special mappings
TEMPLATE_TARGET = "05_Utils/Templates/Providence"
ATTACHMENT_TARGET = "05_Utils/Attachments/Providence"

# Skip these folders (no content to move or internal)
SKIP_FOLDERS = {"04-people", ".obsidian", ".git", ".smart-env"}

# Dataview FROM path rewrites for the Providence Dashboard
DATAVIEW_REWRITES = {
    '"00-inbox"': '"04_Resources/07_Providence/00-inbox"',
    '"01-journal"': '"04_Resources/07_Providence/01-journal"',
    '"02-providence"': '"04_Resources/07_Providence/02-providence"',
    '"03-scripture"': '"04_Resources/07_Providence/03-scripture"',
    '"04-people"': '"04_Resources/07_Providence/04-people"',
    '"05-concepts"': '"04_Resources/07_Providence/05-concepts"',
    '"06-sources"': '"04_Resources/07_Providence/06-sources"',
    '"07-projects"': '"04_Resources/07_Providence/07-projects"',
}


def inject_frontmatter(post: frontmatter.Post, file_path: Path) -> frontmatter.Post:
    """Add created/updated timestamps and source_vault tag to frontmatter."""
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

    if "created" not in post.metadata:
        post["created"] = mtime.strftime("%Y-%m-%dT%H:%M")
    if "updated" not in post.metadata:
        post["updated"] = mtime.strftime("%Y-%m-%dT%H:%M")

    # Add source_vault tag for traceability
    tags = post.metadata.get("tags", [])
    if isinstance(tags, list) and "source_vault/providence" not in tags:
        tags.append("source_vault/providence")
        post["tags"] = tags

    return post


def rewrite_dataview_paths(content: str) -> str:
    """Rewrite Dataview FROM paths in dashboard to new locations."""
    for old, new in DATAVIEW_REWRITES.items():
        content = content.replace(old, new)
    return content


def merge_vaults(source: Path, target: Path, dry_run: bool = False) -> dict:
    """Merge source vault into target vault."""
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "source": str(source),
        "target": str(target),
        "dry_run": dry_run,
        "operations": [],
        "skipped": [],
        "errors": [],
    }

    # 1. Process markdown notes in mapped folders
    for src_folder, tgt_folder in FOLDER_MAP.items():
        src_dir = source / src_folder
        if not src_dir.exists():
            continue

        for md_file in src_dir.rglob("*.md"):
            # Preserve subdirectory structure (e.g., 01-journal/2026/03/)
            relative = md_file.relative_to(src_dir)
            target_path = target / tgt_folder / relative

            if target_path.exists():
                manifest["skipped"].append(
                    {"file": str(relative), "reason": "already exists"}
                )
                continue

            try:
                post = frontmatter.load(md_file)
                post = inject_frontmatter(post, md_file)

                # Special handling for dashboard: rewrite Dataview paths
                if "Dashboard" in md_file.name:
                    post.content = rewrite_dataview_paths(post.content)

                op = {
                    "action": "copy_note",
                    "source": str(md_file.relative_to(source)),
                    "target": str(target_path.relative_to(target)),
                }

                if not dry_run:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(target_path, "w", encoding="utf-8") as f:
                        f.write(frontmatter.dumps(post))

                manifest["operations"].append(op)

            except Exception as e:
                manifest["errors"].append({"file": str(md_file), "error": str(e)})

    # 2. Copy CLAUDE.md from root
    claude_md = source / "CLAUDE.md"
    if claude_md.exists():
        target_claude = target / "04_Resources/07_Providence/CLAUDE.md"
        if not target_claude.exists():
            if not dry_run:
                target_claude.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(claude_md, target_claude)
            manifest["operations"].append(
                {
                    "action": "copy_file",
                    "source": "CLAUDE.md",
                    "target": "04_Resources/07_Providence/CLAUDE.md",
                }
            )

    # 3. Copy templates
    template_dir = source / "templates"
    if template_dir.exists():
        for tmpl in template_dir.glob("*.md"):
            target_tmpl = target / TEMPLATE_TARGET / tmpl.name
            if target_tmpl.exists():
                manifest["skipped"].append(
                    {"file": f"templates/{tmpl.name}", "reason": "already exists"}
                )
                continue

            if not dry_run:
                target_tmpl.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tmpl, target_tmpl)
            manifest["operations"].append(
                {
                    "action": "copy_template",
                    "source": f"templates/{tmpl.name}",
                    "target": f"{TEMPLATE_TARGET}/{tmpl.name}",
                }
            )

    # 4. Copy attachments
    attachment_dir = source / "attachments"
    if attachment_dir.exists():
        for att in attachment_dir.iterdir():
            if att.name.startswith("."):
                continue
            target_att = target / ATTACHMENT_TARGET / att.name
            if target_att.exists():
                manifest["skipped"].append(
                    {"file": f"attachments/{att.name}", "reason": "already exists"}
                )
                continue

            if not dry_run:
                target_att.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(att, target_att)
            manifest["operations"].append(
                {
                    "action": "copy_attachment",
                    "source": f"attachments/{att.name}",
                    "target": f"{ATTACHMENT_TARGET}/{att.name}",
                }
            )

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Merge Providence vault into RealIcloudVault"
    )
    parser.add_argument(
        "--source", type=Path, default=PROVIDENCE_PATH, help="Source vault path"
    )
    parser.add_argument(
        "--target", type=Path, default=REALVAULT_PATH, help="Target vault path"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print operations without executing"
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Error: Source vault not found at {args.source}")
        return 1
    if not args.target.exists():
        print(f"Error: Target vault not found at {args.target}")
        return 1

    prefix = "DRY RUN: " if args.dry_run else ""
    print(f"{prefix}Merging {args.source.name} -> {args.target.name}\n")

    manifest = merge_vaults(args.source, args.target, dry_run=args.dry_run)

    # Print summary
    print(f"Operations: {len(manifest['operations'])}")
    for op in manifest["operations"]:
        print(f"  {op['action']}: {op['source']} -> {op['target']}")

    if manifest["skipped"]:
        print(f"\nSkipped: {len(manifest['skipped'])}")
        for skip in manifest["skipped"]:
            print(f"  {skip['file']}: {skip['reason']}")

    if manifest["errors"]:
        print(f"\nErrors: {len(manifest['errors'])}")
        for err in manifest["errors"]:
            print(f"  {err['file']}: {err['error']}")

    # Save manifest
    if not args.dry_run:
        manifest_path = (
            args.target / "04_Resources/07_Providence/merge_manifest.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"\nManifest saved to {manifest_path}")

    return 0


if __name__ == "__main__":
    exit(main())
