# quarto-shared

Shared infrastructure for Quarto book projects. This repository provides common theme files, Lua filters, and build utilities that can be shared across multiple Quarto projects.

## Quick Start: Create a New Book

```bash
# 1. Clone quarto-shared (one-time setup)
git clone https://github.com/cenmir/quarto-shared.git ~/quarto-shared

# 2. Initialize a new book project
python -m quarto_shared.init_book ~/fem --title "Finite Element Methods" --port 4202

# 3. Start working
cd ~/fem
quarto preview
```

The `init-book` command creates a complete project with:
- `_quarto.yml` configured for the shared theme
- `publish.py` build script
- `index.qmd` starter page
- All theme files synced from quarto-shared
- Git repository initialized

## Structure

```
quarto-shared/
├── theme/              # SCSS stylesheets
│   ├── dark.scss       # Dark mode theme
│   ├── light.scss      # Light mode theme
│   └── custom.scss     # Custom styling (remarks, examples, notes, etc.)
├── filters/            # Pandoc Lua filters
│   ├── hint.lua        # Hint/note box filter
│   ├── color-emphasis.lua  # Color and emphasis spans
│   ├── lastModified.lua    # Last modified date injection
│   └── media.lua       # Images per output format (WebP for HTML, full res for PDF)
├── includes/           # HTML includes and assets
│   ├── footer.html     # Page footer with last modified date
│   └── elsevier-vancouver.csl  # Citation style
└── quarto_shared/      # Python package
    ├── __init__.py
    ├── sync.py         # Sync theme files to projects
    ├── build.py        # Shared incremental build logic
    ├── postprocess.py  # Fix chapter numbering for books with parts
    ├── media.py        # Image converter behind media.lua
    └── init_book.py    # Initialize new projects
```

## Setup

Clone this repository as a sibling to your Quarto projects:

```bash
cd ~
git clone https://github.com/cenmir/quarto-shared.git quarto-shared
```

Your directory structure should look like:

```
~/
├── quarto-shared/      # This repo (REQUIRED)
├── python/             # Quarto project
├── mechanics/          # Quarto project
└── fem/                # Future project
```

## Creating a New Book Project

### Option 1: Using init-book (Recommended)

```bash
python -m quarto_shared.init_book ~/mybook \
    --title "My Book Title" \
    --port 4201 \
    --deploy-path "/var/www/mybook/"
```

Options:
- `--title, -t`: Book title (default: "My Quarto Book")
- `--port, -p`: Preview server port (default: 4200)
- `--deploy-path, -d`: Server deployment path (default: /var/www/mybook/)
- `--no-git`: Skip git initialization

### Option 2: Manual Setup

1. Create your Quarto project directory
2. Copy `publish.py` from an existing project
3. Create `_quarto.yml` (see template below)
4. Run `./publish.py --sync` to copy theme files

## Usage

### Building and Publishing

```bash
./publish.py              # Build changed files and deploy
./publish.py --full       # Force full rebuild
./publish.py --dry-run    # Show what would be built
./publish.py --no-deploy  # Build only, skip deployment
./publish.py --no-render  # Post-process and deploy only
./publish.py --git        # Push to git after build
./publish.py --sync       # Sync theme files only (no build)
./publish.py --no-sync-check  # Skip sync check before building
./publish.py --only Part/chapter.ipynb [...]  # Deploy only these rendered chapters
./publish.py -y ...       # Do not ask before copying to the server
./publish.py --exclude Part [...]  # Leave parts or chapters out of the published book
```

`--only` publishes finished chapters while others are still in progress. It renders
nothing: each chapter must already be rendered into `_book/` (by `quarto preview` or
`quarto render <file>`, which run the post-render hook), so it is safe while the preview
runs. It copies the page, its `.llms.md` twin, its `<stem>_files/` folder and the files it
references inside its own folder, plus any shared file (`site_libs`, `js`) the server
lacks, without `--delete`; every other page on the server stays as it was. The other
pages' sidebars and the search index are not updated, so a new chapter is reachable by its
link until the next full publish. Sidebar entries for pages that are not on the server
yet (chapters registered in `_quarto.yml` but unpublished) are left out of the published
copy, an emptied part with them, and the parts after it keep the numbers the live site
shows; `_book/` itself is not changed. Every publish asks before it copies anything to
the server (`-y` skips the question), and Ctrl+C before the copy deploys nothing. Add
`--dry-run` to see the file list first.

