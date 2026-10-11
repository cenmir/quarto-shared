"""
build.py - Shared incremental build logic for Quarto book projects.

Provides the core build functionality that can be imported and customized
by individual project publish.py scripts.
"""

import yaml
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional, TextIO, Callable
from datetime import datetime
from dataclasses import dataclass, field

__version__ = "1.0.0"

# Global log file handle
_log_file: Optional[TextIO] = None


@dataclass
class BuildConfig:
    """Configuration for a Quarto build."""
    project_root: Path
    deploy_dir: Path
    ssh_key: Path = field(default_factory=lambda: Path.home() / ".ssh" / "ed25519_mechanics")
    log_file: Path = None

    # Auxiliary files that trigger full rebuild when changed
    auxiliary_files: List[str] = field(default_factory=lambda: [
        "custom.scss",
        "dark.scss",
        "light.scss",
        "footer.html",
        "hint.lua",
        "color-emphasis.lua",
        "lastModified.lua",
        "references.bib",
    ])

    # Optional callbacks
    post_process: Optional[Callable[[], bool]] = None

    def __post_init__(self):
        self.project_root = Path(self.project_root).resolve()
        self.deploy_dir = Path(self.deploy_dir)
        if self.log_file is None:
            self.log_file = self.project_root / "build.log"

    @property
    def quarto_yml(self) -> Path:
        return self.project_root / "_quarto.yml"

    @property
    def book_dir(self) -> Path:
        return self.project_root / "_book"


