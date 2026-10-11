#!/usr/bin/env python3
"""Quarto post-render hook for sidebar/chapter renumbering.

Configured in a project's _quarto.yml as:

    project:
      type: book
      post-render:
        - python /home/<user>/quarto-shared/run_postprocess.py

Quarto does not expand `~` in post-render commands — use an absolute path.

Runs after every render, including quarto preview's incremental re-renders.

Quarto sets QUARTO_PROJECT_OUTPUT_FILES to the newline-separated list of
project-relative output paths just rendered. We pass that list through so
postprocess only re-walks the files that actually changed (~50-150ms per save
vs ~3-4s for a full sweep). On full builds Quarto includes every file in the
list, which is the same as the no-args path.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from quarto_shared import postprocess


def main():
    project_root = Path(os.environ.get("QUARTO_PROJECT_ROOT", ".")).resolve()
    book_dir = (project_root / os.environ.get("QUARTO_PROJECT_OUTPUT_DIR", "_book")).resolve()

    raw_files = os.environ.get("QUARTO_PROJECT_OUTPUT_FILES", "").strip()
    files = None
    if raw_files:
        # Quarto's paths can be project-relative or absolute; normalize both.
        files = []
        for entry in raw_files.splitlines():
            entry = entry.strip()
            if not entry:
                continue
            p = Path(entry)
            if not p.is_absolute():
                p = project_root / p
            files.append(p.resolve())

    ok = postprocess.run(project_root, book_dir, files=files)

    # After the renumbering, so the llms.txt pages carry the same numbers as the HTML.
    # A no-op unless the project sets `website: llms-txt: true`.
    from quarto_shared import llms
    llms.rebuild(book_dir, files=files)

    # Quarto moves each page's <name>_files/ folder into the output whole; the PNGs
    # that media.lua replaced with WebP would be deployed unused.
    from quarto_shared import media
    media.prune(book_dir, files)

    sys.exit(0 if ok else 1)


# postprocess and llms run their pages in a process pool; a pool that spawns its
# workers re-imports this script, which must then not run the hook again
if __name__ == "__main__":
    main()
