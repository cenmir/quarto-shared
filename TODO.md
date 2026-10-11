# TODO

## Move the add-ons developed in the books into quarto-shared

The mechanics book (`~/mechanics`) and the Python book (`~/python`) have grown
tools and filters that other books would want too. Each should move here, become
general, and be synced or imported like the existing filters and build logic.

- [x] `media.lua` + `quarto_shared/media.py`: images per output format, with a
      cache (first one moved; the pattern for the rest).
- [ ] MathJax and LaTeX macros (`\bm`, `\tr`, `\vec`): defined three times today,
      in mechanics' `_quarto.yml` header script, `macros.tex` and `macros.qmd`. One
      source here, generating the MathJax config and the LaTeX preamble, so the
      HTML and the PDF can never disagree.
- [ ] `_mathjax-sections.html` (mechanics): equation numbers per section.
- [ ] `_extensions/ute/mathjax3eqno` (mechanics): third-party extension; decide
      whether the shared theme ships it.
- [ ] `tools/svg_roundtrip.py` (mechanics): report hand edits to a generated SVG
      figure in data units.
- [ ] `tools/extract_katex_html.py` (mechanics): pull markdown with LaTeX out of
      old KaTeX-rendered course pages.
- [ ] Image credits appendix (mechanics `ImageCredits.qmd`): the pattern of credits
      in one appendix, not in captions; a template plus a check that every
      third-party image has an entry.
- [x] Animated GIF to WebM + MP4 in `media.py`/`media.lua`, and pruning of the
      unused notebook PNGs in the post-render hook.
- [ ] Video embedding (mechanics): MP4 under `graphics/` listed in
      `project.resources`, placed with raw `<video>` tags the filter does not
      see; decide whether those should go through `media.lua` too.
- [ ] marimo runner (mechanics `runMechanicsMarimo.py`, python `marimo/`): serving
      the books' marimo notebooks.
- [ ] Sweep `~/python` for book-specific filters and scripts not listed here.

## Quarto upgrades

- [ ] llms-txt: Quarto fixed the two bugs that `quarto_shared/llms.py` works
      around, the unnumbered book cross-references (quarto-cli #14975, fixed by
      PR #14977) and the escaped MathJax math (#14974, PR #14978). Both are on
      Quarto's main since 2026-10-02 and not yet released (latest is 1.11.5,
      2026-09-17; we run 1.10.18). After upgrading to the release that has them,
      render a book with the post-render rebuild switched off and compare its
      `.llms.md` pages with ours. Two jobs remain ours even then: iframes (the
      marimo configurators) replaced by links, and the index titles' span markup;
      check those before dropping `llms.py` or shrinking it to just those. From
      1.11 the `llms-txt` key moves from `website:` to `book:` (#14881).

## Print edition (PDF for a publisher)

- [ ] Decide case by case how each animation and interactive element appears in
      print. `media.lua` strips them for now and logs each one as a warning, so
      `quarto render --to pdf 2>&1 | grep media.lua` is the list to work through.
- [x] Print preflight: `media.py preflight BOOK.pdf` lists every image below
      300 ppi at its printed size, with its source file.
- [ ] Notebook plots are stored as PNG or SVG outputs, and Quarto does not
      re-execute notebooks; make sure every plot has a vector output for print.
- [ ] Code cells: hidden or shown in print (HTML folds them; the PDF prints them).
- [ ] `media.py warm`: convert the whole project in parallel before a first full
      build, if the serial first build is too slow.
