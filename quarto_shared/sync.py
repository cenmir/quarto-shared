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
# Files go to project root unless source dir is in PRESERVE_SUBDIR
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
        "welcome-gallery.js",
    ],
}

# Source directories that should preserve their subdir in the target project
PRESERVE_SUBDIR = {"js"}


def file_hash(path: Path) -> str:
    """Compute MD5 hash of a file."""
    if not path.exists():
        return ""
    return hashlib.md5(path.read_bytes()).hexdigest()


def get_target_path(project_dir: Path, source_subdir: str, filename: str) -> Path:
    """Get the target path for a file in the project directory."""
    if source_subdir in PRESERVE_SUBDIR:
        return project_dir / source_subdir / filename
    return project_dir / filename


def get_display_name(source_subdir: str, filename: str) -> str:
    """Get display name for a file (includes subdir if preserved)."""
    if source_subdir in PRESERVE_SUBDIR:
        return f"{source_subdir}/{filename}"
    return filename


def get_sync_status(project_dir: Path) -> Dict[str, Tuple[str, str, bool, str]]:
    """
    Compare files between quarto-shared and project.

    Returns dict mapping display_name -> (shared_hash, project_hash, differs, source_subdir)
    """
    project_dir = Path(project_dir).resolve()
    status = {}

    for source_subdir, files in SYNC_MAP.items():
        for filename in files:
            shared_path = SHARED_ROOT / source_subdir / filename
            project_path = get_target_path(project_dir, source_subdir, filename)

            shared_hash = file_hash(shared_path)
            project_hash = file_hash(project_path)
            differs = shared_hash != project_hash

            display_name = get_display_name(source_subdir, filename)
            status[display_name] = (shared_hash, project_hash, differs, source_subdir)

    return status


def has_changes(project_dir: Path) -> bool:
    """Check if any theme files differ between quarto-shared and project."""
    status = get_sync_status(project_dir)
    return any(differs for _, _, differs, _ in status.values())


def get_changed_files(project_dir: Path) -> List[str]:
    """Get list of files that differ (returns display names)."""
    status = get_sync_status(project_dir)
    return [name for name, (_, _, differs, _) in status.items() if differs]


def print_diff_summary(project_dir: Path) -> None:
    """Print a summary of what differs."""
    project_dir = Path(project_dir).resolve()
    status = get_sync_status(project_dir)
    changed = [(name, sh, ph, sd) for name, (sh, ph, differs, sd) in status.items() if differs]

    if not changed:
        print("All theme files are in sync.")
        return

    print(f"\n{len(changed)} file(s) differ from quarto-shared:\n")
    for name, shared_hash, project_hash, source_subdir in changed:
        if not project_hash:
            print(f"  + {name} (new file)")
        elif not shared_hash:
            print(f"  ? {name} (not in quarto-shared)")
        else:
            # Determine which copy is newer
            shared_path = SHARED_ROOT / source_subdir / name.split("/")[-1]
            project_path = get_target_path(project_dir, source_subdir, name.split("/")[-1])
            shared_mtime = shared_path.stat().st_mtime
            project_mtime = project_path.stat().st_mtime
            if shared_mtime > project_mtime:
                hint = "quarto-shared is newer"
            elif project_mtime > shared_mtime:
                hint = "local is newer"
            else:
                hint = "modified"
            print(f"  ~ {name} ({hint})")
    print()


def apply(project_dir: Path, files: List[str] = None, dry_run: bool = False) -> List[str]:
    """
    Copy files from quarto-shared to project.

    Args:
        project_dir: Path to the Quarto project
        files: Specific files to sync (default: all changed files, as display names)
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

    # Build reverse map: display_name -> (source_subdir, filename)
    display_to_info = {}
    for subdir, filenames in SYNC_MAP.items():
        for filename in filenames:
            display_name = get_display_name(subdir, filename)
            display_to_info[display_name] = (subdir, filename)

    for display_name in files:
        if display_name not in display_to_info:
            print(f"  Warning: {display_name} not in sync map, skipping")
            continue

        subdir, filename = display_to_info[display_name]
        source = SHARED_ROOT / subdir / filename
        dest = get_target_path(project_dir, subdir, filename)

        if not source.exists():
            print(f"  Warning: {source} does not exist, skipping")
            continue

        if dry_run:
            print(f"  Would copy: {display_name}")
        else:
            # Create parent directory if needed
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            print(f"  Copied: {display_name}")

        copied.append(display_name)

    return copied


def push_to_shared(project_dir: Path, files: list[str] = None, dry_run: bool = False) -> list[str]:
    """
    Copy files from the project back to quarto-shared.

    Args:
        project_dir: Path to the Quarto project
        files: Specific files to push (default: all changed files, as display names)
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

    display_to_info = {}
    for subdir, filenames in SYNC_MAP.items():
        for filename in filenames:
            display_name = get_display_name(subdir, filename)
            display_to_info[display_name] = (subdir, filename)

    for display_name in files:
        if display_name not in display_to_info:
            print(f"  Warning: {display_name} not in sync map, skipping")
            continue

        subdir, filename = display_to_info[display_name]
        source = get_target_path(project_dir, subdir, filename)
        dest = SHARED_ROOT / subdir / filename

        if not source.exists():
            print(f"  Warning: {source} does not exist, skipping")
            continue

        if dry_run:
            print(f"  Would push: {display_name}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            print(f"  Pushed: {display_name}")

        copied.append(display_name)

    return copied


def interactive_sync(project_dir: Path) -> bool:
    """
    Check for changes and prompt user to sync in the appropriate direction.

    For each changed file, compares modification times to determine direction:
    - quarto-shared is newer -> offer to pull into project
    - project is newer -> offer to push to quarto-shared

    Returns True if sync was performed or not needed, False if user declined.
    """
    project_dir = Path(project_dir).resolve()

    if not has_changes(project_dir):
        return True

    status = get_sync_status(project_dir)
    pull_files = []  # shared is newer
    push_files = []  # local is newer

    for name, (shared_hash, project_hash, differs, source_subdir) in status.items():
        if not differs:
            continue
        if not project_hash:
            pull_files.append(name)
        elif not shared_hash:
            push_files.append(name)
        else:
            shared_path = SHARED_ROOT / source_subdir / name.split("/")[-1]
            project_path = get_target_path(project_dir, source_subdir, name.split("/")[-1])
            if shared_path.stat().st_mtime > project_path.stat().st_mtime:
                pull_files.append(name)
            else:
                push_files.append(name)

    synced = False

    if pull_files:
        print(f"\n{len(pull_files)} file(s) newer in quarto-shared:\n")
        for f in pull_files:
            print(f"  ~ {f}")
        print()
        response = input("Apply quarto-shared updates to your project? [y/N] ").strip().lower()
        if response == 'y':
            apply(project_dir, files=pull_files)
            print("Pulled from quarto-shared.")
            synced = True
        else:
            print("Pull skipped.")

    if push_files:
        print(f"\n{len(push_files)} file(s) newer in your project:\n")
        for f in push_files:
            print(f"  ~ {f}")
        print()
        response = input("Update quarto-shared with your changes? [y/N] ").strip().lower()
        if response == 'y':
            push_to_shared(project_dir, files=push_files)
            print("Pushed to quarto-shared.")
            synced = True
        else:
            print("Push skipped.")

    return synced
