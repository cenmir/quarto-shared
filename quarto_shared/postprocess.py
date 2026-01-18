"""
postprocess.py - Post-process Quarto HTML output to fix chapter numbering.

When using Quarto's `part:` structure, Quarto numbers chapters sequentially
(1, 2, 3, ...) instead of hierarchically (1.1, 1.2, 2.1, ...). This module
fixes the numbering in the generated HTML files.

This is automatically called by build.py after rendering.
"""

import json
import re
import yaml
from pathlib import Path
from typing import Dict, Optional

try:
    from bs4 import BeautifulSoup, NavigableString
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


def generate_numbering_map(project_root: Path) -> Optional[Dict[str, str]]:
    """
    Parse _quarto.yml to create a mapping of chapter files to hierarchical numbers.

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
            part_chapters = item.get('chapters', [])
            sub_chapter_counter = 1
            for sub_chapter in part_chapters:
                html_file = Path(sub_chapter).with_suffix('.html').as_posix()
                mapping[html_file] = f"{chapter_counter}.{sub_chapter_counter}"
                sub_chapter_counter += 1

    print("  Generated numbering map:")
    print(json.dumps(mapping, indent=4))
    return mapping


def post_process_html(book_dir: Path, numbering_map: Dict[str, str]) -> bool:
    """
    Parse all HTML files in _book directory and fix chapter/section numbering.

    Args:
        book_dir: Path to the _book output directory
        numbering_map: Dict mapping HTML filename to correct chapter number

    Returns:
        True on success, False on failure
    """
    book_dir_abs = book_dir.resolve()
    print("  Processing HTML files...")

    for file_path in book_dir.rglob('*.html'):
        relative_path_posix = file_path.relative_to(book_dir).as_posix()

        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'lxml')

        # Universal Sidebar and Nav Renumbering (applied to every page)
        for link in soup.select('#quarto-sidebar .sidebar-item-container > a.sidebar-link, .nav-page-previous a.pagination-link, .nav-page-next a.pagination-link'):
            href = link.get('href')
            if href and not href.startswith(('http://', 'https://', '#')):
                try:
                    target_abs = (file_path.parent / href).resolve(strict=False)
                    target_rel_posix = target_abs.relative_to(book_dir_abs).as_posix()
                    lookup_key = target_rel_posix.split('#')[0]

                    if lookup_key in numbering_map:
                        number_span = link.select_one('.chapter-number')
                        title_span = link.select_one('.chapter-title')
                        if number_span:
                            number_span.string = numbering_map[lookup_key]
                        elif title_span and lookup_key not in numbering_map:
                            if link.select_one('.chapter-number'):
                                link.select_one('.chapter-number').decompose()
                except ValueError:
                    continue

        # Page-Specific Renumbering
        correct_number = numbering_map.get(relative_path_posix)
        if not correct_number:
            main_title_span = soup.select_one('#quarto-document-content h1.title .chapter-number')
            if main_title_span:
                main_title_span.decompose()
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            continue

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

        if not incorrect_number:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            continue

        # Skip if already correctly numbered
        if incorrect_number == correct_number:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            continue

        print(f"    {relative_path_posix}: {incorrect_number} -> {correct_number}")

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
                rf'^(Theorem|Lemma|Corollary|Proposition|Conjecture|Definition|Example|Exercise|Solution|Remark|Algorithm)([\s\xa0]+){re.escape(incorrect_number)}\.',
                rf'\g<1>\g<2>{correct_number}.',
                original_text
            )
            if new_text != original_text:
                theorem_title.string = new_text

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
            target_element = soup.select_one(f'#{target_id}')
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
                        rf'^(?:Theorem|Lemma|Corollary|Proposition|Conjecture|Definition|Example|Exercise|Solution|Remark|Algorithm)[\s\xa0]+({re.escape(correct_number)}\.\d+)',
                        title_text
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

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))

    return True


def run(project_root: Path, book_dir: Path) -> bool:
    """
    Run post-processing on a Quarto book.

    This is the main entry point called by build.py.

    Args:
        project_root: Path to the Quarto project root (contains _quarto.yml)
        book_dir: Path to the _book output directory

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

    return post_process_html(book_dir, numbering_map)