`--exclude` keeps parts that are not ready off the site (folders such as `Mechanisms`, or
single chapters), and has to be given on every publish that should leave them out. The
render runs on a temporary `_quarto.yml` without them, so the published sidebar has no
entries for them, the later parts keep consecutive numbers in titles, figures and
equations, and the search index leaves them out; the original `_quarto.yml` is put back
with its own modification time. The rsync passes `--exclude` with `--delete-excluded`, so
an excluded part that was published before is taken down. `_book/.publish-exclude.json`
records what the last publish render left out; when that differs, or when the preview
has rendered pages since, the next publish does a full render, and `--deploy-only` refuses.
A render that excludes refuses to start while `quarto preview` runs in the project, since
the preview watches `_quarto.yml` and serves `_book/`. `--only` refuses excluded chapters.

### Sync Behavior

Before each build, `publish.py` checks if theme files differ from `quarto-shared`. If differences are found, it prompts:

```
3 file(s) differ from quarto-shared:

  ~ dark.scss (modified)
  ~ custom.scss (modified)
  + hint.lua (new file)

Sync theme files from quarto-shared? [y/N]
```

This ensures all projects stay in sync while giving you control over when updates are applied.

## Updating Shared Files

When you want to change styles across ALL projects:

1. Edit files in `quarto-shared/theme/`, `quarto-shared/filters/`, etc.
2. Commit and push:
   ```bash
   cd ~/quarto-shared
   git add -A && git commit -m "Update theme" && git push
   ```
3. In each project, the next `./publish.py` run will detect changes and prompt to sync

### Multi-user Workflow

1. **User A** updates `quarto-shared` and pushes
2. **User B** pulls the latest:
   ```bash
   cd ~/quarto-shared && git pull
   ```
3. **User B** runs `./publish.py` in their project - sync prompt appears automatically

## Synced Files

