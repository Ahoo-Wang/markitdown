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

from markitdown import MarkItDown, StreamInfo

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
    **stream_attrs,
):
    return {
        "stream": _FakePdfImageStream(data, "DCTDecode", **stream_attrs),
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

    def test_pdf_uses_filename_as_document_title(self):
        page = _make_plain_page()

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(
                    extension=".pdf",
                    mimetype="application/pdf",
                    filename="示例工业公司介绍（for 示例客户）.pdf",
                ),
            )

        assert result.title == "示例工业公司介绍（for 示例客户）"

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
        Image.new("CMYK", (100, 100), (255, 255, 255, 255)).save(
            jpeg_stream, format="JPEG"
        )
        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    jpeg_stream.getvalue(),
                    "DCTDecode",
                    ColorSpace="DeviceCMYK",
                    SMask=object(),
                ),
                "x0": 80,
                "x1": 180,
                "top": 120,
                "bottom": 220,
                "width": 100,
                "height": 100,
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

    def test_keep_data_uris_applies_pdf_soft_mask_and_matte(self):
        """PDF soft masks should become PNG alpha without dark matte fringes."""
        Image = _require_pillow()
        soft_mask = _FakePdfImageStream(
            bytes([0, 128]),
            "FlateDecode",
            Width=2,
            Height=1,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
            Matte=[0, 0, 0],
        )
        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    bytes([0, 0, 0, 128, 0, 0]),
                    "FlateDecode",
                    Width=2,
                    Height=1,
                    BitsPerComponent=8,
                    ColorSpace="DeviceRGB",
                    SMask=soft_mask,
                ),
                "x0": 80,
                "x1": 180,
                "top": 120,
                "bottom": 220,
                "width": 100,
                "height": 100,
            }
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        match = re.search(
            r"data:image/png;base64,([A-Za-z0-9+/=]+)", result.text_content
        )
        assert match is not None

        converted = Image.open(io.BytesIO(base64.b64decode(match.group(1))))
        assert converted.mode == "RGBA"
        assert converted.getpixel((0, 0))[3] == 0
        red, green, blue, alpha = converted.getpixel((1, 0))
        assert red >= 250
        assert green == 0
        assert blue == 0
        assert alpha == 128

    def test_keep_data_uris_applies_soft_mask_to_jpeg_with_alpha(self):
        """JPEG image XObjects with a soft mask must retain an alpha channel."""
        Image = _require_pillow()
        jpeg_stream = io.BytesIO()
        Image.new("RGB", (2, 2), (255, 0, 0)).save(jpeg_stream, format="JPEG")
        soft_mask = _FakePdfImageStream(
            bytes([0, 255, 128, 255]),
            "FlateDecode",
            Width=2,
            Height=2,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
        )
        page = _make_plain_page()
        page.images = [
            _make_pdf_image(
                x0=80,
                top=120,
                width=100,
                height=100,
                data=jpeg_stream.getvalue(),
                ColorSpace="DeviceRGB",
                SMask=soft_mask,
            )
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        match = re.search(
            r"data:image/(?:png|webp);base64,([A-Za-z0-9+/=]+)",
            result.text_content,
        )
        assert match is not None
        converted = Image.open(io.BytesIO(base64.b64decode(match.group(1))))
        assert converted.mode == "RGBA"
        assert list(converted.getchannel("A").tobytes()) == [0, 255, 128, 255]

    def test_pdf_image_filter_skips_translucent_grayscale_effect_layer(self):
        """A grayscale soft effect paired with content is a rendering layer."""
        Image = _require_pillow()
        width = 100
        height = 100
        base = bytes(
            40 + ((x + y) % 40)
            for y in range(height)
            for x in range(width)
            for _ in range(3)
        )
        soft_mask = _FakePdfImageStream(
            bytes(80 + ((x + y) % 80) for y in range(height) for x in range(width)),
            "FlateDecode",
            Width=width,
            Height=height,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
        )
        jpeg_stream = io.BytesIO()
        Image.new("RGB", (width, height), (255, 0, 0)).save(jpeg_stream, format="JPEG")
        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    base,
                    "FlateDecode",
                    Width=width,
                    Height=height,
                    BitsPerComponent=8,
                    ColorSpace="DeviceRGB",
                    SMask=soft_mask,
                ),
                "x0": 80,
                "x1": 180,
                "top": 120,
                "bottom": 220,
                "width": width,
                "height": height,
            },
            _make_pdf_image(
                x0=80,
                top=120,
                width=width,
                height=height,
                data=jpeg_stream.getvalue(),
            ),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1]" not in result.text_content
        assert "![PDF page 1 image 2](data:image/jpeg;base64," in result.text_content
        assert result.text_content.count("data:image/") == 1

    def test_pdf_image_filter_keeps_meaningful_translucent_grayscale_image(self):
        """A standalone translucent grayscale logo is content, not an effect."""
        Image = _require_pillow()
        width = 100
        height = 40
        base = bytearray([128] * (width * height * 3))
        alpha = bytearray(width * height)
        for y in range(8, 32):
            for x in range(10, 90):
                pixel = y * width + x
                base[pixel * 3 : pixel * 3 + 3] = bytes([60, 60, 60])
                alpha[pixel] = 160

        soft_mask = _FakePdfImageStream(
            bytes(alpha),
            "FlateDecode",
            Width=width,
            Height=height,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
        )
        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    bytes(base),
                    "FlateDecode",
                    Width=width,
                    Height=height,
                    BitsPerComponent=8,
                    ColorSpace="DeviceRGB",
                    SMask=soft_mask,
                ),
                "x0": 80,
                "x1": 180,
                "top": 120,
                "bottom": 160,
                "width": width,
                "height": height,
            }
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        match = re.search(
            r"data:image/png;base64,([A-Za-z0-9+/=]+)", result.text_content
        )
        assert match is not None
        converted = Image.open(io.BytesIO(base64.b64decode(match.group(1))))
        assert converted.mode == "RGBA"
        assert converted.getchannel("A").getextrema() == (0, 160)

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

    def test_pdf_image_filter_skips_solid_black_images(self):
        """Low-opacity black soft-mask layers should not become black rectangles."""
        Image = _require_pillow()
        width = 100
        height = 100
        soft_mask = _FakePdfImageStream(
            bytes([80]) * width * height,
            "FlateDecode",
            Width=width,
            Height=height,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
        )

        jpeg_stream = io.BytesIO()
        Image.new("RGB", (width, height), (0, 0, 0)).save(jpeg_stream, format="JPEG")

        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    bytes(width * height * 3),
                    "FlateDecode",
                    Width=width,
                    Height=height,
                    BitsPerComponent=8,
                    ColorSpace="DeviceRGB",
                    SMask=soft_mask,
                ),
                "x0": 80,
                "x1": 80 + width,
                "top": 120,
                "bottom": 120 + height,
                "width": width,
                "height": height,
            },
            _make_pdf_image(
                x0=220,
                top=120,
                width=width,
                height=height,
                data=jpeg_stream.getvalue(),
                SMask=soft_mask,
            ),
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

    def test_pdf_image_filter_keeps_solid_black_images_without_smask(self):
        """Standalone black content must not be mistaken for a transparency layer."""
        Image = _require_pillow()
        width = 100
        height = 100

        jpeg_stream = io.BytesIO()
        Image.new("RGB", (width, height), (0, 0, 0)).save(jpeg_stream, format="JPEG")

        page = _make_plain_page()
        page.images = [
            {
                "stream": _FakePdfImageStream(
                    bytes(width * height * 3),
                    "FlateDecode",
                    Width=width,
                    Height=height,
                    BitsPerComponent=8,
                    ColorSpace="DeviceRGB",
                ),
                "x0": 80,
                "x1": 80 + width,
                "top": 120,
                "bottom": 120 + height,
                "width": width,
                "height": height,
            },
            _make_pdf_image(
                x0=220,
                top=120,
                width=width,
                height=height,
                data=jpeg_stream.getvalue(),
            ),
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
        assert "![PDF page 1 image 2](data:image/jpeg;base64," in result.text_content

    def test_pdf_image_filter_skips_solid_black_cmyk_smask(self):
        """CMYK filtering must use the same inverted-color normalization as output."""
        Image = _require_pillow()
        width = 100
        height = 100

        jpeg_stream = io.BytesIO()
        Image.new("CMYK", (width, height), (0, 0, 0, 0)).save(
            jpeg_stream, format="JPEG"
        )
        soft_mask = _FakePdfImageStream(
            bytes([80]) * width * height,
            "FlateDecode",
            Width=width,
            Height=height,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
        )

        page = _make_plain_page()
        page.images = [
            _make_pdf_image(
                x0=80,
                top=120,
                width=width,
                height=height,
                data=jpeg_stream.getvalue(),
                ColorSpace="DeviceCMYK",
                SMask=soft_mask,
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

    def test_pdf_image_filter_keeps_solid_black_icon_with_opaque_soft_mask(self):
        """A meaningful opaque mask must preserve legitimate black artwork."""
        Image = _require_pillow()
        width = 100
        height = 100
        jpeg_stream = io.BytesIO()
        Image.new("RGB", (width, height), (0, 0, 0)).save(
            jpeg_stream, format="JPEG", quality=95
        )
        alpha = bytearray(width * height)
        for y in range(25, 75):
            for x in range(25, 75):
                alpha[y * width + x] = 255
        soft_mask = _FakePdfImageStream(
            bytes(alpha),
            "FlateDecode",
            Width=width,
            Height=height,
            BitsPerComponent=8,
            ColorSpace="DeviceGray",
        )

        page = _make_plain_page()
        page.images = [
            _make_pdf_image(
                x0=80,
                top=120,
                width=width,
                height=height,
                data=jpeg_stream.getvalue(),
                ColorSpace="DeviceRGB",
                SMask=soft_mask,
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

        match = re.search(
            r"data:image/(?:png|webp);base64,([A-Za-z0-9+/=]+)",
            result.text_content,
        )
        assert match is not None
        converted = Image.open(io.BytesIO(base64.b64decode(match.group(1))))
        assert converted.mode == "RGBA"
        assert converted.getchannel("A").getextrema() == (0, 255)

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

    def test_pdf_images_deduplicate_repeated_headers_across_pages(self):
        """A header repeated on at least three pages is a running header."""
        pages = [_make_plain_page(), _make_plain_page(), _make_plain_page()]
        for page in pages:
            page.images = [
                _make_pdf_image(
                    x0=440,
                    top=20,
                    width=120,
                    height=40,
                    data=b"\xff\xd8shared header",
                )
            ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1]" in result.text_content
        assert "![PDF page 2 image 1]" not in result.text_content
        assert "![PDF page 3 image 1]" not in result.text_content
        assert result.text_content.count("data:image/") == 1

    def test_pdf_images_keep_two_visually_equivalent_top_images(self):
        """Two top-of-page matches are insufficient to confirm a running header."""
        Image = _require_pillow()
        encoded_logos = []
        for size, quality in [((120, 40), 90), ((240, 80), 95)]:
            logo = Image.new("RGB", size, "white")
            logo.paste((80, 180, 40), (0, 0, size[0] // 4, size[1]))
            logo.paste(
                (10, 10, 10),
                (size[0] // 3, size[1] // 4, size[0], size[1] * 3 // 4),
            )
            jpeg_stream = io.BytesIO()
            logo.save(jpeg_stream, format="JPEG", quality=quality)
            encoded_logos.append(jpeg_stream.getvalue())

        pages = [_make_plain_page(), _make_plain_page()]
        for page, encoded_logo in zip(pages, encoded_logos):
            page.images = [
                _make_pdf_image(
                    x0=440,
                    top=20,
                    width=120,
                    height=40,
                    data=encoded_logo,
                )
            ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1]" in result.text_content
        assert "![PDF page 2 image 1]" in result.text_content
        assert result.text_content.count("data:image/") == 2

    def test_pdf_images_deduplicate_identical_content_within_page(self):
        """Identical image content on one page should only be emitted once."""
        page = _make_plain_page()
        page.images = [
            _make_pdf_image(
                x0=80,
                top=180,
                width=180,
                height=100,
                data=b"\xff\xd8same page product",
            ),
            _make_pdf_image(
                x0=300,
                top=180,
                width=180,
                height=100,
                data=b"\xff\xd8same page product",
            ),
        ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open([page])
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1]" in result.text_content
        assert "![PDF page 1 image 2]" not in result.text_content
        assert result.text_content.count("data:image/") == 1

    def test_pdf_images_keep_identical_content_on_different_non_header_pages(self):
        """Repeated product images on different pages preserve page semantics."""
        pages = [_make_plain_page(), _make_plain_page()]
        for page in pages:
            page.images = [
                _make_pdf_image(
                    x0=80,
                    top=180,
                    width=180,
                    height=100,
                    data=b"\xff\xd8shared product",
                )
            ]

        with patch(
            "markitdown.converters._pdf_converter.pdfplumber"
        ) as mock_pdfplumber, patch(
            "markitdown.converters._pdf_converter.pdfminer"
        ) as mock_pdfminer:
            mock_pdfplumber.open.side_effect = _mock_pdfplumber_open(pages)
            mock_pdfminer.high_level.extract_text.return_value = "Plain text content"

            result = MarkItDown().convert_stream(
                io.BytesIO(b"fake pdf content"),
                stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"),
                keep_data_uris=True,
            )

        assert "![PDF page 1 image 1]" in result.text_content
        assert "![PDF page 2 image 1]" in result.text_content
        assert result.text_content.count("data:image/") == 2

    def test_pdf_image_filter_can_be_disabled_with_environment(self, monkeypatch):
        """Set PDF_IMAGE_FILTER_ENABLED=false to keep all extractable images."""
        monkeypatch.setenv("PDF_IMAGE_FILTER_ENABLED", "false")
        page = _make_plain_page()
        page.images = [
            _make_pdf_image(
                x0=10,
                top=10,
                width=1.5,
                height=700,
                data=b"\xff\xd8framework image",
            ),
            _make_pdf_image(
                x0=80,
                top=120,
                width=240,
                height=140,
                data=b"\xff\xd8content image",
            ),
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
