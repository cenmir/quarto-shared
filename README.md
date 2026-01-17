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
│   └── lastModified.lua    # Last modified date injection
├── includes/           # HTML includes and assets
│   ├── footer.html     # Page footer with last modified date
│   └── elsevier-vancouver.csl  # Citation style
└── quarto_shared/      # Python package
    ├── __init__.py
    ├── sync.py         # Sync theme files to projects
    ├── build.py        # Shared incremental build logic
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
```

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

## Dependencies

- Python 3.8+
- PyYAML (`pip install pyyaml`)
- Quarto CLI
- beautifulsoup4 and lxml (for postProcessing.py in each project)

## License

MIT
