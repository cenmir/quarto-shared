"""
build.py - Shared incremental build logic for Quarto book projects.

Provides the core build functionality that can be imported and customized
by individual project publish.py scripts.
"""

import re
import yaml
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional, TextIO, Callable
from datetime import datetime
from dataclasses import dataclass, field

__version__ = "1.1.0"

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


# --- Publishing single chapters ---------------------------------------------------------

_ASSET_ATTR = re.compile(r'(?:src|href|poster|data)="([^"#?]+)[^"]*"')


def chapter_files(config: BuildConfig, source: Path) -> tuple:
    """The files in _book/ that make up one rendered chapter.

    Returns ``(files, shared, pages)``: ``files`` are the page itself, its ``.llms.md``
    twin, its ``<stem>_files/`` folder (plots of code cells) and every local file the page
    references inside its own folder tree (figures, videos, data); ``shared`` are the
    other local files it references (``site_libs``, ``js``), which belong to the whole
    site; ``pages`` are the other pages it links to.
    """
    page = source_to_output(config, source)
    files, shared, pages = [page], set(), set()
    twin = page.with_suffix('.llms.md')
    if twin.exists():
        files.append(twin)
    extra = page.parent / f'{page.stem}_files'
    if extra.is_dir():
        files += sorted(p for p in extra.rglob('*') if p.is_file())
    own = page.parent.resolve()
    for ref in sorted(set(_ASSET_ATTR.findall(page.read_text(encoding='utf-8')))):
        if ref.startswith(('http:', 'https:', 'mailto:', 'data:', '//', '/')):
            continue
        target = (page.parent / ref).resolve()
        if not target.is_file():
            continue
        rel = os.path.relpath(target, config.book_dir)
        if target.suffix == '.html':
            if target != page.resolve():
                pages.add(rel)
        elif own not in target.parents:
            shared.add(rel)
        elif target not in [f.resolve() for f in files]:
            files.append(target)
    return files, sorted(shared), sorted(pages)


def confirm(question: str) -> bool:
    """Ask a yes/no question on the terminal; anything but y/yes, Ctrl+C or a closed
    input counts as no."""
    try:
        answer = input(f"{question} [y/N] ")
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    return answer.strip().lower() in ('y', 'yes')


