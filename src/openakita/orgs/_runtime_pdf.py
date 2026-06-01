"""Best-effort Markdown -> PDF rendering for root-node final deliverables.

UI feedback (图5/图6): the 主编 final report should be delivered not just as a
raw ``.md`` but also rendered to a clean PDF for presentation. We reuse the
approach proven by the ``fin-pulse`` plugin (``finpulse_dispatch.py``): convert
the markdown to a small styled HTML document and let Playwright's bundled
Chromium print it to PDF via ``page.pdf()``.

Everything here is **best-effort and fail-silent**: if Playwright / Chromium is
unavailable, or rendering raises, we return ``None`` and the caller falls back
to the markdown file. Rendering can be disabled outright with
``OPENAKITA_ORGS_V2_RENDER_PDF=0``.

The markdown->HTML conversion is a tiny self-contained renderer (headings,
bold/italic/code, ordered/unordered lists, blockquotes, paragraphs) so we carry
no new hard dependency on a markdown package.
"""

from __future__ import annotations

import html as _html
import logging
import os
import re

__all__ = ["pdf_rendering_enabled", "markdown_to_html", "render_markdown_to_pdf"]

_LOGGER = logging.getLogger(__name__)
_DISABLE_VALUES = {"0", "false", "no", "off"}
_ENV_VAR = "OPENAKITA_ORGS_V2_RENDER_PDF"


def pdf_rendering_enabled() -> bool:
    raw = os.environ.get(_ENV_VAR)
    if raw is None:
        return True
    return raw.strip().lower() not in _DISABLE_VALUES


_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """Escape then apply inline markdown (code/bold/italic/link)."""
    out = _html.escape(text)
    out = _INLINE_CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    out = _LINK.sub(r'<a href="\2">\1</a>', out)
    return out


def markdown_to_html(md: str) -> str:
    """Convert a markdown body to an HTML fragment (block-level + inline)."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    html_parts: list[str] = []
    list_stack: list[str] = []  # "ul" / "ol"
    in_code = False
    code_buf: list[str] = []
    para_buf: list[str] = []

    def flush_para() -> None:
        if para_buf:
            html_parts.append(f"<p>{_inline(' '.join(para_buf))}</p>")
            para_buf.clear()

    def close_lists() -> None:
        while list_stack:
            html_parts.append(f"</{list_stack.pop()}>")

    for raw_line in lines:
        line = raw_line.rstrip()
        fence = line.strip().startswith("```")
        if fence:
            if in_code:
                html_parts.append(
                    "<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>"
                )
                code_buf.clear()
                in_code = False
            else:
                flush_para()
                close_lists()
                in_code = True
            continue
        if in_code:
            code_buf.append(raw_line)
            continue
        if not line.strip():
            flush_para()
            close_lists()
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_para()
            close_lists()
            level = len(heading.group(1))
            html_parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        ul = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if ol or ul:
            flush_para()
            want = "ol" if ol else "ul"
            if not list_stack or list_stack[-1] != want:
                close_lists()
                html_parts.append(f"<{want}>")
                list_stack.append(want)
            item = (ol or ul).group(1)
            html_parts.append(f"<li>{_inline(item)}</li>")
            continue
        if line.strip().startswith(">"):
            flush_para()
            close_lists()
            html_parts.append(f"<blockquote>{_inline(line.strip()[1:].strip())}</blockquote>")
            continue
        para_buf.append(line.strip())

    if in_code and code_buf:
        html_parts.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
    flush_para()
    close_lists()
    return "\n".join(html_parts)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Microsoft YaHei","PingFang SC","Noto Sans CJK SC","Segoe UI",sans-serif;
    color: #1f2937; font-size: 12.5px; line-height: 1.7; }}
  .doc-header {{ border-bottom: 3px solid #6366f1; padding-bottom: 10px; margin-bottom: 18px; }}
  .doc-title {{ font-size: 20px; font-weight: 700; color: #4338ca; margin: 0; }}
  .doc-meta {{ color: #6b7280; font-size: 11px; margin-top: 4px; }}
  h1 {{ font-size: 18px; color: #4338ca; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  h2 {{ font-size: 16px; color: #4f46e5; }}
  h3 {{ font-size: 14px; color: #4f46e5; }}
  p {{ margin: 8px 0; }}
  ul, ol {{ margin: 8px 0; padding-left: 24px; }}
  li {{ margin: 3px 0; }}
  code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 4px;
    font-family: Consolas,Menlo,monospace; font-size: 11.5px; color: #be123c; }}
  pre {{ background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
    overflow-x: auto; }}
  pre code {{ background: transparent; color: inherit; padding: 0; }}
  blockquote {{ border-left: 4px solid #c7d2fe; margin: 8px 0; padding: 4px 12px;
    color: #475569; background: #f8fafc; }}
  a {{ color: #4f46e5; }}
</style></head><body>
<div class="doc-header">
  <p class="doc-title">{title}</p>
  <p class="doc-meta">{meta}</p>
</div>
{body}
</body></html>"""


def build_report_html(*, title: str, meta: str, markdown_body: str) -> str:
    return _HTML_TEMPLATE.format(
        title=_html.escape(title or "交付报告"),
        meta=_html.escape(meta or ""),
        body=markdown_to_html(markdown_body),
    )


def _configure_launch() -> dict:
    """Mirror fin-pulse: prefer a bundled Chromium when packaged."""
    kwargs: dict = {"headless": True}
    try:
        from openakita.plugins import sdk  # type: ignore  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    return kwargs


async def render_markdown_to_pdf(
    *, markdown_body: str, out_path: str, title: str = "交付报告", meta: str = ""
) -> str | None:
    """Render ``markdown_body`` to a PDF at ``out_path``. Returns the path or None.

    Best-effort: any failure (Playwright missing, Chromium not installed,
    render error) returns ``None`` so the caller keeps the markdown fallback.
    """
    if not pdf_rendering_enabled():
        return None
    if not isinstance(markdown_body, str) or not markdown_body.strip():
        return None
    try:
        from playwright.async_api import async_playwright
    except Exception:  # noqa: BLE001 -- playwright not installed
        _LOGGER.debug("pdf render skipped: playwright unavailable")
        return None
    html_doc = build_report_html(title=title, meta=meta, markdown_body=markdown_body)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(**_configure_launch())
            try:
                page = await browser.new_page()
                await page.set_content(html_doc, wait_until="load")
                await page.pdf(
                    path=str(out_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "16mm", "right": "14mm", "bottom": "16mm", "left": "14mm"},
                )
                await page.close()
            finally:
                await browser.close()
    except Exception:  # noqa: BLE001 -- best-effort; keep md fallback
        _LOGGER.debug("pdf render failed for %s", out_path, exc_info=True)
        return None
    return str(out_path)
