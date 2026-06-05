#!/usr/bin/env python3 -m pytest
"""Tests for PDF converter memory optimization.

Verifies that:
- page.close() is called after processing each page (frees cached data)
- Plain-text PDFs fall back to pdfminer when no form pages are found
- Mixed PDFs use form extraction only on form-style pages
- Memory stays constant regardless of page count
"""

import gc
import io
import os
import base64
import re
import tracemalloc

import pytest
from unittest.mock import patch, MagicMock

from markitdown import MarkItDown
from markitdown.converters._pdf_converter import _to_markdown_table

TEST_FILES_DIR = os.path.join(os.path.dirname(__file__), "test_files")


def _require_pillow():
    return pytest.importorskip("PIL.Image")


def _has_fpdf2() -> bool:
    try:
        import fpdf  # noqa: F401

        return True
    except ImportError:
        return False


def _make_form_page():
    """Create a mock page with 3-column table-like word positions."""
    page = MagicMock()
    page.width = 612
    page.height = 792
    page.close = MagicMock()
    page.extract_words.return_value = [
        {"text": "Name", "x0": 50, "x1": 100, "top": 10, "bottom": 20},
        {"text": "Value", "x0": 250, "x1": 300, "top": 10, "bottom": 20},
        {"text": "Unit", "x0": 450, "x1": 500, "top": 10, "bottom": 20},
        {"text": "Alpha", "x0": 50, "x1": 100, "top": 30, "bottom": 40},
        {"text": "100", "x0": 250, "x1": 280, "top": 30, "bottom": 40},
        {"text": "kg", "x0": 450, "x1": 470, "top": 30, "bottom": 40},
        {"text": "Beta", "x0": 50, "x1": 100, "top": 50, "bottom": 60},
        {"text": "200", "x0": 250, "x1": 280, "top": 50, "bottom": 60},
        {"text": "lb", "x0": 450, "x1": 470, "top": 50, "bottom": 60},
    ]
    return page


def _make_plain_page():
    """Create a mock page with single-line paragraph (no table structure)."""
    page = MagicMock()
    page.width = 612
    page.height = 792
    page.close = MagicMock()
    page.extract_words.return_value = [
        {
            "text": "This is a long paragraph of plain text.",
            "x0": 50,
            "x1": 550,
            "top": 10,
            "bottom": 20,
        },
    ]
    page.extract_text.return_value = "This is a long paragraph of plain text."
    return page


def _make_two_column_page():
    """Create a mock plain-text page with two prose columns."""
    page = MagicMock()
    page.width = 612
    page.height = 792
    page.close = MagicMock()
    page.extract_words.return_value = [
        {
            "text": "Document overview title",
            "x0": 60,
            "x1": 260,
            "top": 50,
            "bottom": 62,
        },
        {"text": "Left heading", "x0": 60, "x1": 245, "top": 80, "bottom": 92},
        {"text": "Right heading", "x0": 340, "x1": 430, "top": 80, "bottom": 92},
        {
            "text": "Left body line one has enough prose content",
            "x0": 60,
            "x1": 245,
            "top": 110,
            "bottom": 122,
        },
        {
            "text": "Right body line one has enough prose content",
            "x0": 340,
            "x1": 535,
            "top": 110,
            "bottom": 122,
        },
        {
            "text": "Left body line two keeps the left narrative together",
            "x0": 60,
            "x1": 270,
            "top": 130,
            "bottom": 142,
        },
        {
            "text": "Right body line two keeps the right narrative together",
            "x0": 340,
            "x1": 550,
            "top": 130,
            "bottom": 142,
        },
        {
            "text": "Left body line three continues below the matching row",
            "x0": 60,
            "x1": 275,
            "top": 150,
            "bottom": 162,
        },
        {
            "text": "Right body line three continues below the matching row",
            "x0": 340,
            "x1": 555,
            "top": 150,
            "bottom": 162,
        },
        {
            "text": "Document footer text",
            "x0": 60,
            "x1": 190,
            "top": 740,
            "bottom": 752,
        },
    ]
    page.extract_text.return_value = (
        "Document overview title\n"
        "Left heading Right heading\n"
        "Left body line one has enough prose content "
        "Right body line one has enough prose content\n"
        "Left body line two keeps the left narrative together "
        "Right body line two keeps the right narrative together\n"
        "Left body line three continues below the matching row "
        "Right body line three continues below the matching row\n"
        "Document footer text"
    )
    return page


