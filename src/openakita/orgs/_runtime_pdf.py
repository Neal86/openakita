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


def _is_table_sep(line: str) -> bool:
    """A GFM table separator row, e.g. ``| --- | :--: | ---: |``."""
    s = line.strip()
    if "|" not in s or "-" not in s:
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", c or "") for c in cells)


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _cell_align(spec: str) -> str:
    spec = spec.strip()
    if spec.startswith(":") and spec.endswith(":"):
        return "center"
    if spec.endswith(":"):
        return "right"
    return "left"


def markdown_to_html(md: str) -> str:
    """Convert a markdown body to an HTML fragment.

    Handles headings, bold/italic/code, ordered/unordered lists, blockquotes,
    fenced code, GFM pipe tables, and horizontal rules -- enough structure for a
    presentable final-report PDF (test17 item 5) without a markdown dependency.
    """
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

    i = 0
    n = len(lines)
    while i < n:
        raw_line = lines[i]
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
            i += 1
            continue
        if in_code:
            code_buf.append(raw_line)
            i += 1
            continue
        if not line.strip():
            flush_para()
            close_lists()
            i += 1
            continue
        # GFM pipe table: a header row followed by a separator row.
        if "|" in line and i + 1 < n and _is_table_sep(lines[i + 1]):
            flush_para()
            close_lists()
            headers = _split_row(line)
            aligns = [_cell_align(c) for c in _split_row(lines[i + 1])]
            rows: list[list[str]] = []
            j = i + 2
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_split_row(lines[j]))
                j += 1
            thead = "".join(
                f'<th style="text-align:{aligns[k] if k < len(aligns) else "left"}">{_inline(h)}</th>'
                for k, h in enumerate(headers)
            )
            body_rows = []
            for r in rows:
                tds = "".join(
                    f'<td style="text-align:{aligns[k] if k < len(aligns) else "left"}">{_inline(c)}</td>'
                    for k, c in enumerate(r)
                )
                body_rows.append(f"<tr>{tds}</tr>")
            html_parts.append(
                f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
            )
            i = j
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_para()
            close_lists()
            level = len(heading.group(1))
            html_parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            flush_para()
            close_lists()
            html_parts.append("<hr>")
            i += 1
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
            i += 1
            continue
        if line.strip().startswith(">"):
            flush_para()
            close_lists()
            html_parts.append(f"<blockquote>{_inline(line.strip()[1:].strip())}</blockquote>")
            i += 1
            continue
        para_buf.append(line.strip())
        i += 1

    if in_code and code_buf:
        html_parts.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
    flush_para()
    close_lists()
    return "\n".join(html_parts)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Microsoft YaHei","PingFang SC","Noto Sans CJK SC","Source Han Sans SC","Segoe UI",sans-serif;
    color: #1f2937; font-size: 12.5px; line-height: 1.75; margin: 0;
    -webkit-font-smoothing: antialiased; }}
  .doc-header {{ border-bottom: 3px solid #6366f1; padding-bottom: 12px; margin-bottom: 22px; }}
  .doc-title {{ font-size: 22px; font-weight: 700; color: #3730a3; margin: 0; letter-spacing: .3px; }}
  .doc-meta {{ color: #6b7280; font-size: 11px; margin-top: 6px; }}
  h1, h2, h3, h4, h5, h6 {{ font-weight: 700; line-height: 1.35;
    page-break-after: avoid; break-after: avoid; }}
  h1 {{ font-size: 19px; color: #3730a3; border-bottom: 2px solid #e5e7eb;
    padding-bottom: 5px; margin: 22px 0 12px; }}
  h2 {{ font-size: 16px; color: #4338ca; margin: 18px 0 9px;
    border-left: 4px solid #6366f1; padding-left: 9px; }}
  h3 {{ font-size: 14px; color: #4f46e5; margin: 14px 0 7px; }}
  h4 {{ font-size: 13px; color: #5b21b6; margin: 12px 0 6px; }}
  p {{ margin: 8px 0; }}
  ul, ol {{ margin: 8px 0; padding-left: 26px; }}
  li {{ margin: 4px 0; }}
  li > ul, li > ol {{ margin: 4px 0; }}
  code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 4px;
    font-family: Consolas,Menlo,monospace; font-size: 11.5px; color: #be123c; }}
  pre {{ background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
    overflow-x: auto; page-break-inside: avoid; break-inside: avoid; }}
  pre code {{ background: transparent; color: inherit; padding: 0; }}
  blockquote {{ border-left: 4px solid #c7d2fe; margin: 10px 0; padding: 6px 14px;
    color: #475569; background: #f8fafc; border-radius: 0 6px 6px 0; }}
  a {{ color: #4f46e5; word-break: break-all; }}
  hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 11.5px;
    page-break-inside: avoid; break-inside: avoid; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 10px; vertical-align: top; }}
  thead th {{ background: #eef2ff; color: #3730a3; font-weight: 700;
    border-bottom: 2px solid #c7d2fe; }}
  tbody tr:nth-child(even) {{ background: #f8fafc; }}
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
