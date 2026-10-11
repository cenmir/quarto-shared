#!/usr/bin/env python3
"""media.py - Convert a book's raster images per output format.

The sources keep their full-resolution images. HTML gets WebP at screen
resolution, and an animated GIF becomes a looping WebM video with an MP4
fallback. PDF gets the full-resolution source and is re-encoded only when LaTeX
cannot read the format (WebP, TIFF, BMP, a static GIF).

The Lua filter filters/media.lua owns the cache: it hashes the source bytes
together with the recipe, looks for <cache>/<name>.<key>.<ext>, and calls this
script only on a miss. So a cache hit costs one file read and no process.

CLI (called by the filter; the result written is printed as one word):

    python media.py convert SRC OUT_STEM --target html|pdf [--max-width N] [--quality Q]

prints one of
    webp      wrote OUT_STEM.webp
    webm      an animated GIF for HTML; wrote OUT_STEM.webm and OUT_STEM.mp4
    png       wrote OUT_STEM.png
    keep      the source is already the best choice; wrote the marker OUT_STEM.keep
    animated  an animated GIF for PDF; wrote the marker OUT_STEM.animated

Print preflight, on a rendered PDF:

    python media.py preflight BOOK.pdf [--project DIR] [--min-ppi 300]

lists every raster image printed below MIN_PPI, with the page, the pixels, the
resolution it prints at and the source file, and exits 1 if there is any.

After a render, delete the notebook images no page uses any more:

    python media.py prune BOOK_DIR [HTML ...]

Requires Pillow with WebP support, ffmpeg (libvpx-vp9, libx264) for animations,
and pdfimages (poppler-utils) for preflight.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageOps

# A PNG is kept lossless when that costs at most this factor over lossy WebP.
# Line art and plots land well inside it; photographs saved as PNG do not.
LOSSLESS_TOLERANCE = 1.3

# LaTeX reads PNG, JPEG and PDF directly; everything else must be re-encoded.
LATEX_READABLE = {".png", ".jpg", ".jpeg", ".pdf"}


def _atomic_save(im: Image.Image, dst: Path, **kwargs) -> None:
    """Write through a temporary file, so a reader never sees half an image."""
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
    im.save(tmp, **kwargs)
    tmp.replace(dst)


def _marker(out_stem: Path, kind: str) -> str:
    out_stem.with_name(f"{out_stem.name}.{kind}").touch()
    return kind


def _flatten_mode(im: Image.Image) -> Image.Image:
    """WebP takes RGB or RGBA; palette and grey images keep their transparency."""
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    return im.convert("RGBA" if has_alpha else "RGB")


def _even(n: float) -> int:
    """H.264 and VP9 in 4:2:0 need even dimensions."""
    return max(2, int(n) // 2 * 2)


def _ffmpeg(args: list, dst: Path) -> None:
    tmp = dst.with_name(f".{dst.stem}.{os.getpid()}.tmp{dst.suffix}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, str(tmp)], check=True)
    tmp.replace(dst)


def to_video(src: Path, out_stem: Path, max_width: int) -> str:
    """Encode an animated GIF as a looping WebM, plus an MP4 for older Safari.

    A GIF's transparency survives in the WebM, so the animation sits on the page
    background in either theme. MP4 has no alpha, so there it is laid on white.
    """
    with Image.open(src) as im:
        width, height = im.size
        # Many GIFs declare a transparent colour and never draw with it; only
        # pixels that are actually see-through make the alpha channel worth its bytes.
        has_alpha = im.convert("RGBA").getchannel("A").getextrema()[0] < 255
        durations = []
        for frame in range(im.n_frames):
            im.seek(frame)
            durations.append(im.info.get("duration", 100) or 100)
    # The white backdrop is a generated stream that sets the output frame rate,
    # so it must tick at least as fast as the GIF or frames are dropped.
    fps = max(1, round(1000 * len(durations) / sum(durations)))

    scale = min(1.0, max_width / width)
    w, h = _even(width * scale), _even(height * scale)
    size = f"scale={w}:{h}:flags=lanczos"

    _ffmpeg(["-i", str(src), "-vf", f"{size},format={'yuva420p' if has_alpha else 'yuv420p'}",
             "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32", "-row-mt", "1",
             "-auto-alt-ref", "0", "-an"], out_stem.with_name(f"{out_stem.name}.webm"))
    _ffmpeg(["-i", str(src), "-filter_complex",
             f"color=white:s={w}x{h}:r={fps}[bg];[0:v]{size}[fg];"
             f"[bg][fg]overlay=shortest=1,format=yuv420p",
             "-c:v", "libx264", "-crf", "23", "-preset", "slow",
             "-movflags", "+faststart", "-an"], out_stem.with_name(f"{out_stem.name}.mp4"))
    return "webm"


def to_html(src: Path, out_stem: Path, max_width: int, quality: int) -> str:
    with Image.open(src) as im:
        animated = getattr(im, "is_animated", False)
    if animated:
        return to_video(src, out_stem, max_width)
    with Image.open(src) as im:
        icc = im.info.get("icc_profile")
        im = _flatten_mode(ImageOps.exif_transpose(im))

    resized = im.width > max_width
    if resized:
        height = round(im.height * max_width / im.width)
        im = im.resize((max_width, height), Image.Resampling.LANCZOS)

    dst = out_stem.with_name(f"{out_stem.name}.webp")
    options = {"format": "WEBP", "method": 6}
    if icc:
        options["icc_profile"] = icc

    _atomic_save(im, dst, quality=quality, **options)
    if src.suffix.lower() == ".png":
        lossless = dst.with_name(f"{dst.name}.lossless")
        _atomic_save(im, lossless, lossless=True, quality=100, **options)
        if lossless.stat().st_size <= LOSSLESS_TOLERANCE * dst.stat().st_size:
            lossless.replace(dst)
        else:
            lossless.unlink()

    # An image already small and at screen size gains nothing from WebP.
    if not resized and dst.stat().st_size >= src.stat().st_size:
        dst.unlink()
        return _marker(out_stem, "keep")
    return "webp"


def to_pdf(src: Path, out_stem: Path) -> str:
    if src.suffix.lower() in LATEX_READABLE:
        return _marker(out_stem, "keep")
    with Image.open(src) as im:
        if getattr(im, "is_animated", False):
            return _marker(out_stem, "animated")
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = _flatten_mode(im)
        _atomic_save(im, out_stem.with_name(f"{out_stem.name}.png"), format="PNG", optimize=True)
    return "png"


# Directories that hold build output or tooling, never a book's images.
SKIP_DIRS = {"_book", "_site", "_freeze", "_mediacache", ".quarto", ".git", ".venv", "venv",
             "node_modules", "__pycache__"}
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}


def _sources_by_size(project: Path) -> dict:
    """Map (width, height) in pixels to the raster files of that size.

    LaTeX embeds an image with its pixels untouched, so the pixel size is what
    ties an image in the PDF back to the file it came from.
    """
    by_size = {}
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(root, name)
            if path.suffix.lower() not in RASTER_SUFFIXES:
                continue
            try:
                with Image.open(path) as im:
                    size = im.size
            except OSError:
                continue
            by_size.setdefault(size, []).append(path.relative_to(project))
    return by_size


def _pdf_images(pdf: Path) -> list:
    """The raster images of a PDF, one dict per placement, from pdfimages -list.

    The list gives the effective resolution of each placement, so an image
    printed twice at different sizes appears twice. Soft masks (the alpha
    channel of a PNG) are skipped; they share the size of their image.
    """
    out = subprocess.run(["pdfimages", "-list", str(pdf)],
                         capture_output=True, text=True, check=True).stdout
    images = []
    for line in out.splitlines()[2:]:   # two header lines
        cols = line.split()
        if len(cols) < 14 or cols[2] != "image":
            continue
        images.append({"page": int(cols[0]), "width": int(cols[3]),
                       "height": int(cols[4]), "ppi": min(int(cols[12]), int(cols[13]))})
    return images


def preflight(pdf: Path, project: Path, min_ppi: int) -> int:
    images = _pdf_images(pdf)
    low = sorted((im for im in images if im["ppi"] < min_ppi), key=lambda im: im["ppi"])
    if not low:
        sys.stdout.write(f"{len(images)} raster images, all at {min_ppi} ppi or more.\n")
        return 0

    by_size = _sources_by_size(project)
    rows = [("ppi", "page", "pixels", "source")]
    for im in low:
        sources = by_size.get((im["width"], im["height"]), [])
        source = ", ".join(str(s) for s in sources) or "(no file of this size; drawn by a notebook?)"
        rows.append((str(im["ppi"]), str(im["page"]), f'{im["width"]}x{im["height"]}', source))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for r in rows:
        sys.stdout.write(f"{r[0]:>{widths[0]}}  {r[1]:>{widths[1]}}  {r[2]:<{widths[2]}}  {r[3]}\n")
    sys.stdout.write(f"\n{len(low)} of {len(images)} raster images print below {min_ppi} ppi. "
                     f"To fix one, find a larger original or print it smaller.\n")
    return 1


def prune(book_dir: Path, html_files=None) -> int:
    """Delete the notebook images that no page refers to any more.

    Quarto moves a document's `<name>_files/` folder into the output as a whole,
    whatever the page uses from it. Once media.lua points a page at the WebP, the
    PNG that Jupyter wrote stays behind in `<name>_files/figure-html/`, unused.
    Only that folder is touched, and only images in it that neither the page nor
    its llms.txt twin mentions.
    """
    if html_files is None:
        html_files = book_dir.rglob("*.html")
    removed = 0
    for html in html_files:
        html = Path(html)
        figures = html.with_name(f"{html.stem}_files") / "figure-html"
        if html.suffix != ".html" or not html.exists() or not figures.is_dir():
            continue
        text = html.read_text(errors="ignore")
        twin = html.with_suffix(".llms.md")
        if twin.exists():
            text += twin.read_text(errors="ignore")
        for image in figures.iterdir():
            if image.suffix.lower() in RASTER_SUFFIXES and image.name not in text:
                image.unlink()
                removed += 1
    return removed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("convert", help="convert one image (used by media.lua)")
    conv.add_argument("src", type=Path)
    conv.add_argument("out_stem", type=Path, help="cache path without extension")
    conv.add_argument("--target", choices=["html", "pdf"], required=True)
    conv.add_argument("--max-width", type=int, default=1600)
    conv.add_argument("--quality", type=int, default=82)
    prn = sub.add_parser("prune", help="delete notebook images no page uses")
    prn.add_argument("book_dir", type=Path)
    prn.add_argument("html", type=Path, nargs="*", help="only these pages (default: all)")
    pre = sub.add_parser("preflight", help="list the images a PDF prints at low resolution")
    pre.add_argument("pdf", type=Path)
    pre.add_argument("--project", type=Path, default=Path("."),
                     help="where to look for the source files (default: here)")
    pre.add_argument("--min-ppi", type=int, default=300,
                     help="300 for photographs; publishers ask 600 or more for bitmap line art")
    args = parser.parse_args(argv)

    if args.command == "preflight":
        return preflight(args.pdf, args.project, args.min_ppi)
    if args.command == "prune":
        n = prune(args.book_dir, args.html or None)
        sys.stdout.write(f"removed {n} unused notebook images\n")
        return 0

    args.out_stem.parent.mkdir(parents=True, exist_ok=True)
    if args.target == "html":
        result = to_html(args.src, args.out_stem, args.max_width, args.quality)
    else:
        result = to_pdf(args.src, args.out_stem)
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
