#!/usr/bin/env python3
"""
init_book.py - Initialize a new Quarto book project with quarto-shared infrastructure.

Usage:
    python -m quarto_shared.init_book ~/fem --title "Finite Element Methods" --port 4202

Or after installation:
    quarto-init ~/fem --title "Finite Element Methods"
"""

import argparse
import shutil
import sys
from pathlib import Path
from textwrap import dedent

QUARTO_SHARED_ROOT = Path(__file__).parent.parent.resolve()


def create_quarto_yml(project_dir: Path, title: str, port: int) -> None:
    """Create _quarto.yml with sensible defaults."""
    content = dedent(f'''\
        project:
          type: book
          output-dir: _book
          preview:
            port: {port}

        book:
          title: "{title}"
          subtitle: "Your subtitle here"
          author:
            - name: "Your Name"
              affiliation: "Your Institution"
              email: "your.email@example.com"
          page-navigation: true
          sidebar:
            search: true
            collapse-level: 1

          chapters:
            - index.qmd
            # - part: "Part One"
            #   chapters:
            #     - chapter1.qmd

        # These files come from quarto-shared via ./publish.py --sync
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
            html-math-method:
              method: mathjax
              # tex-chtml, not tex-svg: Quarto's crossref hover previews re-typeset
              # math outside the live layout, and SVG output cannot compute its
              # sizes there, so the popup fills with giant overlapping glyphs.
              # -full, not plain tex-chtml: the plain bundle fetches
              # [tex]/boldsymbol from the CDN lazily while typesetting, and when
              # that does not land \boldsymbol (and \bm) prints as red literal text.
              url: https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js
            header-includes: |
              <link href='https://fonts.googleapis.com/css?family=Vollkorn' rel='stylesheet'>
              <link rel="stylesheet" type="text/css" href="https://cdn.rawgit.com/dreampulse/computer-modern-web-font/master/fonts.css">
            include-after-body:
              - footer.html
            number-sections: true
            number-depth: 1

        crossref:
          eq-prefix: ""
    ''')
    (project_dir / "_quarto.yml").write_text(content)


def create_publish_py(project_dir: Path, deploy_path: str) -> None:
    """Create publish.py build script."""
    content = dedent(f'''\
        #!/usr/bin/env python3
        """
        publish.py - Incremental Quarto Book Builder

        Uses quarto_shared from ~/quarto-shared for build logic and theme syncing.
        """

        import sys
        import argparse
        from pathlib import Path

        # Add quarto-shared to path
        QUARTO_SHARED = Path.home() / "quarto-shared"
        if not QUARTO_SHARED.exists():
            print(f"ERROR: quarto-shared not found at {{QUARTO_SHARED}}")
            print("Please clone the quarto-shared repository:")
            print("  git clone https://github.com/cenmir/quarto-shared.git ~/quarto-shared")
            sys.exit(1)

        sys.path.insert(0, str(QUARTO_SHARED))

        from quarto_shared import sync, build

        __version__ = "2.0.0"

        # === PROJECT-SPECIFIC CONFIGURATION ===
        PROJECT_ROOT = Path(__file__).parent.resolve()
        DEPLOY_DIR = Path("{deploy_path}")  # Update this for your server
        SSH_KEY = Path.home() / ".ssh" / "ed25519_mechanics"


        def main():
            parser = argparse.ArgumentParser(
                prog='publish',
                description='Incremental Quarto book builder (uses quarto-shared)',
                epilog='Examples:\\n'
                       '  ./publish.py              Build changed files and deploy\\n'
                       '  ./publish.py --full       Force full rebuild\\n'
                       '  ./publish.py --dry-run    Show what would be built\\n'
                       '  ./publish.py --sync       Sync theme files from quarto-shared',
                formatter_class=argparse.RawDescriptionHelpFormatter
            )
            parser.add_argument('--version', action='version', version=f'%(prog)s {{__version__}} (quarto_shared {{build.__version__}})')
            parser.add_argument('--full', action='store_true', help='Force full rebuild')
            parser.add_argument('--no-deploy', action='store_true', help='Skip deployment')
            parser.add_argument('--no-render', action='store_true', help='Skip quarto render')
            parser.add_argument('--dry-run', action='store_true', help='Show what would be built')
            parser.add_argument('--git', action='store_true', help='Push to git after build')
            parser.add_argument('--ssh-key', type=Path, default=SSH_KEY)
            parser.add_argument('--sync', action='store_true', help='Sync theme files from quarto-shared')
            parser.add_argument('--no-sync-check', action='store_true', help='Skip sync check')
            args = parser.parse_args()

            # Sync-only mode
            if args.sync:
                if sync.has_changes(PROJECT_ROOT):
                    sync.print_diff_summary(PROJECT_ROOT)
                    sync.apply(PROJECT_ROOT)
                    print("\\nTheme files synced from quarto-shared.")
                else:
                    print("All theme files are already in sync with quarto-shared.")
                return

            # Check for theme updates before building
            if not args.no_sync_check and sync.has_changes(PROJECT_ROOT):
                sync.interactive_sync(PROJECT_ROOT)

            # Configure and run build
            config = build.BuildConfig(
                project_root=PROJECT_ROOT,
                deploy_dir=DEPLOY_DIR,
                ssh_key=args.ssh_key,
            )

            options = build.BuildOptions(
                full=args.full,
                no_deploy=args.no_deploy,
                no_render=args.no_render,
                dry_run=args.dry_run,
                git=args.git,
            )

            success = build.run(config, options)
            sys.exit(0 if success else 1)


        if __name__ == '__main__':
            main()
    ''')
    publish_path = project_dir / "publish.py"
    publish_path.write_text(content)
    publish_path.chmod(0o755)