def log(message: str):
    """Print timestamped log message to console and log file."""
    global _log_file
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def parse_quarto_yml(config: BuildConfig) -> dict:
    """Load and parse _quarto.yml."""
    with open(config.quarto_yml, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_book_files(config: BuildConfig, quarto_config: dict) -> List[Path]:
    """Extract all source files from chapters structure in _quarto.yml."""
    chapters = quarto_config.get('book', {}).get('chapters', [])
    files = []

    def extract(items):
        for item in items:
            if isinstance(item, str):
                files.append(config.project_root / item)
            elif isinstance(item, dict):
                if 'chapters' in item:
                    extract(item['chapters'])

    extract(chapters)
    return files


def source_to_output(config: BuildConfig, source: Path) -> Path:
    """Map source file (.qmd/.ipynb) to HTML output path in _book/."""
    relative = source.relative_to(config.project_root)
    return config.book_dir / relative.with_suffix('.html')


def get_mtime(path: Path) -> float:
    """Get modification time, return 0 if file doesn't exist."""
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0


def needs_full_rebuild(config: BuildConfig, book_files: List[Path]) -> tuple:
    """
    Check if full rebuild is needed.
    Returns (needs_rebuild, reason).
    """
    # No output directory = needs full rebuild
    if not config.book_dir.exists():
        return True, "No _book/ directory found"

    # Get oldest output file mtime
    output_mtimes = []
    for source in book_files:
        output = source_to_output(config, source)
        if output.exists():
            output_mtimes.append(get_mtime(output))

    if not output_mtimes:
        return True, "No output files found in _book/"

    oldest_output_mtime = min(output_mtimes)

    # Check if _quarto.yml is newer than oldest output
    if get_mtime(config.quarto_yml) > oldest_output_mtime:
        return True, "_quarto.yml has been modified"

    # Check auxiliary files
    for aux_name in config.auxiliary_files:
        aux_path = config.project_root / aux_name
        if aux_path.exists() and get_mtime(aux_path) > oldest_output_mtime:
            return True, f"{aux_name} has been modified"

    return False, ""


def find_changed_files(config: BuildConfig, book_files: List[Path]) -> List[Path]:
    """Find source files newer than their HTML output."""
    changed = []
    for source in book_files:
        if not source.exists():
            log(f"Warning: Source file not found: {source.relative_to(config.project_root)}")
            continue
        output = source_to_output(config, source)
        if get_mtime(source) > get_mtime(output):
            changed.append(source)
    return changed


def render_full(config: BuildConfig) -> bool:
    """Execute full quarto render."""
    log("Running full Quarto render...")
    result = subprocess.run(
        ['quarto', 'render', '--to', 'html'],
        cwd=config.project_root
    )
    return result.returncode == 0


def render_files(config: BuildConfig, files: List[Path]) -> bool:
    """Render specific files incrementally."""
    success = True
    for source in files:
        relative = source.relative_to(config.project_root)
        log(f"Rendering: {relative}")
        result = subprocess.run(
            ['quarto', 'render', str(relative), '--to', 'html'],
            cwd=config.project_root
        )
        if result.returncode != 0:
            log(f"ERROR: Failed to render {relative}")
            success = False
    return success


def has_post_render_hook(quarto_config: dict) -> bool:
    """True when _quarto.yml runs quarto-shared's run_postprocess.py after rendering."""
    hooks = quarto_config.get('project', {}).get('post-render') or []
    if isinstance(hooks, str):
        hooks = [hooks]
    return any('run_postprocess.py' in hook for hook in hooks)


def run_post_processing(config: BuildConfig) -> bool:
    """Run post-processing to fix chapter numbering for books with parts."""
    # Use custom post-processor if configured
    if config.post_process:
        log("Running custom post-processing...")
        return config.post_process()

    # Use built-in postprocess module
    log("Running post-processing (chapter renumbering)...")
    from . import postprocess
    return postprocess.run(config.project_root, config.book_dir)


def set_permissions(config: BuildConfig) -> bool:
    """Set group ownership to www-data."""
    log("Setting permissions (chgrp www-data)...")
    result = subprocess.run(
        ['sudo', 'chgrp', '-R', 'www-data', str(config.book_dir)]
    )
    return result.returncode == 0


def deploy(config: BuildConfig) -> bool:
    """Rsync to deployment directory."""
    log(f"Deploying to {config.deploy_dir}...")
    # one overall progress line instead of a line per copied file
    result = subprocess.run(
        ['sudo', 'rsync', '-a', '--delete', '--info=progress2', '--no-inc-recursive',
         str(config.book_dir) + '/', str(config.deploy_dir)]
    )
    return result.returncode == 0


def git_push(config: BuildConfig) -> bool:
    """Push to git remote using specified SSH key."""
    if not config.ssh_key.exists():
        log(f"ERROR: SSH key not found: {config.ssh_key}")
        return False

    log("Pushing to git remote...")

    # Set up SSH command with the specific key
    git_ssh_command = f"ssh -i {config.ssh_key} -o IdentitiesOnly=yes"
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = git_ssh_command

    # Run git push
    result = subprocess.run(
        ["git", "push"],
        cwd=config.project_root,
        env=env
    )
    return result.returncode == 0


@dataclass
class BuildOptions:
    """Options for a build run."""
    full: bool = False
    no_deploy: bool = False
    no_render: bool = False
    dry_run: bool = False
    git: bool = False
    deploy_only: bool = False  # Skip render, just post-process and deploy


def run(config: BuildConfig, options: BuildOptions = None) -> bool:
    """
    Execute the build pipeline.

    Returns True on success, False on failure.
    """
    global _log_file

    if options is None:
        options = BuildOptions()

    # Open log file
    _log_file = open(config.log_file, 'a', encoding='utf-8')

    try:
        log("=" * 60)
        log("Incremental Quarto Build")
        log("=" * 60)

        # Parse configuration
        quarto_config = parse_quarto_yml(config)
        book_files = get_book_files(config, quarto_config)
        log(f"Found {len(book_files)} book files in _quarto.yml")

        # Skip rendering if --no-render or --deploy-only is set
        if options.no_render or options.deploy_only:
            log("Skipping quarto render" + (" (--deploy-only)" if options.deploy_only else " (--no-render)"))
            # Prompt for sudo password upfront if deploying
            if not options.no_deploy:
                subprocess.run(['sudo', '-v'])
        else:
            # Determine build strategy
            if options.full:
                do_full_rebuild = True
                reason = "Forced via --full flag"
            else:
                do_full_rebuild, reason = needs_full_rebuild(config, book_files)

            if do_full_rebuild:
                log(f"Full rebuild needed: {reason}")
                if options.dry_run:
                    log("DRY RUN: Would run full quarto render")
                else:
                    # Prompt for sudo password upfront
                    if not options.no_deploy:
                        subprocess.run(['sudo', '-v'])
                    if not render_full(config):
                        log("ERROR: Full render failed!")
                        return False
            else:
                changed = find_changed_files(config, book_files)
                if not changed:
                    log("No changes detected - nothing to build")
                    if options.git:
                        if not git_push(config):
                            log("ERROR: Git push failed!")
                            return False
                    return True
                else:
                    log(f"Found {len(changed)} changed file(s):")
                    for f in changed:
                        log(f"  - {f.relative_to(config.project_root)}")

                    if options.dry_run:
                        log("DRY RUN: Would render only the above files")
                    else:
                        # Prompt for sudo password upfront
                        if not options.no_deploy:
                            subprocess.run(['sudo', '-v'])
                        if not render_files(config, changed):
                            log("ERROR: Incremental render failed!")
                            return False

        if options.dry_run:
            log("DRY RUN: Would run post-processing, set permissions, and deploy")
            return True

        # The post-render hook has already processed every page Quarto rendered,
        # and the pages it did not render were processed when they were. Without
        # a render (--no-render, --deploy-only) or without the hook, sweep them all.
        rendered = not (options.no_render or options.deploy_only)
        if rendered and has_post_render_hook(quarto_config):
            log("Post-processing done by the post-render hook")
        elif not run_post_processing(config):
            log("ERROR: Post-processing failed!")
            return False

        if options.no_deploy:
            log("Build complete (deployment skipped via --no-deploy)")
            return True

        # Set permissions and deploy
        if not set_permissions(config):
            log("ERROR: Failed to set permissions!")
            return False

        if not deploy(config):
            log("ERROR: Deployment failed!")
            return False

        # Git push if requested
        if options.git:
            if not git_push(config):
                log("ERROR: Git push failed!")
                return False

        log("=" * 60)
        log("Build and deployment complete!")
        log("=" * 60)
        return True

    finally:
        _log_file.close()
        _log_file = None
