"""Header/footer stripping unit tests."""

from finreportparser.fusion.headers_footers import (
    collect_repeated_line_keys,
    filter_document_headers_footers,
    is_header_footer_text,
    strip_header_footer_lines,
)
from finreportparser.types import BBox, BlockType, PageBlock, PageResult


def test_disclaimer_footer() -> None:
    t = "免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。 8"
    assert is_header_footer_text(t)


def test_department_header() -> None:
    assert is_header_footer_text("固收研究")
    assert is_header_footer_text("华泰证券")
    assert is_header_footer_text("HUATAI SECURITIES")


def test_body_not_removed() -> None:
    body = (
        "我们先对50余个转债相关的因子进行单独回测。"
        "固收研究框架在正文中也会被讨论，但这是长段落。"
    )
    assert not is_header_footer_text(body)


def test_strip_lines() -> None:
    text = "固收研究\n正文内容在这里\n免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。 3"
    out = strip_header_footer_lines(text)
    assert "固收研究" not in out
    assert "免责声明" not in out
    assert "正文内容在这里" in out


def test_geometry_top_band() -> None:
    page = PageResult(
        page_num=1,
        height=1000,
        width=700,
        blocks=[
            PageBlock(
                type=BlockType.TEXT,
                text="页眉部门",
                bbox=BBox(x0=50, y0=10, x1=200, y1=40),
            ),
            PageBlock(
                type=BlockType.TEXT,
                text="这是正文第一段，内容比较长，不应该被删掉。",
                bbox=BBox(x0=50, y0=200, x1=600, y1=280),
            ),
            PageBlock(
                type=BlockType.TEXT,
                text="免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。 1",
                bbox=BBox(x0=50, y0=940, x1=600, y1=980),
            ),
        ],
    )
    filtered = filter_document_headers_footers([page])[0]
    texts = [b.text for b in filtered.blocks]
    assert any("正文第一段" in (t or "") for t in texts)
    assert not any(t and "免责声明" in t for t in texts)


def test_cross_page_repeat() -> None:
    pages = []
    for i in range(5):
        pages.append(
            PageResult(
                page_num=i + 1,
                height=1000,
                width=700,
                blocks=[
                    PageBlock(
                        type=BlockType.TEXT,
                        text="固收研究",
                        bbox=BBox(x0=50, y0=100, x1=150, y1=120),  # mid-ish but repeated
                    ),
                    PageBlock(
                        type=BlockType.TEXT,
                        text=f"第{i+1}页独有正文段落内容足够长不会被误删。",
                        bbox=BBox(x0=50, y0=300, x1=500, y1=400),
                    ),
                ],
            )
        )
    keys = collect_repeated_line_keys(pages, min_pages=3)
    assert "固收研究" in keys
    filtered = filter_document_headers_footers(pages)
    for p in filtered:
        assert not any(b.text == "固收研究" for b in p.blocks)
        assert any("独有正文" in (b.text or "") for b in p.blocks)
