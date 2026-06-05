import sys
import base64
import io
import os
import re
from typing import BinaryIO, Any

from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from .._exceptions import MissingDependencyException, MISSING_DEPENDENCY_MESSAGE

# Pattern for MasterFormat-style partial numbering (e.g., ".1", ".2", ".10")
PARTIAL_NUMBERING_PATTERN = re.compile(r"^\.\d+$")


def _merge_partial_numbering_lines(text: str) -> str:
    """
    Post-process extracted text to merge MasterFormat-style partial numbering
    with the following text line.

    MasterFormat documents use partial numbering like:
        .1  The intent of this Request for Proposal...
        .2  Available information relative to...

    Some PDF extractors split these into separate lines:
        .1
        The intent of this Request for Proposal...

    This function merges them back together.
    """
    lines = text.split("\n")
    result_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check if this line is ONLY a partial numbering
        if PARTIAL_NUMBERING_PATTERN.match(stripped):
            # Look for the next non-empty line to merge with
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1

            if j < len(lines):
                # Merge the partial numbering with the next line
                next_line = lines[j].strip()
                result_lines.append(f"{stripped} {next_line}")
                i = j + 1  # Skip past the merged line
            else:
                # No next line to merge with, keep as is
                result_lines.append(line)
                i += 1
        else:
            result_lines.append(line)
            i += 1

    return "\n".join(result_lines)


# Load dependencies
_dependency_exc_info = None
try:
    import pdfminer
    import pdfminer.high_level
    from pdfminer.pdftypes import resolve1
    import pdfplumber
except ImportError:
    _dependency_exc_info = sys.exc_info()

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:
    Image = None
    ImageChops = None
    ImageStat = None


ACCEPTED_MIME_TYPE_PREFIXES = [
    "application/pdf",
    "application/x-pdf",
]

ACCEPTED_FILE_EXTENSIONS = [".pdf"]


def _pdf_name(value: Any) -> str:
    name = getattr(value, "name", None)
    if name is None:
        name = str(value)
    return str(name).strip("/'\"")


def _pdf_filter_names(filters: Any) -> list[str]:
    if filters is None:
        return []

    if not isinstance(filters, (list, tuple)):
        filters = [filters]

    names: list[str] = []
    for pdf_filter in filters:
        names.append(_pdf_name(pdf_filter))

    return names


def _resolve_pdf_value(value: Any) -> Any:
    try:
        return resolve1(value)
    except Exception:
        return value


