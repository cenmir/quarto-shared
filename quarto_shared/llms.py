"""Rebuild Quarto's llms.txt markdown pages from the finished book HTML.

With `website: llms-txt: true`, Quarto writes a `.llms.md` twin of every page and an
`llms.txt` index. For a book the result is unusable as it stands:

- the page is converted in an HTML finalizer, before the book resolves its
  cross-references, so a reference reads `[eq-navier](#eq-navier)` with no number;
- pandoc's HTML reader does not recognise MathJax's `\\(..\\)` spans as math, so the TeX
  is escaped into nonsense (a `\\,` thin space becomes `\\\\`);
- iframes, i.e. the marimo configurators, vanish without a trace;
- the index titles keep pandoc's span markup for the chapter number.

So we redo the conversion on the final HTML, after the renumbering pass, for exactly the
pages Quarto chose (drafts excluded): the same chrome stripping and Quarto's own
`llms.lua` filter, plus `filters/llms-math.lua` for the math, and each iframe replaced by
a link to what it showed.
"""

import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from .cache import PageCache, file_hash, version_key

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

MATH_LUA = Path(__file__).resolve().parent.parent / "filters" / "llms-math.lua"

# commonmark_x writes math as $..$ and $$..$$; the rest is switched off so no
# pandoc-specific attribute syntax leaks into the output
TARGET = "commonmark_x-raw_html-raw_attribute-attributes-bracketed_spans-fenced_divs"

# The page chrome Quarto strips in its own extractMainContent
STRIP = [
    "#quarto-header", ".nav-footer", "#quarto-sidebar", "#quarto-margin-sidebar",
    "#quarto-search-results", ".sidebar", ".quarto-search", "nav.navbar",
    ".quarto-page-breadcrumbs", "script", "style", "link[rel='stylesheet']", "meta",
    "noscript", ".llms-hidden-content",
]


def _quarto_paths():
    quarto = shutil.which("quarto")
    if quarto is None:
        return None, None
    share = Path(quarto).resolve().parent.parent / "share"
    lua = share / "filters" / "llms" / "llms.lua"
    pandoc = next((share.parent / "bin" / "tools").rglob("pandoc"), None)
    return (pandoc, lua) if pandoc and lua.exists() else (None, None)


def _main_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in STRIP:
        for el in soup.select(selector):
            el.decompose()
    # A configurator means nothing as text; leave a link to it in its place
    for frame in soup.find_all("iframe"):
        p = soup.new_tag("p")
        a = soup.new_tag("a", href=frame.get("src", ""))
        src = frame.get("src", "")
        video = "youtube" in src or "vimeo" in src
        a.string = frame.get("title") or ("video" if video else "interactive figure")
        p.append("Video: " if video else "Interactive: ")
        p.append(a)
        frame.replace_with(p)
    main = soup.select_one("main") or soup.body
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>{main}</body></html>'


def _page_title(html_path: Path) -> str:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    h1 = soup.select_one("h1.title") or soup.find("h1")
    return " ".join(h1.get_text(" ").split()) if h1 else html_path.stem


def _fix_index(book_dir: Path, titles: PageCache) -> None:
    """Quarto rewrites llms.txt with every render, so every title is put back each
    time; parsing all pages for them took 7 s, hence the titles are cached by page hash."""
    index = book_dir / "llms.txt"
    lines = []
    for line in index.read_text(encoding="utf-8").splitlines():
        m = re.match(r"- \[.*\]\((.+\.llms\.md)\)$", line)
        if m:
            page = m.group(1).replace(".llms.md", ".html")
            digest = file_hash(book_dir / page)
            if digest:
                cached = titles.get(page)
                if not cached or cached[0] != digest:
                    cached = [digest, _page_title(book_dir / page)]
                    titles.put(page, cached)
                line = f"- [{cached[1]}]({m.group(1)})"
        lines.append(line)
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    titles.save()


def _convert(md: Path, pandoc: Path, llms_lua: Path) -> Optional[str]:
    """Rewrite one .llms.md from its finished HTML page. Returns a warning on failure."""
    html = md.with_name(md.name.replace(".llms.md", ".html"))
    result = subprocess.run(
        [str(pandoc), "-f", "html", "-t", TARGET, "--wrap=none",
         "--lua-filter", str(MATH_LUA), "--lua-filter", str(llms_lua)],
        input=_main_html(html.read_text(encoding="utf-8")),
        capture_output=True, text=True)
    if result.returncode != 0:
        return f"  Warning: llms conversion failed for {html.name}: {result.stderr.strip()}"
    md.write_text(result.stdout, encoding="utf-8")
    return None


def rebuild(book_dir: Path, files: Optional[Iterable[Path]] = None,
            cache_file: Optional[Path] = None) -> int:
    """Reconvert the .llms.md of every page in `files` (all pages when None).

    Does nothing unless Quarto wrote an llms.txt, i.e. unless llms-txt is switched on.
    With `cache_file` (see cache.py) a page is skipped when both its HTML and its
    .llms.md are as the last conversion left them. Both are checked: a re-render can
    end in the same HTML while Quarto has put its own .llms.md back.
    Returns the number of pages rewritten.
    """
    book_dir = Path(book_dir)
    if not (book_dir / "llms.txt").exists():
        return 0
    pandoc, llms_lua = _quarto_paths()
    if pandoc is None:
        print("  Warning: Quarto's pandoc or llms.lua not found, llms pages left as they are")
        return 0

    if files is None:
        pages = sorted(book_dir.rglob("*.llms.md"))
    else:
        pages = [Path(f).with_suffix(".llms.md") for f in files if Path(f).suffix == ".html"]
        pages = [p for p in pages if p.exists()]
    # an .llms.md whose page is gone (a renamed or deleted chapter) is left over from an
    # earlier build; there is no HTML to convert it from
    pages = [p for p in pages if p.with_name(p.name.replace(".llms.md", ".html")).exists()]

    html_of = lambda md: md.with_name(md.name.replace(".llms.md", ".html"))
    page_of = lambda md: html_of(md).resolve().relative_to(book_dir.resolve()).as_posix()
    # the result depends on the page, this code, both filters and the target format
    done = PageCache(cache_file, "llms", version_key(Path(__file__), MATH_LUA, llms_lua, TARGET))
    pages = [md for md in pages
             if done.get(page_of(md)) != [file_hash(html_of(md)), file_hash(md)]]

    failed = set()

    def report(md, warning):
        if warning:
            failed.add(md)
            (bar.write if bar else print)(warning)
        if bar:
            bar.update()

    bar = tqdm(total=len(pages), desc="  llms pages", unit="file", leave=False,
               disable=None) if tqdm and len(pages) > 2 else None
    if len(pages) <= 2:
        # one save in quarto preview; a pool costs more than it saves
        for md in pages:
            report(md, _convert(md, pandoc, llms_lua))
    else:
        # one pandoc per page; the pages are independent, so run them side by side
        with ProcessPoolExecutor() as pool:
            jobs = {pool.submit(_convert, md, pandoc, llms_lua): md for md in pages}
            for job in as_completed(jobs):
                report(jobs[job], job.result())
    if bar:
        bar.close()
    for md in pages:
        if md not in failed:
            done.put(page_of(md), [file_hash(html_of(md)), file_hash(md)])
    done.save()

    _fix_index(book_dir, PageCache(cache_file, "llms-titles", version_key(Path(__file__))))
    return len(pages)