def create_index_qmd(project_dir: Path, title: str) -> None:
    """Create initial index.qmd."""
    content = dedent(f'''\
        # Welcome {{.unnumbered}}

        Welcome to {title}.

        ## Getting Started

        This is the introduction to your book. Edit this file to add your content.

        ## About This Project

        This project uses [quarto-shared](https://github.com/cenmir/quarto-shared) for
        shared theme files and build infrastructure.
    ''')
    (project_dir / "index.qmd").write_text(content)


def create_gitignore(project_dir: Path) -> None:
    """Create .gitignore."""
    content = dedent('''\
        # Quarto
        _book/
        _freeze/
        .quarto/

        # Python
        __pycache__/
        *.py[cod]
        .venv/
        venv/

        # Build
        build.log

        # IDE
        .idea/
        .vscode/
        *.swp
        *~

        # OS
        .DS_Store
        Thumbs.db
    ''')
    (project_dir / ".gitignore").write_text(content)


def sync_theme_files(project_dir: Path) -> None:
    """Copy theme files from quarto-shared."""
    # Import sync module
    sys.path.insert(0, str(QUARTO_SHARED_ROOT))
    from quarto_shared import sync

    print("Syncing theme files from quarto-shared...")
    sync.apply(project_dir)


def init_book(
    project_dir: Path,
    title: str = "My Quarto Book",
    port: int = 4200,
    deploy_path: str = "/var/www/mybook/",
    no_git: bool = False,
) -> bool:
    """
    Initialize a new Quarto book project.

    Returns True on success, False on failure.
    """
    project_dir = Path(project_dir).resolve()

    # Check if directory exists and is not empty
    if project_dir.exists():
        if any(project_dir.iterdir()):
            print(f"ERROR: Directory {project_dir} is not empty.")
            print("Please use an empty directory or a new path.")
            return False
    else:
        project_dir.mkdir(parents=True)

    print(f"Initializing Quarto book in {project_dir}")
    print(f"  Title: {title}")
    print(f"  Preview port: {port}")
    print(f"  Deploy path: {deploy_path}")
    print()

    # Create project files
    print("Creating _quarto.yml...")
    create_quarto_yml(project_dir, title, port)

    print("Creating publish.py...")
    create_publish_py(project_dir, deploy_path)

    print("Creating index.qmd...")
    create_index_qmd(project_dir, title)

    print("Creating .gitignore...")
    create_gitignore(project_dir)

    # Sync theme files
    sync_theme_files(project_dir)

    # Initialize git
    if not no_git:
        import subprocess
        print("\nInitializing git repository...")
        subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit from quarto-shared init-book"],
            cwd=project_dir,
            capture_output=True
        )

    print()
    print("=" * 60)
    print("Project initialized successfully!")
    print("=" * 60)
    print()
    print("Next steps:")
    print(f"  cd {project_dir}")
    print("  quarto preview          # Preview locally")
    print("  ./publish.py --dry-run  # Test build")
    print()
    print("To customize:")
    print("  - Edit _quarto.yml to add chapters and metadata")
    print("  - Edit publish.py to set DEPLOY_DIR and SSH_KEY")
    print("  - Run ./publish.py --sync to update theme files")
    print()

    return True


def main():
    parser = argparse.ArgumentParser(
        prog='init-book',
        description='Initialize a new Quarto book project with quarto-shared infrastructure.',
        epilog='Example:\n'
               '  python -m quarto_shared.init_book ~/fem --title "Finite Element Methods" --port 4202',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'project_dir',
        type=Path,
        help='Directory for the new project (will be created if needed)'
    )
    parser.add_argument(
        '--title', '-t',
        default='My Quarto Book',
        help='Book title (default: "My Quarto Book")'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=4200,
        help='Preview server port (default: 4200)'
    )
    parser.add_argument(
        '--deploy-path', '-d',
        default='/var/www/mybook/',
        help='Deployment path on server (default: /var/www/mybook/)'
    )
    parser.add_argument(
        '--no-git',
        action='store_true',
        help='Skip git initialization'
    )

    args = parser.parse_args()

    success = init_book(
        project_dir=args.project_dir,
        title=args.title,
        port=args.port,
        deploy_path=args.deploy_path,
        no_git=args.no_git,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