def _make_two_column_table_page():
    """Create a mock page with a two-column key/value table."""
    page = MagicMock()
    page.width = 612
    page.height = 792
    page.close = MagicMock()
    page.extract_words.return_value = [
        {"text": "Name", "x0": 60, "x1": 100, "top": 80, "bottom": 92},
        {"text": "Alice", "x0": 340, "x1": 390, "top": 80, "bottom": 92},
        {"text": "Date", "x0": 60, "x1": 95, "top": 110, "bottom": 122},
        {"text": "2026", "x0": 340, "x1": 385, "top": 110, "bottom": 122},
        {"text": "Owner", "x0": 60, "x1": 112, "top": 130, "bottom": 142},
        {"text": "Bob", "x0": 340, "x1": 370, "top": 130, "bottom": 142},
    ]
    page.extract_text.return_value = "Name Alice\nDate 2026\nOwner Bob"
    return page


def _make_baseline_offset_table_page():
    """Create a mock page where one visual table row has shifted baselines."""
    page = MagicMock()
    page.width = 840
    page.height = 595
    page.close = MagicMock()
    page.extract_words.return_value = [
        {"text": "Wide", "x0": 45, "x1": 70, "top": 100, "bottom": 108},
        {"text": "A", "x0": 170, "x1": 180, "top": 100, "bottom": 108},
        {"text": "B", "x0": 275, "x1": 285, "top": 100, "bottom": 108},
        {"text": "C", "x0": 380, "x1": 390, "top": 100, "bottom": 108},
        {"text": "D", "x0": 485, "x1": 495, "top": 100, "bottom": 108},
        {"text": "E", "x0": 590, "x1": 600, "top": 100, "bottom": 108},
        {"text": "F", "x0": 700, "x1": 710, "top": 100, "bottom": 108},
        {"text": "Gateway modules", "x0": 45, "x1": 150, "top": 180, "bottom": 192},
        {"text": "Feature", "x0": 45, "x1": 75, "top": 230, "bottom": 238},
        {"text": "Protocol A", "x0": 170, "x1": 230, "top": 230, "bottom": 240},
        {"text": "Protocol B", "x0": 275, "x1": 335, "top": 230, "bottom": 240},
        {"text": "Protocol C", "x0": 380, "x1": 440, "top": 230, "bottom": 240},
        {"text": "Order No.", "x0": 45, "x1": 90, "top": 246.1, "bottom": 254.1},
        {"text": "R1.001", "x0": 170, "x1": 215, "top": 247.5, "bottom": 255.5},
        {"text": "R1.002", "x0": 275, "x1": 320, "top": 247.5, "bottom": 255.5},
        {"text": "R1.003", "x0": 380, "x1": 425, "top": 247.5, "bottom": 255.5},
        {"text": "Approval", "x0": 45, "x1": 90, "top": 260, "bottom": 268},
        {"text": "CE", "x0": 170, "x1": 185, "top": 261.5, "bottom": 269.5},
        {"text": "UL", "x0": 275, "x1": 290, "top": 261.5, "bottom": 269.5},
        {"text": "UKCA", "x0": 380, "x1": 410, "top": 261.5, "bottom": 269.5},
    ]
    return page


class _FakePdfImageStream:
    def __init__(self, data: bytes, pdf_filter: str, **attrs):
        self.attrs = {"Filter": pdf_filter, **attrs}
        self._data = data

    def get_data(self):
        return self._data


def _make_pdf_image(
    *,
    x0: float,
    top: float,
    width: float,
    height: float,
    data: bytes = b"\xff\xd8fake jpeg",
):
    return {
        "stream": _FakePdfImageStream(data, "DCTDecode"),
        "x0": x0,
        "x1": x0 + width,
        "top": top,
        "bottom": top + height,
        "width": width,
        "height": height,
    }


