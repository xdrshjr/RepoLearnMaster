"""PDF 渲染（spec §13 问题 2）。

**MVP 唯一引擎 = Chromium**（`playwright install chromium`，由 start.ps1 的 G2 负责）。
`weasyprint` 在 Windows 需要手工安装 GTK/Pango，等同不可用——v1 把它写成"兜底"
是假的安全感，v2 已删除该选项（P1-7）。

降级路径是"打印优化 HTML + 浏览器打印"（`engine='browser-print'`）：
**不生成假 PDF**。一个 0 页的 PDF 比没有 PDF 更糟，因为它看起来像是成功了。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from repolearn.core.logging import get_logger
from repolearn.services import object_store

log = get_logger("pdf")


@dataclass
class PdfResult:
    ok: bool
    engine: str = "chromium"
    data: bytes = b""
    pages: int = 0
    object_key: str = ""
    error: dict = field(default_factory=dict)


def chromium_available() -> bool:
    """探测 Chromium 是否可被 playwright 使用（Gate 0 G2 的运行时判断）。"""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - 缺包即不可用
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            browser.close()
        return True
    except Exception:  # noqa: BLE001
        return False


async def render_pdf(html: str, *, engine: str = "chromium", name: str = "book") -> PdfResult:
    if engine == "browser-print":
        return PdfResult(ok=False, engine="browser-print", error={"code": "PDF_BROWSER_PRINT", "message": "已切换为打印视图"})
    try:
        return await asyncio.to_thread(_render_with_playwright, html, name)
    except Exception as exc:  # noqa: BLE001 - 任何失败都降级，不抛给用户
        log.warning("pdf_render_failed", error=str(exc))
        return PdfResult(
            ok=False,
            engine="browser-print",
            error={
                "code": "PDF_ENGINE_UNAVAILABLE",
                "message": f"Chromium 不可用，已切换为打印视图：{exc}",
                "hint": "运行 `python -m playwright install chromium` 后重新导出",
            },
        )


def _render_with_playwright(html: str, name: str) -> PdfResult:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        data = page.pdf(format="A4", print_background=True, margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
        browser.close()
    key = f"{name}.pdf"
    object_store.put("pdf", key, data)
    pages = _count_pages(data)
    return PdfResult(ok=True, engine="chromium", data=data, pages=pages, object_key=key)


def _count_pages(data: bytes) -> int:
    """优先用 pypdf 精确计数；不可用时按 `/Type /Page` 近似。"""
    try:
        import io as _io

        from pypdf import PdfReader  # type: ignore[import-not-found]

        return len(PdfReader(_io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001
        return max(1, data.count(b"/Type /Page") - data.count(b"/Type /Pages"))
