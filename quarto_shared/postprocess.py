"""
postprocess.py - Post-process Quarto HTML output to fix chapter numbering.

When using Quarto's `part:` structure, Quarto numbers chapters sequentially
(1, 2, 3, ...) instead of hierarchically (1.1, 1.2, 2.1, ...). This module
fixes the numbering in the generated HTML files.

This is automatically called by build.py after rendering.
"""

import re
import yaml
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:
    from bs4 import BeautifulSoup, NavigableString
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# Quarto's numbered environments. Theorem-like ones render with a
# `.theorem-title strong`; the proof-like ones (proof, remark, solution) render
# with a `.proof-title em` instead, so both markups have to be renumbered.
ENVIRONMENT_KEYWORDS = (
    'Theorem|Lemma|Corollary|Proposition|Conjecture|Definition|'
    'Example|Exercise|Solution|Remark|Algorithm|Proof'
)


def generate_numbering_map(project_root: Path) -> Optional[Dict[str, str]]:
    """
    Parse _quarto.yml to create a mapping of chapter files to hierarchical numbers.

    Part-index files (e.g. ``Equilibrium/index.html``) map to the part number
    only (``"5"``); chapter files map to the hierarchical number (``"5.1"``).

    Args:
        project_root: Path to the Quarto project root

    Returns:
        Dict mapping HTML filename to correct chapter number, or None if no parts found
    """
    quarto_yml_path = project_root / '_quarto.yml'
    if not quarto_yml_path.exists():
        print("  No _quarto.yml found, skipping post-processing")
        return None

    with open(quarto_yml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    chapters_list = config.get('book', {}).get('chapters', [])

    # Check if any parts exist - if not, no post-processing needed
    has_parts = any(isinstance(item, dict) and 'part' in item for item in chapters_list)
    if not has_parts:
        return None

    mapping = {}
    chapter_counter = 0

    for item in chapters_list:
        if isinstance(item, str):
            if Path(item).stem.lower() not in ['index', 'preface', 'about']:
                chapter_counter += 1
                html_file = Path(item).with_suffix('.html').as_posix()
                mapping[html_file] = f"{chapter_counter}"

        elif isinstance(item, dict) and 'part' in item:
            chapter_counter += 1  # A part starts a new chapter number
            part_value = item.get('part')
            # When `part:` points at a file (e.g. Equilibrium/index.qmd),
            # map that html to the bare part number so the sidebar header
            # and the part landing page get a "5" prefix.
            if isinstance(part_value, str) and part_value.lower().endswith(('.qmd', '.ipynb', '.md')):
                part_html = Path(part_value).with_suffix('.html').as_posix()
                mapping[part_html] = f"{chapter_counter}"

            part_chapters = item.get('chapters', [])
            sub_chapter_counter = 1
            for sub_chapter in part_chapters:
                html_file = Path(sub_chapter).with_suffix('.html').as_posix()
                mapping[html_file] = f"{chapter_counter}.{sub_chapter_counter}"
                sub_chapter_counter += 1

    return mapping


def _rewrite_xrefs(soup, file_path: Path, book_dir_abs: Path,
                   numbering_map: Dict[str, str], correct_number: Optional[str]) -> None:
    """Give every cross-reference on the page the hierarchical number of its target.

    Runs on every page, including pages outside the numbering map (an appendix,
    say): those have no correct_number, so only their links to other pages are
    rewritten.
    """
    # This also patches xrefs on pages whose chapter renumbering was applied
    # in a previous run (the per-target lookup in post_process_html is gated
    # behind a "skip if already renumbered" check). Two cases it handles:
    #   (a) Sections without data-number (e.g. number-depth: 1), where
    #       Quarto's xref text is "Section <quarto-chapter>.<n>" but the
    #       target heading carries no data-number for that lookup to
    #       pick up.
    #   (b) Cross-page xrefs (href like "Other.html#anchor"), which that
    #       lookup skips because it only follows "#"-prefixed hrefs.
    # In both cases the visible text is "Keyword <chapter>.<rest>" and
    # we swap the chapter portion for the correct hierarchical number
    # (this page's correct_number for intra-page, numbering_map[target]
    # for cross-page). Idempotent: skips xrefs whose chapter already
    # matches target_correct.
    # an optional subfigure letter follows the number: "Figure 26.5 (a)"
    chapter_pattern = re.compile(
        r'^([A-Za-z\.]+[\s\xa0]+)?(\d+)((?:\.\d+)*)([\s\xa0]*\([a-z]+\))?$')
    for xref in soup.select('a.quarto-xref'):
        href = xref.get('href')
        if not href:
            continue
        number_span = xref.select_one('span')
        if not (number_span and number_span.string):
            continue
        current_span_text = number_span.string

        if href.startswith('#'):
            target_correct = correct_number
        else:
            try:
                target_abs = (file_path.parent / href).resolve(strict=False)
                lookup_key = target_abs.relative_to(book_dir_abs).as_posix().split('#')[0]
            except ValueError:
                continue
            target_correct = numbering_map.get(lookup_key)
        if not target_correct:
            continue

        m = chapter_pattern.match(current_span_text)
        if not m:
            continue
        keyword_prefix = m.group(1) or ''
        subfloat = m.group(4) or ''
        existing_number = current_span_text[len(keyword_prefix):len(current_span_text) - len(subfloat)]
        if existing_number == target_correct or existing_number.startswith(target_correct + '.'):
            continue
        rest = m.group(3)
        new_text = f"{keyword_prefix}{target_correct}{rest}{subfloat}"
        if new_text != current_span_text:
            number_span.string = new_text


def _progress(total: int, desc: str):
    """A tqdm bar on a terminal, nothing otherwise (Quarto may pipe the hook's output)."""
    if tqdm is None:
        return None
    return tqdm(total=total, desc=desc, unit="file", leave=False, disable=None)


def post_process_html(
    book_dir: Path,
    numbering_map: Dict[str, str],
    files: Optional[Iterable[Path]] = None,
) -> bool:
    """
    Parse HTML files in _book directory and fix chapter/section numbering.

    The files are independent of each other, so they are spread over a process
    pool. A file whose numbering is already right is not rewritten, which keeps
    its mtime and spares rsync from copying it again.

    Args:
        book_dir: Path to the _book output directory
        numbering_map: Dict mapping HTML filename to correct chapter number
        files: Optional explicit list of HTML files to process (must be inside
            book_dir). When None, walks the entire output dir. Used by the
            post-render hook to process only the files Quarto just rendered.

    Returns:
        True on success, False on failure
    """
    book_dir_abs = book_dir.resolve()
    if files is None:
        targets = sorted(book_dir.rglob('*.html'))
    else:
        targets = [Path(f) for f in files if Path(f).suffix == '.html']
    print(f"  Processing {len(targets)} HTML file(s)...")

    written = 0
    if len(targets) <= 2:
        # quarto preview re-renders one page per save; a pool costs more than it saves
        for file_path in targets:
            written += _process_file(file_path, book_dir, book_dir_abs, numbering_map)
    else:
        bar = _progress(len(targets), "  Renumbering")
        with ProcessPoolExecutor() as pool:
            jobs = [pool.submit(_process_file, f, book_dir, book_dir_abs, numbering_map)
                    for f in targets]
            for job in as_completed(jobs):
                written += job.result()
                if bar:
                    bar.update()
        if bar:
            bar.close()
    print(f"  Rewrote {written} of {len(targets)} file(s)")
    return True


def _process_file(file_path: Path, book_dir: Path, book_dir_abs: Path,
                  numbering_map: Dict[str, str]) -> bool:
    """Renumber one page. Returns True when the file was rewritten."""
    relative_path_posix = file_path.relative_to(book_dir).as_posix()
    original = file_path.read_text(encoding='utf-8')
    soup = BeautifulSoup(original, 'lxml')

    def save() -> bool:
        html = str(soup)
        if html == original:
            return False
        file_path.write_text(html, encoding='utf-8')
        return True

    # Every page carries the whole sidebar; searching inside it rather than the
    # whole document is most of the speed of this pass.
    sidebar = soup.find(id='quarto-sidebar') or soup

    # String-title parts (e.g. `part: "Preliminaries"` in _quarto.yml)
    # have no href, so they can't be looked up in the numbering_map by
    # path. Derive each part's number from the first chapter inside the
    # section by resolving its href against numbering_map ("4.1" -> "4")
    # and inject a chapter-number span. We use numbering_map directly
    # rather than reading the chapter-number text already in the sidebar
    # because at this point that text is still Quarto's raw global number.
    for section_li in sidebar.select('.sidebar-item-section'):
        header_link = section_li.select_one(
            '.sidebar-item-container > a.sidebar-link[data-bs-toggle="collapse"]'
        )
        if not header_link:
            continue
        menu_text = header_link.find(class_='menu-text')
        if not menu_text:
            continue

        part_number = None
        for child_link in section_li.select('ul.sidebar-section a.sidebar-link[href]'):
            href = child_link.get('href', '')
            if not href or href.startswith(('http://', 'https://', '#')):
                continue
            try:
                target_abs = (file_path.parent / href).resolve(strict=False)
                lookup_key = target_abs.relative_to(book_dir_abs).as_posix().split('#')[0]
            except ValueError:
                continue
            if lookup_key in numbering_map:
                part_number = numbering_map[lookup_key].split('.')[0]
                break
        if not part_number:
            continue

        existing_num = menu_text.find(class_='chapter-number')
        if existing_num:
            existing_num.string = part_number
        else:
            title_text = menu_text.get_text()
            menu_text.clear()
            num_span = soup.new_tag('span', attrs={'class': 'chapter-number'})
            num_span.string = part_number
            title_span_new = soup.new_tag('span', attrs={'class': 'chapter-title'})
            title_span_new.string = title_text
            menu_text.append(num_span)
            menu_text.append(NavigableString('\xa0'))
            menu_text.append(title_span_new)

    # Universal Sidebar and Nav Renumbering (applied to every page)
    nav_links = (sidebar.select('.sidebar-item-container > a.sidebar-link')
                 + soup.select('.nav-page-previous a.pagination-link, .nav-page-next a.pagination-link'))
    for link in nav_links:
        href = link.get('href')
        if href and not href.startswith(('http://', 'https://', '#')):
            try:
                target_abs = (file_path.parent / href).resolve(strict=False)
                target_rel_posix = target_abs.relative_to(book_dir_abs).as_posix()
                lookup_key = target_rel_posix.split('#')[0]

                if lookup_key in numbering_map:
                    number_span = link.find(class_='chapter-number')
                    title_span = link.find(class_='chapter-title')
                    if number_span:
                        number_span.string = numbering_map[lookup_key]
                    elif title_span and lookup_key not in numbering_map:
                        if link.find(class_='chapter-number'):
                            link.find(class_='chapter-number').decompose()
                    else:
                        # Part header in the sidebar: Quarto emits
                        # <span class="menu-text">Title</span> with no
                        # chapter-number span. Inject one so parts get a
                        # "5 Equilibrium" prefix matching their children.
                        menu_text = link.find(class_='menu-text')
                        if menu_text and not menu_text.find(class_='chapter-number'):
                            title_text = menu_text.get_text()
                            menu_text.clear()
                            num_span = soup.new_tag('span', attrs={'class': 'chapter-number'})
                            num_span.string = numbering_map[lookup_key]
                            title_span_new = soup.new_tag('span', attrs={'class': 'chapter-title'})
                            title_span_new.string = title_text
                            menu_text.append(num_span)
                            menu_text.append(NavigableString('\xa0'))
                            menu_text.append(title_span_new)
            except ValueError:
                continue

    # Page-Specific Renumbering
    correct_number = numbering_map.get(relative_path_posix)
    _rewrite_xrefs(soup, file_path, book_dir_abs, numbering_map, correct_number)
    if not correct_number:
        main_title_span = soup.select_one('#quarto-document-content h1.title .chapter-number')
        if main_title_span:
            main_title_span.decompose()
        return save()

    # Determine the incorrect number from the first section found
    first_section = soup.select_one('section[data-number]')
    incorrect_number = None
    if first_section:
        incorrect_number = first_section['data-number'].split('.')[0]

    if not incorrect_number:
        main_title = soup.select_one('h1.title[data-number]')
        if main_title:
            incorrect_number = main_title['data-number'].split('.')[0]

    if not incorrect_number and soup.title and soup.title.string:
        title_match = re.match(r'^([\d\.]+)', soup.title.string.strip())
        if title_match:
            incorrect_number = title_match.group(1)

    # Nothing to renumber, or already correctly numbered
    if not incorrect_number or incorrect_number == correct_number:
        return save()

    incorrect_prefix = f"{incorrect_number}."
    correct_prefix = f"{correct_number}."

    # Update main H1 title
    main_title_h1 = soup.select_one('#quarto-document-content h1.title')
    if main_title_h1:
        if main_title_h1.has_attr('data-number'):
            main_title_h1['data-number'] = correct_number
        main_title_span = main_title_h1.select_one('.chapter-number')
        if main_title_span:
            main_title_span.string = correct_number
        else:
            new_span = soup.new_tag("span", attrs={"class": "chapter-number"})
            new_span.string = correct_number
            main_title_h1.insert(0, new_span)
            main_title_h1.insert(1, NavigableString('\xa0'))

    # Update browser <title> tag
    if soup.title and soup.title.string:
        soup.title.string = re.sub(
            rf'^{re.escape(incorrect_number)}(?:\.[\d\.]+)*[\s\xa0]+',
            f'{correct_number}\xa0',
            soup.title.string
        )

    # Update breadcrumbs
    for breadcrumb_span in soup.select('.quarto-page-breadcrumbs .breadcrumb-item:last-child .chapter-number'):
        breadcrumb_span.string = correct_number

    # Update section headings
    for section in soup.select('section[data-number]'):
        original_data_number = section['data-number']
        if original_data_number.startswith(incorrect_prefix):
            new_data_number = correct_prefix + '.'.join(original_data_number.split('.')[1:])
            section['data-number'] = new_data_number

            header = section.find(['h2','h3','h4','h5','h6'], recursive=False)
            if header:
                header['data-number'] = new_data_number
                number_span = header.select_one('.header-section-number')
                if number_span:
                    number_span.string = new_data_number

    # Update right-hand Table of Contents
    for toc_item in soup.select('#TOC .nav-link'):
        number_span = toc_item.select_one('.header-section-number')
        if number_span and number_span.string and number_span.string.strip().startswith(incorrect_prefix):
            original_toc_number = number_span.string.strip()
            new_toc_number = correct_prefix + '.'.join(original_toc_number.split('.')[1:])
            number_span.string = new_toc_number

    # Update Figure, Table, and Listing captions
    for caption in soup.select('.quarto-float-caption'):
        caption_text_node = None
        for node in caption.contents:
            if isinstance(node, NavigableString) and node.strip():
                caption_text_node = node
                break

        if caption_text_node:
            original_text = str(caption_text_node).lstrip()
            new_text = re.sub(
                rf'^(Figure|Table|Listing)([\s\xa0]){re.escape(incorrect_number)}\.',
                rf'\g<1>\g<2>{correct_number}.',
                original_text
            )
            if new_text != original_text:
                caption_text_node.replace_with(new_text)

    # Update Theorem-like environment titles
    for theorem_title in soup.select('.theorem-title strong'):
        original_text = theorem_title.get_text(strip=True)
        new_text = re.sub(
            rf'^({ENVIRONMENT_KEYWORDS})([\s\xa0]+){re.escape(incorrect_number)}\.',
            rf'\g<1>\g<2>{correct_number}.',
            original_text
        )
        if new_text != original_text:
            theorem_title.string = new_text

    # Update proof-like environment titles (proof, remark, solution). The
    # number sits inside an <em> and the trailing period outside it, so the
    # text to rewrite is "Remark 12.3" with no terminal dot.
    for proof_title in soup.select('.proof-title'):
        title_node = proof_title.find('em') or proof_title
        original_text = title_node.get_text(strip=True)
        new_text = re.sub(
            rf'^({ENVIRONMENT_KEYWORDS})([\s\xa0]+){re.escape(incorrect_number)}\.',
            rf'\g<1>\g<2>{correct_number}.',
            original_text
        )
        if new_text != original_text:
            title_node.string = new_text

    # Update MathJax equation numbers
    for math_span in soup.select('span.math.display'):
        if math_span.string:
            original_latex = math_span.string
            new_latex = re.sub(
                rf'(\\tag\{{){re.escape(incorrect_prefix)}([^\}}]+\}})',
                rf'\g<1>{correct_prefix}\g<2>',
                original_latex
            )
            if new_latex != original_latex:
                math_span.string = new_latex

    for math_span in soup.select('span.math.inline[data-eq-number]'):
        original_eq_number = math_span['data-eq-number']
        if original_eq_number.startswith(incorrect_prefix):
            new_eq_number = correct_prefix + '.'.join(original_eq_number.split('.')[1:])
            math_span['data-eq-number'] = new_eq_number

            next_sibling = math_span.find_next_sibling('span', class_='paren-eq-no')
            if next_sibling and next_sibling.string:
                next_sibling.string = f"({new_eq_number})"

    # Update cross-references
    for xref in soup.select('a.quarto-xref'):
        href = xref.get('href')
        if not (href and href.startswith('#')):
            continue

        target_id = href[1:]
        target_element = soup.find(id=target_id)
        if not target_element:
            continue

        current_text = xref.get_text(strip=True)
        if not current_text:
            continue

        ref_parts = current_text.split(maxsplit=1)

        ref_type = None
        if len(ref_parts) == 2:
            ref_type = ref_parts[0]
        elif len(ref_parts) == 1:
            id_type_map = {
                'fig-': 'Figure', 'tbl-': 'Table', 'lst-': 'Listing',
                'sec-': 'Section', 'eq-': 'Equation', 'thm-': 'Theorem',
                'lem-': 'Lemma', 'cor-': 'Corollary', 'prp-': 'Proposition',
                'cnj-': 'Conjecture', 'def-': 'Definition', 'exm-': 'Example',
                'exr-': 'Exercise', 'sol-': 'Solution', 'rem-': 'Remark',
                'alg-': 'Algorithm'
            }
            for prefix, type_name in id_type_map.items():
                if target_id.startswith(prefix):
                    ref_type = type_name
                    break

        if not ref_type:
            continue

        correct_target_number = None

        if target_element.has_attr('data-number'):
            correct_target_number = target_element['data-number']
        elif 'quarto-float' in target_element.get('class', []):
            caption = target_element.select_one('.quarto-float-caption')
            if caption:
                caption_text = caption.get_text().strip()
                match = re.search(
                    rf'^(?:Figure|Table|Listing)[\s\xa0]+({re.escape(correct_number)}\.\d+)',
                    caption_text
                )
                if match:
                    correct_target_number = match.group(1)
        elif 'theorem' in target_element.get('class', []):
            theorem_title = target_element.select_one('.theorem-title strong')
            if theorem_title:
                title_text = theorem_title.get_text(strip=True)
                match = re.search(
                    rf'^(?:{ENVIRONMENT_KEYWORDS})[\s\xa0]+({re.escape(correct_number)}\.\d+)',
                    title_text
                )
                if match:
                    correct_target_number = match.group(1)
        elif 'proof' in target_element.get('class', []):
            # Read the number back from the title fixed above. Without this
            # branch the fallback below would descend into the environment
            # and pick up the tag of the first equation inside it.
            proof_title = target_element.select_one('.proof-title')
            if proof_title:
                title_node = proof_title.find('em') or proof_title
                match = re.search(
                    rf'^(?:{ENVIRONMENT_KEYWORDS})[\s\xa0]+({re.escape(correct_number)}\.\d+)',
                    title_node.get_text(strip=True)
                )
                if match:
                    correct_target_number = match.group(1)
        else:
            math_span = target_element.select_one('span.math[data-eq-number]')
            if math_span:
                correct_target_number = math_span.get('data-eq-number')
            else:
                math_display_span = target_element.select_one('span.math.display')
                if math_display_span and math_display_span.string:
                    tag_match = re.search(r'\\tag\{([^}]+)\}', math_display_span.string)
                    if tag_match:
                        correct_target_number = tag_match.group(1)
                else:
                    tag_span = target_element.select_one('.tag')
                    if tag_span and tag_span.string:
                        raw_tag = tag_span.string.strip('()')
                        if raw_tag.startswith(incorrect_prefix):
                            correct_target_number = correct_prefix + '.'.join(raw_tag.split('.')[1:])
                        else:
                            correct_target_number = raw_tag

        if correct_target_number:
            number_span = xref.select_one('span')
            if number_span:
                current_number = number_span.get_text(strip=True)
                if current_number != correct_target_number:
                    number_span.string = correct_target_number
            else:
                new_text = f"{ref_type}\xa0{correct_target_number}"
                if current_text != new_text:
                    xref.clear()
                    xref.string = new_text

    # Final sweep for plain-text references
    main_content = soup.select_one('#quarto-document-content')
    if main_content:
        number_pattern = re.compile(rf'^{re.escape(incorrect_number)}\.[\d\.]*$')
        keywords = ['Figure', 'Table', 'Listing', 'Section', 'Equation', 'Eq.',
                   'Theorem', 'Lemma', 'Corollary', 'Proposition', 'Conjecture',
                   'Definition', 'Example', 'Exercise', 'Solution', 'Remark', 'Algorithm']

        # PASS 1: Handle split elements like "Figure <span>15.3</span>"
        text_nodes = main_content.find_all(
            string=lambda t: not t.find_parent(
                ['a', 'pre', 'code', 'script', 'style', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                 '.quarto-float-caption', '.tag', 'title']
            )
        )

        for text_node in text_nodes:
            stripped_text = str(text_node).rstrip()
            if any(stripped_text.endswith(kw) for kw in keywords):
                target_node = None
                next_elem = text_node.next_sibling

                if next_elem and next_elem.name == 'span' and next_elem.string:
                    target_node = next_elem.string

                if target_node:
                    number_text = target_node.strip()
                    if number_pattern.match(number_text):
                        new_number = correct_prefix + '.'.join(number_text.split('.')[1:])
                        if number_text != new_number:
                            target_node.replace_with(new_number)

        # PASS 2: Handle combined text nodes like "Figure 15.3"
        keyword_and_number_pattern = re.compile(
            rf'(?P<keyword>{"|".join(keywords)})'
            rf'(?P<space>[\s\xa0]+)'
            rf'(?P<number>{re.escape(incorrect_number)}\.[\d\.]*)'
        )
        text_nodes = main_content.find_all(
            string=lambda t: not t.find_parent(
                ['a', 'pre', 'code', 'script', 'style', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                 '.quarto-float-caption', '.tag', 'title', 'span']
            )
        )
        for text_node in text_nodes:
            original_text = str(text_node)

            def replacer(m):
                number = m.group('number')
                new_number = correct_prefix + '.'.join(number.split('.')[1:])
                if number != new_number:
                    return m.group('keyword') + m.group('space') + new_number
                return m.group(0)

            modified_text = keyword_and_number_pattern.sub(replacer, original_text)

            if modified_text != original_text:
                text_node.replace_with(modified_text)

    return save()


def run(
    project_root: Path,
    book_dir: Path,
    files: Optional[Iterable[Path]] = None,
) -> bool:
    """
    Run post-processing on a Quarto book.

    This is the main entry point called by build.py and the post-render hook.

    Args:
        project_root: Path to the Quarto project root (contains _quarto.yml)
        book_dir: Path to the _book output directory
        files: Optional explicit list of HTML files to process. Used by the
            quarto preview post-render hook for incremental updates. When None,
            processes every HTML file under book_dir.

    Returns:
        True on success (or if no post-processing needed), False on failure
    """
    if not HAS_BS4:
        print("  Warning: beautifulsoup4/lxml not installed, skipping post-processing")
        print("  Install with: pip install beautifulsoup4 lxml")
        return True

    if not book_dir.exists():
        print("  Warning: _book directory not found, skipping post-processing")
        return True

    numbering_map = generate_numbering_map(project_root)

    if numbering_map is None:
        print("  No part: structure found, skipping chapter renumbering")
        return True

    return post_process_html(book_dir, numbering_map, files=files)