def _make_flate_indexed_cmyk_image(
    *,
    width: int,
    height: int,
    data: bytes,
    palette: bytes,
):
    return {
        "stream": _FakePdfImageStream(
            data,
            "FlateDecode",
            Width=width,
            Height=height,
            BitsPerComponent=8,
            ColorSpace=["Indexed", "DeviceCMYK", (len(palette) // 4) - 1, palette],
        ),
        "x0": 80,
        "x1": 80 + width,
        "top": 120,
        "bottom": 120 + height,
        "width": width,
        "height": height,
    }


def _mock_pdfplumber_open(pages):
    """Return a mock pdfplumber.open that yields the given pages."""

    def mock_open(stream):
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        return mock_pdf

    return mock_open


class TestPdfMemoryOptimization:
    """Test that PDF conversion cleans up per-page caches to limit memory."""

    def test_page_close_called_on_every_page(self):
        """Verify page.close() is called on every page during conversion.

        This ensures cached word/layout data is freed after each page,
        preventing O(n) memory growth with page count.
        """
        num_pages = 20
        pages = [_make_form_page() for _ in range(num_pages)]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        # page.close() must be called on ALL pages
        for i, page in enumerate(pages):
            assert page.close.called, (
                f"page.close() was NOT called on page {i} — "
                "this would cause memory to accumulate"
            )

    def test_plain_text_pdf_falls_back_to_pdfminer(self):
        """Verify all-plain-text PDFs fall back to pdfminer.

        When no page has form-style content, the converter should discard
        pdfplumber results and use pdfminer for the whole document (better
        text spacing for prose).
        """
        num_pages = 50
        pages = [_make_plain_page() for _ in range(num_pages)]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        # pdfminer should be used for the final text extraction
        assert mock_pdfminer.high_level.extract_text.called, (
            "pdfminer.high_level.extract_text was not called — "
            "plain-text PDFs should fall back to pdfminer"
        )
        assert result.text_content is not None

    def test_two_column_plain_text_pdf_preserves_column_reading_order(self):
        """Two-column prose should not be interleaved row by row."""
        page = _make_two_column_page()

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = page.extract_text()

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        assert result.text_content is not None
        assert "Document overview title" in result.text_content
        assert (
            "Left heading\n"
            "Left body line one has enough prose content\n"
            "Left body line two keeps the left narrative together\n"
            "Left body line three continues below the matching row"
        ) in result.text_content
        assert (
            "Right heading\n"
            "Right body line one has enough prose content\n"
            "Right body line two keeps the right narrative together\n"
            "Right body line three continues below the matching row"
        ) in result.text_content
        assert (
            "Left body line one has enough prose content "
            "Right body line one has enough prose content"
        ) not in result.text_content
        assert result.text_content.rfind(
            "Document footer text"
        ) > result.text_content.rfind(
            "Right body line three continues below the matching row"
        )

    def test_two_column_key_value_pdf_falls_back_to_pdfminer(self):
        """Two-column key/value rows should preserve row associations."""
        page = _make_two_column_table_page()

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = (
                "Name Alice\nDate 2026\nOwner Bob"
            )

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        assert result.text_content is not None
        assert mock_pdfminer.high_level.extract_text.called
        assert "Name Alice\nDate 2026\nOwner Bob" in result.text_content
        assert "Name\nDate\nOwner\n\nAlice" not in result.text_content

    def test_plain_pages_use_pdfminer_when_document_has_multicolumn_page(self):
        """Only detected multi-column pages should replace pdfminer output."""
        plain_before = _make_plain_page()
        plain_before.extract_text.return_value = "page extract text before"
        plain_after = _make_plain_page()
        plain_after.extract_text.return_value = "page extract text after"
        multi_column = _make_two_column_page()

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(
                [plain_before, multi_column, plain_after]
            )
            mock_pdfminer.high_level.extract_text.return_value = (
                "pdfminer text before\f"
                "interleaved multi-column fallback\f"
                "pdfminer text after\f"
            )

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        assert result.text_content is not None
        assert "pdfminer text before" in result.text_content
        assert "pdfminer text after" in result.text_content
        assert "page extract text before" not in result.text_content
        assert "page extract text after" not in result.text_content
        assert "interleaved multi-column fallback" not in result.text_content
        assert (
            "Left heading\nLeft body line one has enough prose content"
            in result.text_content
        )

    def test_plain_text_pdf_still_closes_all_pages(self):
        """Even for plain-text PDFs, page.close() must be called on every page."""
        num_pages = 30
        pages = [_make_plain_page() for _ in range(num_pages)]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)
            mock_pdfminer.high_level.extract_text.return_value = "text"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        for i, page in enumerate(pages):
            assert (
                page.close.called
            ), f"page.close() was NOT called on plain-text page {i}"

    def test_mixed_pdf_uses_form_extraction_per_page(self):
        """In a mixed PDF, form pages get table extraction while plain pages don't.

        Ensures we don't miss form-style pages and don't waste work
        running form extraction on plain-text pages.
        """
        # Pages 0,2,4 are form-style; pages 1,3 are plain text
        pages = [
            _make_form_page(),  # 0 - form
            _make_plain_page(),  # 1 - plain
            _make_form_page(),  # 2 - form
            _make_plain_page(),  # 3 - plain
            _make_form_page(),  # 4 - form
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        # All pages should have close() called
        for i, page in enumerate(pages):
            assert page.close.called, f"page.close() not called on page {i}"

        # Form pages (0,2,4) should have extract_words called
        for i in [0, 2, 4]:
            assert pages[
                i
            ].extract_words.called, f"extract_words not called on form page {i}"

        # Result should contain table content from form pages
        assert result.text_content is not None
        assert (
            "|" in result.text_content
        ), "Expected markdown table pipes in output from form-style pages"

    def test_only_one_pdfplumber_open_call(self):
        """Verify pdfplumber.open is called exactly once (single pass)."""
        pages = [_make_form_page() for _ in range(10)]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        assert mock_pdfplumber.open.call_count == 1, (
            f"Expected 1 pdfplumber.open call (single pass), "
            f"got {mock_pdfplumber.open.call_count}"
        )

    def test_keep_data_uris_appends_pdf_images_to_plain_text_pdf(self):
        """PDF images should be preserved as data URIs when requested."""
        page = _make_plain_page()
        page.images = [
            {"stream": _FakePdfImageStream(b"\xff\xd8fake jpeg", "DCTDecode")}
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "Plain text content" in result.text_content
        assert "![PDF page 1 image 1](data:image/jpeg;base64," in result.text_content

    def test_keep_data_uris_places_form_row_images_in_table_cells(self):
        """Images positioned inside form rows should stay with those rows."""
        page = _make_form_page()
        page.images = [
            _make_pdf_image(x0=50, top=24, width=36, height=26),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        image_prefix = "![PDF page 1 image 1](data:image/jpeg;base64,"
        alpha_row = next(
            line for line in result.text_content.splitlines() if "Alpha" in line
        )

        assert image_prefix in alpha_row
        assert result.text_content.count(image_prefix) == 1

    def test_keep_data_uris_form_table_images_do_not_expand_table_padding(self):
        """Image data URIs should not leave huge padded table rows after rewrite."""
        page = _make_form_page()
        page.images = [
            _make_pdf_image(x0=50, top=24, width=36, height=26),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        rewritten = re.sub(
            r"data:image/[^)]+",
            "https://example.invalid/image.jpg",
            result.text_content,
        )
        lines = rewritten.splitlines()

        assert max(len(line) for line in lines) < 160
        assert all(
            len(line) < 80 for line in lines if line.startswith("|") and "---" in line
        )

    def test_markdown_table_compacts_long_link_cells(self):
        """Long links should not determine Markdown table padding widths."""
        long_url = f"https://example.invalid/{'a' * 300}/asset.jpg"
        markdown = _to_markdown_table(
            [
                ["Name", "Download"],
                ["Alpha", f"[datasheet]({long_url})"],
            ]
        )
        rewritten = markdown.replace(long_url, "https://example.invalid/asset.jpg")
        lines = rewritten.splitlines()

        assert max(len(line) for line in lines) < 120
        assert all(
            len(line) < 40 for line in lines if line.startswith("|") and "---" in line
        )

    def test_form_table_merges_overlapping_baselines_and_trims_empty_columns(self):
        """Visual table rows should not split when cell baselines differ slightly."""
        page = _make_baseline_offset_table_page()

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        def normalize_row(line: str) -> str:
            return (
                "| "
                + " | ".join(cell.strip() for cell in line.strip("|").split("|"))
                + " |"
            )

        table_rows = [
            normalize_row(line)
            for line in result.text_content.splitlines()
            if line.startswith("|") and ("Protocol" in line or "Order No." in line)
        ]
        normalized_text = "\n".join(
            normalize_row(line) if line.startswith("|") else line
            for line in result.text_content.splitlines()
        )

        assert "| Order No. | R1.001 | R1.002 | R1.003 |" in normalized_text
        assert "Order No.\n|" not in normalized_text
        assert "| Feature | Protocol A | Protocol B | Protocol C |" in normalized_text
        assert all(not row.endswith(" |  |  |  |") for row in table_rows)

    def test_keep_data_uris_places_images_above_table_header_in_header_cells(self):
        """Images just above a table header should stay in their matching columns."""
        page = _make_baseline_offset_table_page()
        page.images = [
            _make_pdf_image(x0=170, top=205, width=36, height=22),
            _make_pdf_image(x0=275, top=205, width=36, height=22),
            _make_pdf_image(x0=380, top=205, width=36, height=22),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        header_row = next(
            line for line in result.text_content.splitlines() if "Protocol A" in line
        )

        for image_number in [1, 2, 3]:
            image_prefix = f"![PDF page 1 image {image_number}](data:image/jpeg;base64,"
            assert image_prefix in header_row
            assert result.text_content.count(image_prefix) == 1

    def test_keep_data_uris_places_form_non_table_row_images_with_row_text(self):
        """Images in form pages should stay near matching non-table rows too."""
        page = _make_form_page()
        page.extract_words.return_value = [
            {
                "text": "Standalone product row",
                "x0": 50,
                "x1": 180,
                "top": 80,
                "bottom": 90,
            },
            *page.extract_words.return_value,
        ]
        page.images = [
            _make_pdf_image(x0=50, top=76, width=36, height=28),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        image_prefix = "![PDF page 1 image 1](data:image/jpeg;base64,"
        standalone_row = next(
            line
            for line in result.text_content.splitlines()
            if "Standalone product row" in line
        )

        assert image_prefix in standalone_row
        assert result.text_content.count(image_prefix) == 1

    def test_keep_data_uris_ignores_far_right_text_when_matching_row_images(self):
        """A distant side label should not claim a nearby product image."""
        page = _make_form_page()
        page.width = 900
        page.extract_words.return_value = [
            *page.extract_words.return_value,
            {
                "text": "Side label",
                "x0": 820,
                "x1": 860,
                "top": 30,
                "bottom": 70,
            },
        ]
        page.images = [
            _make_pdf_image(x0=50, top=45, width=36, height=30),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        image_prefix = "![PDF page 1 image 1](data:image/jpeg;base64,"
        alpha_row = next(
            line for line in result.text_content.splitlines() if "Alpha" in line
        )
        beta_row = next(
            line for line in result.text_content.splitlines() if "Beta" in line
        )

        assert image_prefix not in alpha_row
        assert image_prefix in beta_row
        assert result.text_content.count(image_prefix) == 1

    def test_keep_data_uris_reuses_page_text_for_image_filtering(self):
        """Plain pages with images should extract page text only once."""
        page = _make_plain_page()
        page.images = [
            {"stream": _FakePdfImageStream(b"\xff\xd8fake jpeg", "DCTDecode")}
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert page.extract_text.call_count == 1

    def test_pdf_images_are_not_emitted_by_default(self):
        """The core converter default should remain text-only for PDF images."""
        page = _make_plain_page()
        page.images = [
            {"stream": _FakePdfImageStream(b"\xff\xd8fake jpeg", "DCTDecode")}
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
            )

        assert "Plain text content" in result.text_content
        assert "data:image/" not in result.text_content

    def test_keep_data_uris_converts_flate_cmyk_pdf_images_to_png(self):
        """Raw FlateDecode PDF image streams should be emitted as PNG data URIs."""
        _require_pillow()
        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    b"\x00\xff\xff\x00",
                    "FlateDecode",
                    Width=1,
                    Height=1,
                    BitsPerComponent=8,
                    ColorSpace="DeviceCMYK",
                )
            }
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1](data:image/png;base64," in result.text_content
        assert "iVBOR" in result.text_content

    def test_keep_data_uris_converts_dct_cmyk_pdf_images_to_rgb_jpeg(self):
        """CMYK JPEG streams from PDFs should be normalized for browser display."""
        Image = _require_pillow()

        jpeg_stream = io.BytesIO()
        Image.new("CMYK", (1, 1), (255, 255, 255, 255)).save(jpeg_stream, format="JPEG")
        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    jpeg_stream.getvalue(),
                    "DCTDecode",
                    ColorSpace="DeviceCMYK",
                )
            }
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        match = re.search(
            r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)", result.text_content
        )
        assert match is not None

        converted = Image.open(io.BytesIO(base64.b64decode(match.group(1)))).convert(
            "RGB"
        )
        assert converted.getpixel((0, 0)) == (255, 255, 255)

    def test_pdf_image_filter_skips_obvious_framework_images(self):
        """PDF framework images should be skipped while content images remain."""
        page = _make_plain_page()
        page.images = [
            _make_pdf_image(x0=10, top=10, width=1.5, height=700),
            _make_pdf_image(x0=20, top=20, width=18, height=18),
            _make_pdf_image(x0=80, top=120, width=240, height=140),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1]" not in result.text_content
        assert "![PDF page 1 image 2]" not in result.text_content
        assert "![PDF page 1 image 3](data:image/jpeg;base64," in result.text_content
        assert result.text_content.count("data:image/") == 1

    def test_pdf_image_filter_skips_low_contrast_flate_shadow_masks(self):
        """Soft gray Flate/Indexed masks are PDF rendering layers, not content."""
        _require_pillow()
        width = 100
        height = 100
        data = bytearray([0] * (width * height))
        for y in range(20, 80):
            for x in range(20, 80):
                data[y * width + x] = 1

        page = _make_plain_page()
        page.images = [
            _make_flate_indexed_cmyk_image(
                width=width,
                height=height,
                data=bytes(data),
                palette=bytes([0, 0, 0, 0, 80, 80, 80, 0]),
            )
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "data:image/" not in result.text_content

    def test_pdf_image_filter_keeps_high_contrast_flate_images(self):
        """High-contrast Flate/Indexed images such as QR codes should remain."""
        _require_pillow()
        width = 100
        height = 100
        data = bytes((x + y) % 2 for y in range(height) for x in range(width))

        page = _make_plain_page()
        page.images = [
            _make_flate_indexed_cmyk_image(
                width=width,
                height=height,
                data=data,
                palette=bytes([0, 0, 0, 0, 0, 0, 0, 255]),
            )
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1](data:image/png;base64," in result.text_content

    def test_pdf_image_filter_can_be_disabled_with_environment(self, monkeypatch):
        """Set PDF_IMAGE_FILTER_ENABLED=false to keep all extractable images."""
        monkeypatch.setenv("PDF_IMAGE_FILTER_ENABLED", "false")
        page = _make_plain_page()
        page.images = [
            _make_pdf_image(x0=10, top=10, width=1.5, height=700),
            _make_pdf_image(x0=80, top=120, width=240, height=140),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            md = MarkItDown()
            buf = io.BytesIO(b"fake pdf content")
            from markitdown import StreamInfo

            result = md.convert_stream(
                buf,
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1](data:image/jpeg;base64," in result.text_content
        assert "![PDF page 1 image 2](data:image/jpeg;base64," in result.text_content

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(TEST_FILES_DIR, "test.pdf")),
        reason="test.pdf not available",
    )
    def test_real_pdf_page_cleanup(self):
        """Integration test: verify page.close() is called with a real PDF."""
        import pdfplumber

        close_call_count = 0
        original_close = pdfplumber.page.Page.close

        def tracking_close(self):
            nonlocal close_call_count
            close_call_count += 1
            original_close(self)

        with patch.object(pdfplumber.page.Page, "close", tracking_close):
            md = MarkItDown()
            pdf_path = os.path.join(TEST_FILES_DIR, "test.pdf")
            md.convert(pdf_path)

        assert (
            close_call_count > 0
        ), "page.close() was never called during PDF conversion"


def _generate_table_pdf(num_pages: int) -> bytes:
    """Generate a PDF with table-like content on every page."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for page_num in range(num_pages):
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.set_xy(10, 10)
        pdf.cell(60, 8, "Parameter", border=1)
        pdf.cell(60, 8, "Value", border=1)
        pdf.cell(60, 8, "Unit", border=1)
        pdf.ln()
        for row in range(20):
            y = 18 + row * 8
            if y > 270:
                break
            pdf.set_xy(10, y)
            pdf.cell(60, 8, f"Param_{page_num}_{row}", border=1)
            pdf.cell(60, 8, f"{(page_num * 100 + row) * 1.23:.2f}", border=1)
            pdf.cell(60, 8, "kg/m2", border=1)
    return pdf.output()


@pytest.mark.skipif(
    not _has_fpdf2(),
    reason="fpdf2 not installed",
)
class TestPdfMemoryBenchmark:
    """Benchmark: verify memory stays constant with page.close() fix."""

    def test_memory_does_not_grow_linearly(self):
        """Peak memory for 200 pages should be far less than without the fix.

        Without page.close(), 200 pages uses ~225 MiB (linear growth).
        With the fix, peak memory should stay under 30 MiB.
        """
        from markitdown import StreamInfo

        num_pages = 200
        pdf_bytes = _generate_table_pdf(num_pages)

        gc.collect()
        tracemalloc.start()

        md = MarkItDown()
        buf = io.BytesIO(pdf_bytes)
        md.convert_stream(buf, stream_info=StreamInfo(extension=".pdf"))

        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mib = peak / 1024 / 1024
        # Without the fix this would be ~225 MiB. With the fix it should
        # be well under 30 MiB. Use a generous threshold to avoid flaky
        # failures on different machines.
        assert peak_mib < 30, (
            f"Peak memory {peak_mib:.1f} MiB for {num_pages} pages is too high. "
            f"Expected < 30 MiB with page.close() fix."
        )

    def test_memory_constant_across_page_counts(self):
        """Peak memory should not scale linearly with page count.

        Converts 50-page and 200-page PDFs and asserts the peak memory
        ratio is much less than the 4x page count ratio.
        """
        from markitdown import StreamInfo

        results = {}
        for num_pages in [50, 200]:
            pdf_bytes = _generate_table_pdf(num_pages)

            gc.collect()
            tracemalloc.start()

            md = MarkItDown()
            buf = io.BytesIO(pdf_bytes)
            md.convert_stream(buf, stream_info=StreamInfo(extension=".pdf"))

            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            results[num_pages] = peak

        ratio = results[200] / results[50]
        # With O(n) memory growth the ratio would be ~4x.
        # With the fix it should be close to 1x (well under 2x).
        assert ratio < 2.0, (
            f"Memory ratio 200p/50p = {ratio:.2f}x — "
            f"expected < 2.0x (constant memory). "
            f"50p={results[50] / 1024 / 1024:.1f} MiB, "
            f"200p={results[200] / 1024 / 1024:.1f} MiB"
        )
