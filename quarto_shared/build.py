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
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, TextIO, Callable
from datetime import datetime
from dataclasses import dataclass, field

__version__ = "1.2.0"

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


def is_excluded(rel: str, exclude: List[str]) -> bool:
    """True when the project-relative path ``rel`` is one of ``exclude`` or lies under one
    of them (an entry ``Mechanisms`` or ``Mechanisms/`` excludes the whole folder)."""
    rel = rel.replace(os.sep, '/')
    for e in exclude:
        e = e.replace(os.sep, '/').rstrip('/')
        if rel == e or rel.startswith(e + '/'):
            return True
    return False


_CHAPTER_LINE = re.compile(r'^\s*-\s+(?:file:\s*)?["\']?([^"\'#\s]+\.(?:qmd|ipynb|md))["\']?\s*(?:#.*)?$')
_PART_LINE = re.compile(r'^(\s*)-\s+part:')


def exclude_from_quarto_yml(text: str, exclude: List[str]) -> str:
    """The text of _quarto.yml without the excluded chapters, and without every part whose
    chapters are all excluded. Works on the text so that comments, quoting and YAML 1.2
    scalars stay as Quarto reads them; the result is checked by parsing it."""
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        m = _PART_LINE.match(lines[i])
        if m:
            indent = len(m.group(1))
            j = i + 1
            while j < len(lines) and (not lines[j].strip()
                                      or len(lines[j]) - len(lines[j].lstrip()) > indent):
                j += 1
            block = lines[i:j]
            files = [c.group(1) for c in map(_CHAPTER_LINE.match, block) if c]
            if files and all(is_excluded(f, exclude) for f in files):
                trailing = [l for l in block[::-1] if not l.strip()]   # keep the blank lines
                out += trailing[:1]
                i = j
                continue
            out.append(lines[i])
            i += 1
            continue
        c = _CHAPTER_LINE.match(lines[i])
        if c and is_excluded(c.group(1), exclude):
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return ''.join(out)


def preview_running(config: BuildConfig) -> bool:
    """True when a ``quarto preview`` of this project is running (it serves _book/ and
    watches _quarto.yml)."""
    try:
        pids = subprocess.run(['pgrep', '-f', 'quarto preview'], capture_output=True,
                              text=True).stdout.split()
    except FileNotFoundError:
        return False
    for pid in pids:
        try:
            if Path(os.readlink(f'/proc/{pid}/cwd')).resolve() == config.project_root:
                return True
        except OSError:
            continue
    return False


EXCLUDE_MARKER = '.publish-exclude.json'