def prune_sidebar(html: str, page_rel: str, absent: List[str]) -> tuple:
    """Remove the sidebar entries of ``html`` (the page at ``page_rel`` in _book/) that link
    to the pages in ``absent``, and any sidebar part left empty. Returns the new html and
    the number of entries removed. Used for a chapter published on its own while other
    chapters listed in _quarto.yml are not on the server yet."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    gone = {os.path.normpath(a) for a in absent}
    base = os.path.dirname(page_rel)
    removed = 0
    for section in soup.select('#quarto-sidebar li.sidebar-item-section'):
        num = section.select_one('span.chapter-number')
        if num is not None:
            section['data-part-number'] = num.get_text().strip().split('.')[0]
    for a in soup.select('#quarto-sidebar a.sidebar-link[href]'):
        target = os.path.normpath(os.path.join(base, a['href'].split('#')[0]))
        if target in gone:
            item = a.find_parent('li', class_='sidebar-item')
            if item is not None:
                item.decompose()
                removed += 1
    dropped = []                      # the numbers of the parts left empty
    for section in soup.select('#quarto-sidebar li.sidebar-item-section'):
        if not section.select('ul li.sidebar-item'):
            dropped.append(section.get('data-part-number'))
            section.decompose()
    dropped = sorted(int(d) for d in dropped if d and d.isdigit())
    if dropped:
        # the parts after a dropped one move up, so their chapters get the numbers the
        # other published pages show
        for span in soup.select('span.chapter-number'):
            m = re.match(r'(\d+)(\..*)?$', span.get_text().strip())
            if m:
                major = int(m.group(1))
                shift = sum(1 for d in dropped if d < major)
                if shift:
                    span.string = f"{major - shift}{m.group(2) or ''}"
    for section in soup.select('[data-part-number]'):
        del section['data-part-number']
    return str(soup), removed


def deploy_chapters(config: BuildConfig, sources: List[Path], dry_run: bool = False,
                    yes: bool = False) -> bool:
    """Deploy only the given chapters from the existing _book/, without rendering.

    For publishing one finished chapter while others are in progress: the chapter must
    already be rendered (by ``quarto preview`` or ``quarto render <file>``, both of which
    run the post-render hook). Only its own files are copied, with no ``--delete``, so
    every other page on the server stays as it was. The other pages' sidebars and the
    search index are not updated, so a new chapter is reachable by its link until the
    next full publish.
    """
    global _log_file
    _log_file = open(config.log_file, 'a', encoding='utf-8')
    try:
        log("=" * 60)
        log("Publishing single chapters (--only)")
        log("=" * 60)
        quarto_config = parse_quarto_yml(config)
        listed = {f.resolve() for f in get_book_files(config, quarto_config)}
        all_files, prune = [], {}
        for src in sources:
            src = (config.project_root / src).resolve()
            rel = src.relative_to(config.project_root)
            page = source_to_output(config, src)
            if src not in listed:
                log(f"WARNING: {rel} is not listed in _quarto.yml")
            if not page.exists():
                log(f"ERROR: {page.relative_to(config.project_root)} does not exist; render {rel} first")
                return False
            if src.exists() and get_mtime(src) > get_mtime(page):
                log(f"WARNING: {rel} is newer than its page; save it in the preview or render it first")
            files, shared, pages = chapter_files(config, src)
            # a shared file the server lacks (a theme rebuilt since the last full publish
            # gives the stylesheet a new hashed name) is copied; existing ones stay
            missing = [config.book_dir / s for s in shared if not (config.deploy_dir / s).exists()]
            log(f"{rel}: {len(files)} file(s) of its own, {len(shared)} shared, "
                f"links to {len(pages)} other page(s)")
            for f in files + missing:
                log(f"  + {os.path.relpath(f, config.book_dir)}")
            for s in shared:
                if config.book_dir / s not in missing:
                    log(f"  = {s} (on the server already)")
            absent = [s for s in pages if not (config.deploy_dir / s).exists()]
            for s in absent:
                log(f"  - {s}: not on the server, its sidebar entry is left out")
            prune[page] = absent
            all_files += files + missing
        rel_paths = [os.path.relpath(f, config.book_dir) for f in all_files]
        if dry_run:
            log("DRY RUN: would copy the files above to " + str(config.deploy_dir))
            return True
        # stage a copy, so that the sidebar of the published page can be pruned without
        # touching _book/, which the preview keeps serving
        import shutil
        import tempfile
        stage = Path(tempfile.mkdtemp(prefix='publish-only-'))
        for f, rel in zip(all_files, rel_paths):
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, stage / rel)
        for page, absent in prune.items():
            if absent:
                rel = os.path.relpath(page, config.book_dir)
                html, n = prune_sidebar((stage / rel).read_text(encoding='utf-8'), rel, absent)
                (stage / rel).write_text(html, encoding='utf-8')
                log(f"{rel}: {n} sidebar entr{'y' if n == 1 else 'ies'} to unpublished pages left out")
        if not yes and not confirm(f"Publish {len(all_files)} file(s) to {config.deploy_dir}?"):
            log("Not published: nothing was deployed")
            shutil.rmtree(stage, ignore_errors=True)
            return False
        try:
            subprocess.run(['sudo', '-v'], check=True)
        except (KeyboardInterrupt, subprocess.CalledProcessError):
            print()
            log("Aborted before copying: nothing was deployed")
            shutil.rmtree(stage, ignore_errors=True)
            return False
        try:
            if subprocess.run(['sudo', 'chgrp', '-R', 'www-data', str(stage)]).returncode:
                log("ERROR: Failed to set permissions!")
                return False
            result = subprocess.run(['sudo', 'rsync', '-a', '--relative'] + rel_paths
                                    + [str(config.deploy_dir) + '/'], cwd=stage)
        except KeyboardInterrupt:
            print()
            log("Interrupted during the copy: some files may be new, some old; run it again")
            return False
        finally:
            subprocess.run(['sudo', 'rm', '-rf', str(stage)])
        if result.returncode:
            log("ERROR: Deployment failed!")
            return False
        log(f"Deployed {len(all_files)} file(s)")
        return True
    finally:
        _log_file.close()
        _log_file = None


@dataclass
class BuildOptions:
    """Options for a build run."""
    full: bool = False
    no_deploy: bool = False
    no_render: bool = False
    dry_run: bool = False
    git: bool = False
    deploy_only: bool = False  # Skip render, just post-process and deploy
    yes: bool = False          # Deploy without asking first


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

        # Set permissions and deploy, once the user has said so
        if not options.yes and not confirm(f"Publish _book/ to {config.deploy_dir}?"):
            log("Not published: the build is in _book/, nothing was deployed")
            return False
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
