"""
quarto_shared - Shared infrastructure for Quarto book projects.

This package provides:
- sync: Utilities to sync theme files from quarto-shared to projects
- build: Shared incremental build logic for Quarto projects
- init_book: Initialize new Quarto book projects

Usage:
    # Initialize a new book project
    python -m quarto_shared.init_book ~/mybook --title "My Book" --port 4201

    # In an existing project's publish.py
    from quarto_shared import sync, build
"""

__version__ = "1.0.0"

from . import sync
from . import build
from . import init_book