| Source | Destination | Purpose |
|--------|-------------|---------|
| `theme/dark.scss` | `project/dark.scss` | Dark mode styling |
| `theme/light.scss` | `project/light.scss` | Light mode styling |
| `theme/custom.scss` | `project/custom.scss` | Custom components |
| `filters/hint.lua` | `project/hint.lua` | Hint box filter |
| `filters/color-emphasis.lua` | `project/color-emphasis.lua` | Color spans |
| `filters/lastModified.lua` | `project/lastModified.lua` | Last modified date |
| `filters/media.lua` | `project/media.lua` | Images per output format, see [Images per format](#images-per-format) |
| `includes/footer.html` | `project/footer.html` | Page footer |
| `includes/elsevier-vancouver.csl` | `project/elsevier-vancouver.csl` | Citation style |

## Custom CSS Classes

The theme provides several custom CSS classes:

### Hints (blurred until hover)
```markdown
::: {.hintbox}
This content is blurred until you hover over it.
:::
```

### Notes
```markdown
::: {.notebox}
Important information highlighted in a note box.
:::
```

### Emphasis
```markdown
[highlighted text]{.emphasis}
```

### Examples and Remarks (auto-numbered)
```markdown
::: {.Example}
Example content with automatic numbering.
:::

::: {.Remark}
Remark content with automatic numbering.
:::
```

### Colors
```markdown
[red text]{.red}
[blue text]{.blue}
[green text]{.green}
```

## _quarto.yml Template

```yaml
project:
  type: book
  output-dir: _book
  preview:
    port: 4200

book:
  title: "Your Book Title"
  author:
    - name: "Your Name"
      email: "your.email@example.com"
  page-navigation: true
  sidebar:
    search: true
    collapse-level: 1
  chapters:
    - index.qmd

filters:
  - lastModified.lua

format:
  html:
    theme:
      dark: [darkly, dark.scss, custom.scss]
      light: [flatly, light.scss, custom.scss]
    filters:
      - hint.lua
      - color-emphasis.lua
    toc: true
    code-fold: true
    include-after-body:
      - footer.html
    number-sections: true
```

## Architecture

### What Gets Synced (Static Files)

The `sync` module copies **static asset files** to each project:
- SCSS themes (`dark.scss`, `light.scss`, `custom.scss`)
- Lua filters (`hint.lua`, `color-emphasis.lua`, `lastModified.lua`)
- HTML includes (`footer.html`)
- JavaScript (`js/sidebar-state.js`)

These files are copied to each project directory and must be synced when updated.

### What Runs from quarto-shared (Python Logic)

The **Python code** (`build.py`, `sync.py`, `postprocess.py`) is **never copied** to projects.
Instead, each project's `publish.py` imports directly from `~/quarto-shared`:

```python
sys.path.insert(0, str(Path.home() / "quarto-shared"))
from quarto_shared import sync, build
```

This means:
- When you update Python code in quarto-shared, **all projects automatically get the new logic**
- No need to sync or copy Python files
- Single source of truth for build logic

### Post-Processing (Chapter Renumbering)

When using Quarto's `part:` structure, Quarto numbers chapters sequentially (1, 2, 3, ...)
instead of hierarchically (1.1, 1.2, 2.1, ...). The `postprocess` module automatically
fixes this after each build.

This runs automatically via `build.py` - no per-project configuration needed.

## Images per format

Sources keep their full-resolution images. `media.lua` swaps each local raster
image (PNG, JPEG, GIF, TIFF, BMP, WebP) for a WebP at screen resolution in HTML,
and each animated GIF for a looping, muted video: WebM (VP9, keeping any real
transparency) with an H.264 MP4 fallback for browsers without WebM. In PDF it
uses the full-resolution source, re-encoded to PNG only when LaTeX
cannot read the format. SVG passes through: Quarto already turns it into PDF for
LaTeX with `rsvg-convert`.

Converted files go to `<project>/_mediacache/<name>.<key>.<ext>`, where the key
hashes the source bytes together with the recipe. An edited image or a changed
recipe misses the cache, so nothing stale is served, and a hit costs one file
read and no process. The conversion itself is `quarto_shared/media.py` (Pillow),
which the filter runs only on a miss. Add `_mediacache/` to `.gitignore`.

Quarto moves each page's `<name>_files/` folder into the output whole, so the
PNGs that Jupyter wrote for a notebook's plots would be deployed beside the WebP
that replaced them. The post-render hook (`run_postprocess.py`) deletes those,
through `media.prune`, after every render; only images in `<name>_files/figure-html/`
that neither the page nor its `.llms.md` twin mentions are removed.

Outside HTML the filter also strips what cannot be printed: raw HTML (YouTube
iframes, `<video>`), video files, animated GIFs, and a figure left with only its
caption. Each strip is logged as a warning, so the render log lists every element
that still needs a print version.

```yaml
filters:
  - media.lua        # project-wide, so it sees both HTML and PDF
media:               # optional
  max-width: 1600    # pixels across of the HTML image
  quality: 82        # lossy WebP quality
```

`quarto preview` runs the filter on every re-render, so the HTML preview shows
the WebP. Preview watches documents, not images: after replacing an image, save
the chapter that shows it, and the new image gets a new key and a fresh WebP.

To try the converter on one image and compare it with the source:

```bash
python ~/quarto-shared/quarto_shared/media.py convert photo.jpg /tmp/photo --target html
```

prints what it wrote (`/tmp/photo.webp`, or `keep` when WebP would not be
smaller). `--max-width` and `--quality` take the same values as `media:` above.

Before a PDF goes to a publisher, list the photos it prints below 300 ppi:

```bash
python ~/quarto-shared/quarto_shared/media.py preflight _book/Book.pdf --project .
```

The list gives page, pixels, printed resolution and source file, and the command
exits 1 when it is not empty. Vector figures do not appear: they have no ppi.

The filter runs `python3` from the environment Quarto is started in, which must
have Pillow; set `QUARTO_SHARED_PYTHON` to use another interpreter and
`QUARTO_SHARED_ROOT` if quarto-shared is not at `~/quarto-shared`.

## Dependencies

- Python 3.8+
- PyYAML (`pip install pyyaml`)
- beautifulsoup4 and lxml (`pip install beautifulsoup4 lxml`) - for chapter renumbering
- Pillow with WebP support (`uv pip install pillow`) - for `media.lua`
- ffmpeg with libvpx-vp9 and libx264 - for animated GIFs
- pdfimages (`poppler-utils`) - for `media.py preflight`
- Quarto CLI

## License

MIT