def _detect_image_mimetype(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


def _cmyk_to_rgb_components(
    cyan: int, magenta: int, yellow: int, black: int
) -> tuple[int, int, int]:
    return (
        255 - min(255, cyan + black),
        255 - min(255, magenta + black),
        255 - min(255, yellow + black),
    )


def _indexed_pdf_image_to_pil(
    data: bytes, width: int, height: int, colorspace: list[Any]
) -> Any | None:
    if len(colorspace) < 4:
        return None

    base_colorspace = _resolve_pdf_value(colorspace[1])
    color_count = int(colorspace[2]) + 1
    lookup = _resolve_pdf_value(colorspace[3])

    if hasattr(lookup, "get_data"):
        palette_bytes = lookup.get_data()
    elif isinstance(lookup, bytes):
        palette_bytes = lookup
    elif isinstance(lookup, str):
        palette_bytes = lookup.encode("latin1")
    else:
        return None

    base_name = _pdf_name(base_colorspace)
    components = {
        "DeviceRGB": 3,
        "DeviceCMYK": 4,
        "DeviceGray": 1,
    }.get(base_name)
    if components is None:
        return None

    palette: list[int] = []
    for index in range(min(color_count, 256)):
        start = index * components
        color = palette_bytes[start : start + components]
        if len(color) < components:
            break

        if base_name == "DeviceRGB":
            palette.extend(color[:3])
        elif base_name == "DeviceCMYK":
            palette.extend(_cmyk_to_rgb_components(*color[:4]))
        else:
            shade = color[0]
            palette.extend([shade, shade, shade])

    if not palette:
        return None

    palette.extend([0] * (768 - len(palette)))
    image = Image.frombytes("P", (width, height), data)
    image.putpalette(palette[:768])
    return image.convert("RGB")


def _flate_pdf_image_to_png(data: bytes, attrs: dict[Any, Any]) -> bytes | None:
    image = _flate_pdf_image_to_pil(data, attrs)
    if image is None:
        return None

    png_stream = io.BytesIO()
    image.save(png_stream, format="PNG")
    return png_stream.getvalue()


def _flate_pdf_image_to_pil(data: bytes, attrs: dict[Any, Any]) -> Any | None:
    if Image is None:
        return None

    dimensions = _pdf_stream_dimensions(attrs)
    if dimensions is None:
        return None

    width, height = dimensions
    colorspace = _resolve_pdf_value(attrs.get("ColorSpace"))
    image = None

    if isinstance(colorspace, list) and _pdf_name(colorspace[0]) == "Indexed":
        if len(data) != width * height:
            return None
        image = _indexed_pdf_image_to_pil(data, width, height, colorspace)
    else:
        colorspace_name = _pdf_name(colorspace)
        modes = {
            "DeviceRGB": ("RGB", 3),
            "DeviceCMYK": ("CMYK", 4),
            "DeviceGray": ("L", 1),
        }
        mode_info = modes.get(colorspace_name)
        if mode_info is None:
            return None

        mode, components = mode_info
        if len(data) != width * height * components:
            return None

        image = Image.frombytes(mode, (width, height), data)
        if mode == "CMYK":
            image = image.convert("RGB")

    return image


def _dct_cmyk_pdf_image_to_jpeg(data: bytes, attrs: dict[Any, Any]) -> bytes | None:
    if Image is None or ImageChops is None:
        return None

    colorspace = _resolve_pdf_value(attrs.get("ColorSpace"))
    if _pdf_name(colorspace) != "DeviceCMYK":
        return None

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None

    if image.mode != "CMYK":
        return None

    white = Image.new("CMYK", image.size, (255, 255, 255, 255))
    image = ImageChops.subtract(white, image).convert("RGB")

    jpeg_stream = io.BytesIO()
    image.save(jpeg_stream, format="JPEG", quality=95, optimize=True)
    return jpeg_stream.getvalue()


def _image_mimetype_from_pdf_filter(filters: Any) -> str | None:
    filter_names = _pdf_filter_names(filters)
    if "DCTDecode" in filter_names:
        return "image/jpeg"

    # Only direct browser-friendly image streams are emitted here. Other PDF
    # image filters often represent raw pixel planes, not standalone files.
    return None


def _pdf_image_filter_enabled() -> bool:
    raw = os.environ.get("PDF_IMAGE_FILTER_ENABLED", "true")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _pdf_stream_dimensions(attrs: dict[Any, Any]) -> tuple[int, int] | None:
    try:
        width = int(_resolve_pdf_value(attrs.get("Width")))
        height = int(_resolve_pdf_value(attrs.get("Height")))
        bits = int(_resolve_pdf_value(attrs.get("BitsPerComponent", 8)))
    except Exception:
        return None

    if width <= 0 or height <= 0 or bits != 8:
        return None

    return width, height


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pdf_image_dimensions(image: Any) -> tuple[float | None, float | None]:
    if not isinstance(image, dict):
        return None, None

    width = _float_or_none(image.get("width"))
    height = _float_or_none(image.get("height"))

    if width is None:
        x0 = _float_or_none(image.get("x0"))
        x1 = _float_or_none(image.get("x1"))
        if x0 is not None and x1 is not None:
            width = abs(x1 - x0)

    if height is None:
        top = _float_or_none(image.get("top"))
        bottom = _float_or_none(image.get("bottom"))
        if top is not None and bottom is not None:
            height = abs(bottom - top)
        else:
            y0 = _float_or_none(image.get("y0"))
            y1 = _float_or_none(image.get("y1"))
            if y0 is not None and y1 is not None:
                height = abs(y1 - y0)

    return width, height


def _pdf_image_touches_page_edge(page: Any, image: dict[str, Any]) -> bool:
    page_width = _float_or_none(getattr(page, "width", None))
    page_height = _float_or_none(getattr(page, "height", None))
    x0 = _float_or_none(image.get("x0"))
    x1 = _float_or_none(image.get("x1"))
    top = _float_or_none(image.get("top"))
    bottom = _float_or_none(image.get("bottom"))

    tolerance = 2.0
    touches_left = x0 is not None and x0 <= tolerance
    touches_top = top is not None and top <= tolerance
    touches_right = (
        page_width is not None and x1 is not None and page_width - x1 <= tolerance
    )
    touches_bottom = (
        page_height is not None
        and bottom is not None
        and page_height - bottom <= tolerance
    )
    return touches_left or touches_top or touches_right or touches_bottom


def _is_obvious_framework_pdf_image(
    page: Any, image: Any, page_has_text_layer: bool
) -> bool:
    if not _pdf_image_filter_enabled() or not isinstance(image, dict):
        return False

    width, height = _pdf_image_dimensions(image)
    if width is None or height is None or width <= 0 or height <= 0:
        return False

    if width <= 3 or height <= 3:
        return True

    page_width = _float_or_none(getattr(page, "width", None))
    page_height = _float_or_none(getattr(page, "height", None))
    page_area = (page_width or 0) * (page_height or 0)
    area_ratio = (width * height / page_area) if page_area else 0
    max_dimension = max(width, height)
    aspect_ratio = max(width / height, height / width)

    if aspect_ratio >= 25 and area_ratio <= 0.035:
        return True

    if area_ratio <= 0.0015 and max_dimension <= 80:
        return True

    if _is_low_contrast_flate_mask(image):
        return True

    if (
        page_has_text_layer
        and area_ratio >= 0.90
        and _pdf_image_touches_page_edge(page, image)
    ):
        return True

    return False


def _is_low_contrast_flate_mask(image: Any) -> bool:
    if ImageStat is None or not isinstance(image, dict):
        return False

    stream = image.get("stream")
    if stream is None:
        return False

    attrs = getattr(stream, "attrs", {})
    filters = attrs.get("Filter")
    if "FlateDecode" not in _pdf_filter_names(filters):
        return False

    colorspace = _resolve_pdf_value(attrs.get("ColorSpace"))
    if not (isinstance(colorspace, list) and _pdf_name(colorspace[0]) == "Indexed"):
        return False

    try:
        data = stream.get_data()
    except Exception:
        return False

    image_value = _flate_pdf_image_to_pil(data, attrs)
    if image_value is None:
        return False

    sample = image_value.convert("RGB").resize((64, 64))
    rgb_stat = ImageStat.Stat(sample)
    mean = rgb_stat.mean
    channel_spread = max(mean) - min(mean)
    luminance_stddev = ImageStat.Stat(sample.convert("L")).stddev[0]

    return channel_spread <= 10 and 12 <= luminance_stddev <= 45


def _pdf_image_to_data_uri(image: Any) -> str | None:
    stream = image.get("stream") if isinstance(image, dict) else None
    if stream is None:
        return None

    try:
        data = stream.get_data()
    except Exception:
        return None

    if not data:
        return None

    attrs = getattr(stream, "attrs", {})
    filters = attrs.get("Filter")
    if "DCTDecode" in _pdf_filter_names(filters):
        jpeg_data = _dct_cmyk_pdf_image_to_jpeg(data, attrs)
        if jpeg_data is not None:
            payload = base64.b64encode(jpeg_data).decode("ascii")
            return f"data:image/jpeg;base64,{payload}"

    mimetype = _image_mimetype_from_pdf_filter(filters)
    if mimetype is None:
        mimetype = _detect_image_mimetype(data)
    if mimetype is None:
        if "FlateDecode" in _pdf_filter_names(filters):
            png_data = _flate_pdf_image_to_png(data, attrs)
            if png_data is None:
                return None
            data = png_data
            mimetype = "image/png"
        else:
            return None

    payload = base64.b64encode(data).decode("ascii")
    return f"data:{mimetype};base64,{payload}"


def _extract_pdf_image_markdown(
    page: Any, page_number: int, page_has_text_layer: bool | None = None
) -> list[str]:
    markdown_images: list[str] = []
    if page_has_text_layer is None:
        try:
            page_has_text_layer = bool((page.extract_text() or "").strip())
        except Exception:
            page_has_text_layer = False

    for image_number, image in enumerate(getattr(page, "images", []) or [], start=1):
        if _is_obvious_framework_pdf_image(page, image, page_has_text_layer):
            continue

        data_uri = _pdf_image_to_data_uri(image)
        if data_uri is None:
            continue
        alt_text = f"PDF page {page_number} image {image_number}"
        markdown_images.append(f"![{alt_text}]({data_uri})")
    return markdown_images


def _to_markdown_table(table: list[list[str]], include_separator: bool = True) -> str:
    """Convert a 2D list (rows/columns) into a nicely aligned Markdown table.

    Args:
        table: 2D list of cell values
        include_separator: If True, include header separator row (standard markdown).
                          If False, output simple pipe-separated rows.
    """
    if not table:
        return ""

    # Normalize None → ""
    table = [[cell if cell is not None else "" for cell in row] for row in table]

    # Filter out empty rows
    table = [row for row in table if any(cell.strip() for cell in row)]

    if not table:
        return ""

    # Column widths
    col_widths = [max(len(str(cell)) for cell in col) for col in zip(*table)]

    def fmt_row(row: list[str]) -> str:
        return (
            "|"
            + "|".join(str(cell).ljust(width) for cell, width in zip(row, col_widths))
            + "|"
        )

    if include_separator:
        header, *rows = table
        md = [fmt_row(header)]
        md.append("|" + "|".join("-" * w for w in col_widths) + "|")
        for row in rows:
            md.append(fmt_row(row))
    else:
        md = [fmt_row(row) for row in table]

    return "\n".join(md)


def _group_words_by_y(
    words: list[dict[str, Any]], y_tolerance: int = 5
) -> list[list[dict[str, Any]]]:
    rows_by_y: dict[float, list[dict[str, Any]]] = {}
    for word in words:
        top = _float_or_none(word.get("top"))
        if top is None:
            continue

        y_key = round(top / y_tolerance) * y_tolerance
        if y_key not in rows_by_y:
            rows_by_y[y_key] = []
        rows_by_y[y_key].append(word)

    return [
        sorted(row_words, key=lambda word: _float_or_none(word.get("x0")) or 0)
        for _, row_words in sorted(rows_by_y.items())
        if row_words
    ]


def _word_text(word: dict[str, Any]) -> str:
    return str(word.get("text") or "").strip()


def _join_word_text(words: list[dict[str, Any]]) -> str:
    return " ".join(text for word in words if (text := _word_text(word))).strip()


def _extract_multi_column_text_from_words(page: Any) -> str | None:
    """
    Extract prose from simple multi-column pages in column reading order.

    pdfminer and pdfplumber's default extract_text() are usually better for
    plain prose, but they can interleave independent columns that share similar
    Y positions. This path is intentionally conservative: it only activates
    when several rows show a consistent wide gutter between two text regions.
    """
    words = page.extract_words(keep_blank_chars=True, x_tolerance=3, y_tolerance=3)
    if not words:
        return None

    rows = _group_words_by_y(words)
    if len(rows) < 3:
        return None

    page_width = _float_or_none(getattr(page, "width", None)) or 612.0
    min_gutter = max(64.0, page_width * 0.10)
    split_candidates: list[float] = []

    for row_words in rows:
        if len(row_words) < 2:
            continue

        largest_gap = 0.0
        largest_gap_midpoint: float | None = None
        for previous_word, next_word in zip(row_words, row_words[1:]):
            previous_x1 = _float_or_none(previous_word.get("x1"))
            next_x0 = _float_or_none(next_word.get("x0"))
            if previous_x1 is None or next_x0 is None:
                continue

            gap = next_x0 - previous_x1
            if gap > largest_gap:
                largest_gap = gap
                largest_gap_midpoint = previous_x1 + (gap / 2)

        if largest_gap >= min_gutter and largest_gap_midpoint is not None:
            split_candidates.append(largest_gap_midpoint)

    if len(split_candidates) < 3:
        return None

    split_candidates.sort()
    split_x = split_candidates[len(split_candidates) // 2]

    consistent_candidates = [
        candidate
        for candidate in split_candidates
        if abs(candidate - split_x) <= max(36.0, page_width * 0.06)
    ]
    if len(consistent_candidates) < 3:
        return None

    left_lines: list[str] = []
    right_lines: list[str] = []

    for row_words in rows:
        left_words = [
            word
            for word in row_words
            if (_float_or_none(word.get("x0")) or 0.0) < split_x
        ]
        right_words = [
            word
            for word in row_words
            if (_float_or_none(word.get("x0")) or 0.0) >= split_x
        ]

        left_text = _join_word_text(left_words)
        right_text = _join_word_text(right_words)
        if left_text:
            left_lines.append(left_text)
        if right_text:
            right_lines.append(right_text)

    if len(left_lines) < 2 or len(right_lines) < 2:
        return None

    return "\n\n".join(
        block for block in ["\n".join(left_lines), "\n".join(right_lines)] if block
    )


def _extract_form_content_from_words(page: Any) -> str | None:
    """
    Extract form-style content from a PDF page by analyzing word positions.
    This handles borderless forms/tables where words are aligned in columns.

    Returns markdown with proper table formatting:
    - Tables have pipe-separated columns with header separator rows
    - Non-table content is rendered as plain text

    Returns None if the page doesn't appear to be a form-style document,
    indicating that pdfminer should be used instead for better text spacing.
    """
    words = page.extract_words(keep_blank_chars=True, x_tolerance=3, y_tolerance=3)
    if not words:
        return None

    # Group words by their Y position (rows)
    y_tolerance = 5
    rows_by_y: dict[float, list[dict]] = {}
    for word in words:
        y_key = round(word["top"] / y_tolerance) * y_tolerance
        if y_key not in rows_by_y:
            rows_by_y[y_key] = []
        rows_by_y[y_key].append(word)

    # Sort rows by Y position
    sorted_y_keys = sorted(rows_by_y.keys())
    page_width = page.width if hasattr(page, "width") else 612

    # First pass: analyze each row
    row_info: list[dict] = []
    for y_key in sorted_y_keys:
        row_words = sorted(rows_by_y[y_key], key=lambda w: w["x0"])
        if not row_words:
            continue

        first_x0 = row_words[0]["x0"]
        last_x1 = row_words[-1]["x1"]
        line_width = last_x1 - first_x0
        combined_text = " ".join(w["text"] for w in row_words)

        # Count distinct x-position groups (columns)
        x_positions = [w["x0"] for w in row_words]
        x_groups: list[float] = []
        for x in sorted(x_positions):
            if not x_groups or x - x_groups[-1] > 50:
                x_groups.append(x)

        # Determine row type
        is_paragraph = line_width > page_width * 0.55 and len(combined_text) > 60

        # Check for MasterFormat-style partial numbering (e.g., ".1", ".2")
        # These should be treated as list items, not table rows
        has_partial_numbering = False
        if row_words:
            first_word = row_words[0]["text"].strip()
            if PARTIAL_NUMBERING_PATTERN.match(first_word):
                has_partial_numbering = True

        row_info.append(
            {
                "y_key": y_key,
                "words": row_words,
                "text": combined_text,
                "x_groups": x_groups,
                "is_paragraph": is_paragraph,
                "num_columns": len(x_groups),
                "has_partial_numbering": has_partial_numbering,
            }
        )

    # Collect ALL x-positions from rows with 3+ columns (table-like rows)
    # This gives us the global column structure
    all_table_x_positions: list[float] = []
    for info in row_info:
        if info["num_columns"] >= 3 and not info["is_paragraph"]:
            all_table_x_positions.extend(info["x_groups"])

    if not all_table_x_positions:
        return None

    # Compute adaptive column clustering tolerance based on gap analysis
    all_table_x_positions.sort()

    # Calculate gaps between consecutive x-positions
    gaps = []
    for i in range(len(all_table_x_positions) - 1):
        gap = all_table_x_positions[i + 1] - all_table_x_positions[i]
        if gap > 5:  # Only significant gaps
            gaps.append(gap)

    # Determine optimal tolerance using statistical analysis
    if gaps and len(gaps) >= 3:
        # Use 70th percentile of gaps as threshold (balances precision/recall)
        sorted_gaps = sorted(gaps)
        percentile_70_idx = int(len(sorted_gaps) * 0.70)
        adaptive_tolerance = sorted_gaps[percentile_70_idx]

        # Clamp tolerance to reasonable range [25, 50]
        adaptive_tolerance = max(25, min(50, adaptive_tolerance))
    else:
        # Fallback to conservative value
        adaptive_tolerance = 35

    # Compute global column boundaries using adaptive tolerance
    global_columns: list[float] = []
    for x in all_table_x_positions:
        if not global_columns or x - global_columns[-1] > adaptive_tolerance:
            global_columns.append(x)

    # Adaptive max column check based on page characteristics
    # Calculate average column width
    if len(global_columns) > 1:
        content_width = global_columns[-1] - global_columns[0]
        avg_col_width = content_width / len(global_columns)

        # Forms with very narrow columns (< 30px) are likely dense text
        if avg_col_width < 30:
            return None

        # Compute adaptive max based on columns per inch
        # Typical forms have 3-8 columns per inch
        columns_per_inch = len(global_columns) / (content_width / 72)

        # If density is too high (> 10 cols/inch), likely not a form
        if columns_per_inch > 10:
            return None

        # Adaptive max: allow more columns for wider pages
        # Standard letter is 612pt wide, so scale accordingly
        adaptive_max_columns = int(20 * (page_width / 612))
        adaptive_max_columns = max(15, adaptive_max_columns)  # At least 15

        if len(global_columns) > adaptive_max_columns:
            return None
    else:
        # Single column, not a form
        return None

    # Now classify each row as table row or not
    # A row is a table row if it has words that align with 2+ of the global columns
    for info in row_info:
        if info["is_paragraph"]:
            info["is_table_row"] = False
            continue

        # Rows with partial numbering (e.g., ".1", ".2") are list items, not table rows
        if info["has_partial_numbering"]:
            info["is_table_row"] = False
            continue

        # Count how many global columns this row's words align with
        aligned_columns: set[int] = set()
        for word in info["words"]:
            word_x = word["x0"]
            for col_idx, col_x in enumerate(global_columns):
                if abs(word_x - col_x) < 40:
                    aligned_columns.add(col_idx)
                    break

        # If row uses 2+ of the established columns, it's a table row
        info["is_table_row"] = len(aligned_columns) >= 2

    # Find table regions (consecutive table rows)
    table_regions: list[tuple[int, int]] = []  # (start_idx, end_idx)
    i = 0
    while i < len(row_info):
        if row_info[i]["is_table_row"]:
            start_idx = i
            while i < len(row_info) and row_info[i]["is_table_row"]:
                i += 1
            end_idx = i
            table_regions.append((start_idx, end_idx))
        else:
            i += 1

    # Check if enough rows are table rows (at least 20%)
    total_table_rows = sum(end - start for start, end in table_regions)
    if len(row_info) > 0 and total_table_rows / len(row_info) < 0.2:
        return None

    # Build output - collect table data first, then format with proper column widths
    result_lines: list[str] = []
    num_cols = len(global_columns)

    # Helper function to extract cells from a row
    def extract_cells(info: dict) -> list[str]:
        cells: list[str] = ["" for _ in range(num_cols)]
        for word in info["words"]:
            word_x = word["x0"]
            # Find the correct column using boundary ranges
            assigned_col = num_cols - 1  # Default to last column
            for col_idx in range(num_cols - 1):
                col_end = global_columns[col_idx + 1]
                if word_x < col_end - 20:
                    assigned_col = col_idx
                    break
            if cells[assigned_col]:
                cells[assigned_col] += " " + word["text"]
            else:
                cells[assigned_col] = word["text"]
        return cells

    # Process rows, collecting table data for proper formatting
    idx = 0
    while idx < len(row_info):
        info = row_info[idx]

        # Check if this row starts a table region
        table_region = None
        for start, end in table_regions:
            if idx == start:
                table_region = (start, end)
                break

        if table_region:
            start, end = table_region
            # Collect all rows in this table
            table_data: list[list[str]] = []
            for table_idx in range(start, end):
                cells = extract_cells(row_info[table_idx])
                table_data.append(cells)

            # Calculate column widths for this table
            if table_data:
                col_widths = [
                    max(len(row[col]) for row in table_data) for col in range(num_cols)
                ]
                # Ensure minimum width of 3 for separator dashes
                col_widths = [max(w, 3) for w in col_widths]

                # Format header row
                header = table_data[0]
                header_str = (
                    "| "
                    + " | ".join(
                        cell.ljust(col_widths[i]) for i, cell in enumerate(header)
                    )
                    + " |"
                )
                result_lines.append(header_str)

                # Format separator row
                separator = (
                    "| "
                    + " | ".join("-" * col_widths[i] for i in range(num_cols))
                    + " |"
                )
                result_lines.append(separator)

                # Format data rows
                for row in table_data[1:]:
                    row_str = (
                        "| "
                        + " | ".join(
                            cell.ljust(col_widths[i]) for i, cell in enumerate(row)
                        )
                        + " |"
                    )
                    result_lines.append(row_str)

            idx = end  # Skip to end of table region
        else:
            # Check if we're inside a table region (not at start)
            in_table = False
            for start, end in table_regions:
                if start < idx < end:
                    in_table = True
                    break

            if not in_table:
                # Non-table content
                result_lines.append(info["text"])
            idx += 1

    return "\n".join(result_lines)


def _extract_tables_from_words(page: Any) -> list[list[list[str]]]:
    """
    Extract tables from a PDF page by analyzing word positions.
    This handles borderless tables where words are aligned in columns.

    This function is designed for structured tabular data (like invoices),
    not for multi-column text layouts in scientific documents.
    """
    words = page.extract_words(keep_blank_chars=True, x_tolerance=3, y_tolerance=3)
    if not words:
        return []

    # Group words by their Y position (rows)
    y_tolerance = 5
    rows_by_y: dict[float, list[dict]] = {}
    for word in words:
        y_key = round(word["top"] / y_tolerance) * y_tolerance
        if y_key not in rows_by_y:
            rows_by_y[y_key] = []
        rows_by_y[y_key].append(word)

    # Sort rows by Y position
    sorted_y_keys = sorted(rows_by_y.keys())

    # Find potential column boundaries by analyzing x positions across all rows
    all_x_positions = []
    for words_in_row in rows_by_y.values():
        for word in words_in_row:
            all_x_positions.append(word["x0"])

    if not all_x_positions:
        return []

    # Cluster x positions to find column starts
    all_x_positions.sort()
    x_tolerance_col = 20
    column_starts: list[float] = []
    for x in all_x_positions:
        if not column_starts or x - column_starts[-1] > x_tolerance_col:
            column_starts.append(x)

    # Need at least 3 columns but not too many (likely text layout, not table)
    if len(column_starts) < 3 or len(column_starts) > 10:
        return []

    # Find rows that span multiple columns (potential table rows)
    table_rows = []
    for y_key in sorted_y_keys:
        words_in_row = sorted(rows_by_y[y_key], key=lambda w: w["x0"])

        # Assign words to columns
        row_data = [""] * len(column_starts)
        for word in words_in_row:
            # Find the closest column
            best_col = 0
            min_dist = float("inf")
            for i, col_x in enumerate(column_starts):
                dist = abs(word["x0"] - col_x)
                if dist < min_dist:
                    min_dist = dist
                    best_col = i

            if row_data[best_col]:
                row_data[best_col] += " " + word["text"]
            else:
                row_data[best_col] = word["text"]

        # Only include rows that have content in multiple columns
        non_empty = sum(1 for cell in row_data if cell.strip())
        if non_empty >= 2:
            table_rows.append(row_data)

    # Validate table quality - tables should have:
    # 1. Enough rows (at least 3 including header)
    # 2. Short cell content (tables have concise data, not paragraphs)
    # 3. Consistent structure across rows
    if len(table_rows) < 3:
        return []

    # Check if cells contain short, structured data (not long text)
    long_cell_count = 0
    total_cell_count = 0
    for row in table_rows:
        for cell in row:
            if cell.strip():
                total_cell_count += 1
                # If cell has more than 30 chars, it's likely prose text
                if len(cell.strip()) > 30:
                    long_cell_count += 1

    # If more than 30% of cells are long, this is probably not a table
    if total_cell_count > 0 and long_cell_count / total_cell_count > 0.3:
        return []

    return [table_rows]


class PdfConverter(DocumentConverter):
    """
    Converts PDFs to Markdown.
    Supports extracting tables into aligned Markdown format (via pdfplumber).
    Preserves directly embedded images as data URIs when keep_data_uris=True.
    Falls back to pdfminer if pdfplumber is missing or fails.
    """

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        for prefix in ACCEPTED_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        return False

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        if _dependency_exc_info is not None:
            raise MissingDependencyException(
                MISSING_DEPENDENCY_MESSAGE.format(
                    converter=type(self).__name__,
                    extension=".pdf",
                    feature="pdf",
                )
            ) from _dependency_exc_info[1].with_traceback(
                _dependency_exc_info[2]
            )  # type: ignore[union-attr]

        assert isinstance(file_stream, io.IOBase)

        # Read file stream into BytesIO for compatibility with pdfplumber
        pdf_bytes = io.BytesIO(file_stream.read())
        keep_data_uris = kwargs.get("keep_data_uris", False)

        try:
            # Single pass: check every page for form-style content.
            # Pages with tables/forms get rich extraction; plain-text
            # pages are collected separately. page.close() is called
            # after each page to free pdfplumber's cached objects and
            # keep memory usage constant regardless of page count.
            markdown_chunks: list[str] = []
            image_chunks: list[str] = []
            form_page_count = 0
            multi_column_page_count = 0
            plain_page_indices: list[int] = []

            with pdfplumber.open(pdf_bytes) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    page_content = _extract_form_content_from_words(page)

                    if page_content is not None:
                        form_page_count += 1
                        page_has_text_layer = bool(page_content.strip())
                        if page_content.strip():
                            markdown_chunks.append(page_content)
                    else:
                        text = _extract_multi_column_text_from_words(page)
                        if text is not None:
                            multi_column_page_count += 1
                        else:
                            plain_page_indices.append(page_idx)
                            text = page.extract_text()
                        page_has_text_layer = bool((text or "").strip())
                        if text and text.strip():
                            markdown_chunks.append(text.strip())

                    page_image_chunks = (
                        _extract_pdf_image_markdown(
                            page, page_idx + 1, page_has_text_layer
                        )
                        if keep_data_uris
                        else []
                    )

                    if page_image_chunks:
                        markdown_chunks.extend(page_image_chunks)
                        image_chunks.extend(page_image_chunks)

                    page.close()  # Free cached page data immediately

            # If no pages had form-style content, use pdfminer for
            # the whole document (better text spacing for prose).
            if form_page_count == 0 and multi_column_page_count == 0:
                pdf_bytes.seek(0)
                markdown = pdfminer.high_level.extract_text(pdf_bytes)
                if image_chunks:
                    image_markdown = "\n\n".join(image_chunks)
                    markdown = "\n\n".join(
                        chunk for chunk in [markdown.strip(), image_markdown] if chunk
                    )
            else:
                markdown = "\n\n".join(markdown_chunks).strip()

        except Exception:
            # Fallback if pdfplumber fails
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        # Fallback if still empty
        if not markdown:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        # Post-process to merge MasterFormat-style partial numbering with following text
        markdown = _merge_partial_numbering_lines(markdown)

        return DocumentConverterResult(markdown=markdown)
