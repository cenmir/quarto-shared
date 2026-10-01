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
from pathlib import Path
from typing import Iterable, Optional

from bs4 import BeautifulSoup

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


def _fix_index(book_dir: Path) -> None:
    index = book_dir / "llms.txt"
    lines = []
    for line in index.read_text(encoding="utf-8").splitlines():
        m = re.match(r"- \[.*\]\((.+\.llms\.md)\)$", line)
        if m:
            html = book_dir / m.group(1).replace(".llms.md", ".html")
            if html.exists():
                line = f"- [{_page_title(html)}]({m.group(1)})"
        lines.append(line)
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rebuild(book_dir: Path, files: Optional[Iterable[Path]] = None) -> int:
    """Reconvert the .llms.md of every page in `files` (all pages when None).

    Does nothing unless Quarto wrote an llms.txt, i.e. unless llms-txt is switched on.
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

    for md in pages:
        html = md.with_name(md.name.replace(".llms.md", ".html"))
        result = subprocess.run(
            [str(pandoc), "-f", "html", "-t", TARGET, "--wrap=none",
             "--lua-filter", str(MATH_LUA), "--lua-filter", str(llms_lua)],
            input=_main_html(html.read_text(encoding="utf-8")),
            capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Warning: llms conversion failed for {html.name}: {result.stderr.strip()}")
            continue
        md.write_text(result.stdout, encoding="utf-8")

    _fix_index(book_dir)
    return len(pages)
