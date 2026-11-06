"""渲染层：Mermaid→SVG、PDF、书籍排版。"""

from __future__ import annotations

from repolearn.rendering.book_layout import blocks_to_html, build_chapters
from repolearn.rendering.mermaid import render_and_store, render_svg
from repolearn.rendering.pdf import PdfResult, chromium_available, render_pdf

__all__ = [
    "PdfResult",
    "blocks_to_html",
    "build_chapters",
    "chromium_available",
    "render_and_store",
    "render_pdf",
    "render_svg",
]
