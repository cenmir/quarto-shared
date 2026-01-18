"""
sync.py - Sync theme files from quarto-shared to Quarto projects.

Provides utilities to detect changes and copy theme files.
"""

import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# Resolve quarto-shared root (parent of quarto_shared package)
SHARED_ROOT = Path(__file__).parent.parent.resolve()

# Files to sync, organized by source directory -> target location
SYNC_MAP = {
    "theme": [
        "dark.scss",
        "light.scss",
        "custom.scss",
    ],
    "filters": [
        "hint.lua",
        "color-emphasis.lua",
        "lastModified.lua",
    ],
    "includes": [
        "footer.html",
        "elsevier-vancouver.csl",
    ],
    "js": [
        "sidebar-state.js",
    ],
}


def file_hash(path: Path) -> str:
    """Compute MD5 hash of a file."""
    if not path.exists():
        return ""
    return hashlib.md5(path.read_bytes()).hexdigest()


def get_sync_status(project_dir: Path) -> Dict[str, Tuple[str, str, bool]]:
    """
    Compare files between quarto-shared and project.

    Returns dict mapping filename -> (shared_hash, project_hash, differs)
    """
    project_dir = Path(project_dir).resolve()
    status = {}

    for source_subdir, files in SYNC_MAP.items():
        for filename in files:
            shared_path = SHARED_ROOT / source_subdir / filename
            # All synced files go to project root
            project_path = project_dir / filename

            shared_hash = file_hash(shared_path)
            project_hash = file_hash(project_path)
            differs = shared_hash != project_hash

            status[filename] = (shared_hash, project_hash, differs)

    return status


def has_changes(project_dir: Path) -> bool:
    """Check if any theme files differ between quarto-shared and project."""
    status = get_sync_status(project_dir)
    return any(differs for _, _, differs in status.values())


def get_changed_files(project_dir: Path) -> List[str]:
    """Get list of files that differ."""
    status = get_sync_status(project_dir)
    return [name for name, (_, _, differs) in status.items() if differs]


def print_diff_summary(project_dir: Path) -> None:
    """Print a summary of what differs."""
    status = get_sync_status(project_dir)
    changed = [(name, sh, ph) for name, (sh, ph, differs) in status.items() if differs]

    if not changed:
        print("All theme files are in sync.")
        return

    print(f"\n{len(changed)} file(s) differ from quarto-shared:\n")
    for name, shared_hash, project_hash in changed:
        if not project_hash:
            print(f"  + {name} (new file)")
        elif not shared_hash:
            print(f"  ? {name} (not in quarto-shared)")
        else:
            print(f"  ~ {name} (modified)")
    print()


def apply(project_dir: Path, files: List[str] = None, dry_run: bool = False) -> List[str]:
    """
    Copy files from quarto-shared to project.

    Args:
        project_dir: Path to the Quarto project
        files: Specific files to sync (default: all changed files)
        dry_run: If True, just report what would be done

    Returns:
        List of files that were (or would be) copied
    """
    project_dir = Path(project_dir).resolve()

    if files is None:
        files = get_changed_files(project_dir)

    if not files:
        return []

    copied = []

    # Build reverse map: filename -> source subdir
    file_to_subdir = {}
    for subdir, filenames in SYNC_MAP.items():
        for filename in filenames:
            file_to_subdir[filename] = subdir

    for filename in files:
        if filename not in file_to_subdir:
            print(f"  Warning: {filename} not in sync map, skipping")
            continue

        subdir = file_to_subdir[filename]
        source = SHARED_ROOT / subdir / filename
        dest = project_dir / filename

        if not source.exists():
            print(f"  Warning: {source} does not exist, skipping")
            continue

        if dry_run:
            print(f"  Would copy: {filename}")
        else:
            shutil.copy2(source, dest)
            print(f"  Copied: {filename}")

        copied.append(filename)

    return copied


def interactive_sync(project_dir: Path) -> bool:
    """
    Check for changes and prompt user to sync.

    Returns True if sync was performed or not needed, False if user declined.
    """
    project_dir = Path(project_dir).resolve()

    if not has_changes(project_dir):
        return True

    print_diff_summary(project_dir)

    response = input("Sync theme files from quarto-shared? [y/N] ").strip().lower()

    if response == 'y':
        apply(project_dir)
        print("Theme files synced.")
        return True
    else:
        print("Sync skipped.")
        return False
