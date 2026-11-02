"""Remember which output pages the post-render passes have already finished.

`quarto preview` hands the hook every page of the book when it starts, although it has
rendered only one or none of them. Each pass is a function of the page alone (plus the
book's configuration and the pass's own code), so a page whose bytes are those the pass
left behind last time needs no second look. Hashing all pages of a 150-page book takes
some 40 ms; converting them takes 20 s.

The cache is one JSON file outside the output directory, so it is never published. A
pass stores its entries under a version key built from everything the result depends on
besides the page; a change of code or configuration then empties that pass's entries.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Optional, Union


def file_hash(path: Path) -> Optional[str]:
    try:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def version_key(*parts: Union[str, bytes, Path]) -> str:
    """Hash of the inputs a pass depends on: a Path counts by its contents."""
    h = hashlib.sha1()
    for part in parts:
        if isinstance(part, Path):
            part = part.read_bytes() if part.exists() else b''
        h.update(part if isinstance(part, bytes) else str(part).encode())
        h.update(b'\0')
    return h.hexdigest()


class PageCache:
    """The entries of one pass: page (relative to the book) -> recorded value."""

    def __init__(self, cache_file: Optional[Path], section: str, version: str):
        self.file, self.section, self.version = cache_file, section, version
        self.entries = {}
        if cache_file is None:
            return
        try:
            data = json.loads(Path(cache_file).read_text(encoding='utf-8'))
            stored = data.get(section, {})
            if stored.get('version') == version:
                self.entries = stored.get('pages', {})
        except (FileNotFoundError, ValueError):
            pass

    def get(self, page: str):
        return self.entries.get(page)

    def put(self, page: str, value) -> None:
        self.entries[page] = value

    def forget(self, pages: Iterable[str]) -> None:
        for page in pages:
            self.entries.pop(page, None)

    def save(self) -> None:
        if self.file is None:
            return
        path = Path(self.file)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            data = {}
        data[self.section] = {'version': self.version, 'pages': self.entries}
        tmp = path.with_suffix(f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        tmp.replace(path)
