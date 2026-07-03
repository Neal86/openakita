"""test17 item 5: the md->PDF HTML renderer must render tables, horizontal
rules and heading hierarchy so the final report PDF is presentable."""

from __future__ import annotations

from openakita.orgs._runtime_pdf import build_report_html, markdown_to_html


def test_pipe_table_renders_as_html_table() -> None:
    md = "\n".join([
        "| 项目 | 预算 | 负责人 |",
        "| --- | ---: | :---: |",
        "| 场地 | 5000 | 张三 |",
        "| 物料 | 1200 | 李四 |",
    ])
    html = markdown_to_html(md)
    assert "<table>" in html and "</table>" in html
    assert "<thead>" in html and "<th" in html
    assert html.count("<tr>") == 3  # header + 2 body rows
    assert "<td" in html and "场地" in html and "5000" in html
    # alignment from the separator row is applied.
    assert "text-align:right" in html
    assert "text-align:center" in html


def test_headings_lists_hr_and_code() -> None:
    md = "\n".join([
        "# 标题一",
        "## 标题二",
        "普通段落 **加粗** 与 `代码`。",
        "- 列表项 A",
        "- 列表项 B",
        "1. 有序一",
        "2. 有序二",
        "---",
        "> 引用一句",
        "```",
        "code block",
        "```",
    ])
    html = markdown_to_html(md)
    assert "<h1>标题一</h1>" in html
    assert "<h2>标题二</h2>" in html
    assert "<strong>加粗</strong>" in html
    assert "<code>代码</code>" in html
    assert "<ul>" in html and "<ol>" in html
    assert "<hr>" in html
    assert "<blockquote>" in html
    assert "<pre><code>" in html


def test_build_report_html_wraps_body_with_table_css() -> None:
    html = build_report_html(
        title="交付报告", meta="主编 · 2026",
        markdown_body="| a | b |\n| - | - |\n| 1 | 2 |",
    )
    assert "<!DOCTYPE html>" in html
    assert "交付报告" in html
    # the print stylesheet must style tables (borders/zebra) for the PDF.
    assert "border-collapse" in html
    assert "<table>" in html