def exclusion_state(config: BuildConfig) -> Optional[dict]:
    """What the last render by publish left out, and when it finished, or None."""
    try:
        return json.loads((config.book_dir / EXCLUDE_MARKER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_exclusion_state(config: BuildConfig, exclude: List[str]):
    (config.book_dir / EXCLUDE_MARKER).write_text(
        json.dumps({'exclude': sorted(exclude), 'time': time.time()}), encoding='utf-8')


def exclusion_stale(config: BuildConfig, exclude: List[str]) -> str:
    """Why _book/ cannot be published as it is with ``exclude``, or '' when it can: the
    last render left out something else, or a page was rendered since (by the preview,
    with the full _quarto.yml), or excluded pages are present."""
    state = exclusion_state(config)
    if not exclude and not (state and state['exclude']):
        return ''
    if sorted(exclude) != (state or {}).get('exclude', []):
        return "the last render left out " + (', '.join(state['exclude']) if state and state['exclude'] else 'nothing')
    t0 = state['time'] + 5
    for html in config.book_dir.rglob('*.html'):
        rel = html.relative_to(config.book_dir).as_posix()
        if is_excluded(rel, exclude):
            return f"{rel} is in _book/ (rendered by the preview)"
        if get_mtime(html) > t0:
            return f"{rel} was rendered after the last publish render (by the preview?)"
    return ''


@contextmanager
def quarto_yml_without(config: BuildConfig, exclude: List[str]):
    """Replace _quarto.yml by a copy without the excluded chapters for the duration of the
    block, and put the original back afterwards, with its own modification time so that
    the incremental build does not see a change."""
    if not exclude:
        yield
        return
    original = config.quarto_yml.read_bytes()
    stat = config.quarto_yml.stat()
    text = exclude_from_quarto_yml(original.decode('utf-8'), exclude)
    left = [f for f in get_book_files(config, yaml.safe_load(text))
            if is_excluded(f.relative_to(config.project_root).as_posix(), exclude)]
    if left:
        raise RuntimeError(f"could not remove {left[0]} from _quarto.yml")
    try:
        config.quarto_yml.write_text(text, encoding='utf-8')
        yield
    finally:
        config.quarto_yml.write_bytes(original)
        os.utime(config.quarto_yml, ns=(stat.st_atime_ns, stat.st_mtime_ns))


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


def deploy(config: BuildConfig, exclude: List[str] = ()) -> bool:
    """Rsync to deployment directory. Excluded paths are neither copied nor kept on the
    server (``--delete-excluded``), so a part that was published before is taken down."""
    log(f"Deploying to {config.deploy_dir}...")
    filters = []
    for e in list(exclude) + [EXCLUDE_MARKER]:
        e = e.replace(os.sep, '/').rstrip('/')
        filters += ['--exclude', '/' + e]
    if exclude:
        filters.append('--delete-excluded')
    # one overall progress line instead of a line per copied file
    result = subprocess.run(
        ['sudo', 'rsync', '-a', '--delete', '--info=progress2', '--no-inc-recursive']
        + filters + [str(config.book_dir) + '/', str(config.deploy_dir)]
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
                    yes: bool = False, exclude: List[str] = ()) -> bool:
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
            if is_excluded(rel.as_posix(), exclude):
                log(f"ERROR: {rel} is excluded from publishing ({', '.join(exclude)})")
                return False
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
    exclude: List[str] = field(default_factory=list)   # paths left out of the published book


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
        exclude = list(options.exclude)
        if exclude:
            book_files = [f for f in book_files
                          if not is_excluded(f.relative_to(config.project_root).as_posix(), exclude)]
            log(f"Leaving out {', '.join(exclude)}: {len(book_files)} book files are published")
        stale = exclusion_stale(config, exclude)
        rendering = not (options.no_render or options.deploy_only)
        if exclude and rendering and not options.dry_run and preview_running(config):
            log("ERROR: quarto preview is running. A render that leaves out parts swaps "
                "_quarto.yml and rewrites _book/; stop the preview first")
            return False

        # Skip rendering if --no-render or --deploy-only is set
        if not rendering and stale:
            log(f"ERROR: _book/ cannot be published without {', '.join(exclude)}: {stale}. "
                "Run without --deploy-only/--no-render")
            return False
        if not rendering:
            log("Skipping quarto render" + (" (--deploy-only)" if options.deploy_only else " (--no-render)"))
            # Prompt for sudo password upfront if deploying
            if not options.no_deploy:
                subprocess.run(['sudo', '-v'])
        else:
            # Determine build strategy
            if options.full:
                do_full_rebuild = True
                reason = "Forced via --full flag"
            elif stale:
                do_full_rebuild = True
                reason = f"Leaving out {', '.join(exclude)}, and {stale}"
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
                    with quarto_yml_without(config, exclude):
                        ok = render_full(config)
                    if not ok:
                        log("ERROR: Full render failed!")
                        return False
                    # pages of the excluded parts left in _book/ by earlier renders
                    import shutil
                    for e in exclude:
                        target = config.book_dir / e.rstrip('/')
                        if target.is_dir():
                            shutil.rmtree(target)
                        for page in config.book_dir.glob(e.rstrip('/') + '.*'):
                            page.unlink()
                    write_exclusion_state(config, exclude)
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
                        with quarto_yml_without(config, exclude):
                            ok = render_files(config, changed)
                        if not ok:
                            log("ERROR: Incremental render failed!")
                            return False
                        write_exclusion_state(config, exclude)

        if options.dry_run:
            log("DRY RUN: Would run post-processing, set permissions, and deploy")
            return True

        # The post-render hook has already processed every page Quarto rendered,
        # and the pages it did not render were processed when they were. Without
        # a render (--no-render, --deploy-only) or without the hook, sweep them all.
        rendered = not (options.no_render or options.deploy_only)
        if rendered and has_post_render_hook(quarto_config):
            log("Post-processing done by the post-render hook")
        else:
            # the renumbering reads _quarto.yml, so it sees the same chapters as the render
            with quarto_yml_without(config, exclude):
                ok = run_post_processing(config)
            if not ok:
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

        if not deploy(config, exclude):
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
