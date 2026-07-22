import re
from collections import Counter

_MARKDOWN_IMAGE_RE = re.compile(
    r"^!\[(?P<alt>(?:\\.|[^\]])*)\]" r"\(" r"(?P<target>[^)]*)" r"\)$"
)
_FENCE_RE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)?\|?$")
_DATE_RE = re.compile(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b")
_PDF_IMAGE_LINE_RE = re.compile(r"^!\[(?:.* - )?PDF page \d+ image \d+\]\(")
_WRAPPED_DATA_IMAGE_START_RE = re.compile(
    r"^!\[(?:\\.|[^\]])*\]\(" r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]*$"
)
_WRAPPED_DATA_IMAGE_RE = re.compile(
    r"^!\[(?P<alt>(?:\\.|[^\]])*)\]"
    r"\("
    r"data:(?P<mimetype>image/[A-Za-z0-9.+-]+);base64,"
    r"(?P<payload>[A-Za-z0-9+/=\r\n]+)"
    r'(?P<title>\s+"(?:\\.|[^"])*")?'
    r"\)$"
)
_CJK_SPACING_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")

_NOISE_LINES = {"+", "-", "--", "是", "否", "×", "√", "", "•"}


def optimize_markdown_for_rag(
    markdown: str,
    *,
    heading_keywords: list[str] | None = None,
    document_title: str | None = None,
) -> str:
    """Lightly normalize converted Markdown so downstream chunking has anchors."""

    lines = _merge_wrapped_data_image_lines(markdown.splitlines())
    lines = _merge_split_registered_terms(lines)
    lines = _remove_repeated_page_footers(lines)
    line_counts = Counter(line.strip() for line in _non_fenced_lines(lines))
    heading_keyword_set = {
        keyword.strip() for keyword in (heading_keywords or []) if keyword.strip()
    }

    output: list[str] = []
    current_context: str | None = None
    title_seen = False
    fence_marker: str | None = None

    normalized_document_title = _normalize_document_title(document_title)
    source_title_candidate_checked = False
    if normalized_document_title:
        output.append(f"# {normalized_document_title}")
        current_context = normalized_document_title
        title_seen = True

    for raw_line in lines:
        marker = _fence_marker(raw_line)
        if fence_marker:
            output.append(raw_line)
            if _is_closing_fence(marker, fence_marker):
                fence_marker = None
            continue
        if marker:
            output.append(raw_line)
            fence_marker = marker
            continue

        line = _normalize_cjk_spacing(raw_line.strip())

        if not line:
            if output and output[-1] != "":
                output.append("")
            continue

        if _is_standalone_page_number(line):
            continue

        if line in _NOISE_LINES:
            continue

        if normalized_document_title and not source_title_candidate_checked:
            source_title_candidate_checked = True
            if _plain_heading_text(line) == normalized_document_title:
                continue

        image_match = _MARKDOWN_IMAGE_RE.match(line)
        if image_match:
            output.append(_enrich_image_alt(image_match, current_context))
            continue

        if _is_table_line(line):
            output.append(line)
            continue

        if not title_seen:
            title_seen = True
            if line.startswith("#"):
                output.append(line)
            else:
                output.append(f"# {line}")
            current_context = _plain_heading_text(output[-1])
            continue

        if _is_likely_section_heading(line, line_counts, heading_keyword_set):
            heading = line if line.startswith("#") else f"## {line}"
            heading_text = _plain_heading_text(heading)
            output.append(heading)
            current_context = heading_text
            continue

        if _is_context_line(line):
            current_context = line
        output.append(line)

    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


def _normalize_document_title(title: str | None) -> str | None:
    if title is None:
        return None

    normalized = title.strip().lstrip("#").strip()
    return normalized or None


def _normalize_cjk_spacing(line: str) -> str:
    return _CJK_SPACING_RE.sub("", line)


def _remove_repeated_page_footers(lines: list[str]) -> list[str]:
    boundary_footer_signatures = Counter(
        signature
        for line_index, line in _non_fenced_indexed_lines(lines)
        if _next_nonblank_line_is_pdf_image(lines, line_index + 1)
        if (signature := _page_footer_signature(line)) is not None
    )
    repeated_footer_dates = {
        date_match.group(0)
        for signature, count in boundary_footer_signatures.items()
        if count >= 3
        if (date_match := _DATE_RE.search(signature)) is not None
    }

    output: list[str] = []
    fence_marker: str | None = None
    skip_separator = False
    for line_index, line in enumerate(lines):
        marker = _fence_marker(line)
        if fence_marker:
            output.append(line)
            if _is_closing_fence(marker, fence_marker):
                fence_marker = None
            continue
        if marker:
            output.append(line)
            fence_marker = marker
            continue

        stripped = line.strip()
        if skip_separator and _is_table_separator_line(stripped):
            skip_separator = False
            continue
        skip_separator = False

        signature = _page_footer_signature(stripped)
        standalone_date = _DATE_RE.fullmatch(stripped)
        is_pdf_footer_boundary = _next_nonblank_line_is_pdf_image(lines, line_index + 1)
        if (
            standalone_date is not None
            and standalone_date.group(0) in repeated_footer_dates
            and is_pdf_footer_boundary
        ) or (signature is not None and boundary_footer_signatures[signature] >= 3):
            skip_separator = stripped.startswith("|")
            continue

        output.append(line)

    return output


def _next_nonblank_line_is_pdf_image(lines: list[str], start: int) -> bool:
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or _is_table_separator_line(stripped):
            continue
        return _PDF_IMAGE_LINE_RE.match(stripped) is not None
    return False


def _is_table_separator_line(line: str) -> bool:
    return _TABLE_SEPARATOR_RE.match(line) is not None or (
        line.startswith("|")
        and "-" in line
        and re.fullmatch(r"[\s|:-]+", line) is not None
    )


def _non_fenced_indexed_lines(lines: list[str]):
    fence_marker: str | None = None
    for line_index, line in enumerate(lines):
        marker = _fence_marker(line)
        if fence_marker:
            if _is_closing_fence(marker, fence_marker):
                fence_marker = None
            continue
        if marker:
            fence_marker = marker
            continue
        yield line_index, line.strip()


def _page_footer_signature(line: str) -> str | None:
    if not line or (date_match := _DATE_RE.search(line)) is None:
        return None

    flattened = re.sub(r"\s*\|\s*", " ", line).strip()
    flattened = re.sub(r"\s+", " ", flattened)
    date_match = _DATE_RE.search(flattened)
    page_match = re.search(r"\b\d{1,3}\s*$", flattened)
    if (
        date_match is None
        or page_match is None
        or page_match.start() <= date_match.end()
    ):
        return None

    middle = flattened[date_match.end() : page_match.start()]
    if re.search(r"[^\W\d_]", middle, re.UNICODE) is None:
        return None

    return f"{flattened[: page_match.start()]}#"


def _merge_wrapped_data_image_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    fence_marker: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        marker = _fence_marker(line)
        if fence_marker:
            merged.append(line)
            if _is_closing_fence(marker, fence_marker):
                fence_marker = None
            i += 1
            continue
        if marker:
            merged.append(line)
            fence_marker = marker
            i += 1
            continue

        candidate = line.strip()
        if not _WRAPPED_DATA_IMAGE_START_RE.match(candidate):
            merged.append(line)
            i += 1
            continue

        merged_image = False
        j = i + 1
        while j < len(lines):
            continuation = lines[j].strip()
            if not continuation or _fence_marker(lines[j]):
                break

            candidate = f"{candidate}\n{continuation}"
            image_match = _WRAPPED_DATA_IMAGE_RE.fullmatch(candidate)
            if image_match is not None:
                payload = "".join(image_match.group("payload").split())
                title = image_match.group("title") or ""
                merged.append(
                    f"![{image_match.group('alt')}]"
                    f"(data:{image_match.group('mimetype')};base64,{payload}{title})"
                )
                i = j + 1
                merged_image = True
                break

            if re.fullmatch(r"[A-Za-z0-9+/=]+", continuation) is None:
                break
            j += 1

        if merged_image:
            continue

        merged.append(line)
        i += 1

    return merged


def _merge_split_registered_terms(lines: list[str]) -> list[str]:
    merged: list[str] = []
    fence_marker: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        marker = _fence_marker(line)
        if fence_marker:
            merged.append(line)
            if _is_closing_fence(marker, fence_marker):
                fence_marker = None
            i += 1
            continue
        if marker:
            merged.append(line)
            fence_marker = marker
            i += 1
            continue

        if line.strip() == "®":
            blank_buffer = _pop_trailing_blank_lines(merged)
            suffix = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if merged and 1 <= len(suffix) <= 12:
                previous = merged.pop().rstrip()
                merged.append(f"{previous}® {suffix}")
                i += 2
                continue
            merged.extend(blank_buffer)
            merged.append(line)
            i += 1
            continue

        if line.strip().startswith("®"):
            blank_buffer = _pop_trailing_blank_lines(merged)
            if merged:
                previous = merged.pop().rstrip()
                merged.append(f"{previous}{line.strip()}")
                i += 1
                continue
            merged.extend(blank_buffer)

        merged.append(line)
        i += 1
    return merged


def _non_fenced_lines(lines: list[str]):
    fence_marker: str | None = None
    for line in lines:
        marker = _fence_marker(line)
        if fence_marker:
            if _is_closing_fence(marker, fence_marker):
                fence_marker = None
            continue
        if marker:
            fence_marker = marker
            continue
        stripped = line.strip()
        if _is_context_line(stripped) and not _is_standalone_page_number(stripped):
            yield line


def _fence_marker(line: str) -> str | None:
    match = _FENCE_RE.match(line)
    if not match:
        return None
    return match.group("marker")


def _is_closing_fence(marker: str | None, opening_marker: str) -> bool:
    return (
        marker is not None
        and marker[0] == opening_marker[0]
        and len(marker) >= len(opening_marker)
    )


def _pop_trailing_blank_lines(lines: list[str]) -> list[str]:
    blanks: list[str] = []
    while lines and not lines[-1].strip():
        blanks.insert(0, lines.pop())
    return blanks


def _enrich_image_alt(match: re.Match, current_context: str | None) -> str:
    alt = match.group("alt")
    target = match.group("target")
    if current_context and alt.startswith("PDF page ") and current_context not in alt:
        alt = f"{_escape_alt_text(current_context)} - {alt}"
    return f"![{alt}]({target})"


def _escape_alt_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("]", "\\]")


def _is_standalone_page_number(line: str) -> bool:
    stripped = line.strip()
    return stripped.isdigit() and 1 <= len(stripped) <= 3


def _is_table_line(line: str) -> bool:
    return "|" in line


def _is_context_line(line: str) -> bool:
    if not line or line.startswith("#"):
        return False
    if line in _NOISE_LINES or len(line) <= 1:
        return False
    if _is_table_line(line) or _MARKDOWN_IMAGE_RE.match(line):
        return False
    if _is_standalone_page_number(line):
        return False
    if re.match(r"^\d+[\.)]\s+", line):
        return False
    if any(mark in line for mark in "，。！？；：,.!?;:"):
        return False
    return len(line) <= 36


def _is_likely_section_heading(
    line: str, line_counts: Counter[str], heading_keywords: set[str]
) -> bool:
    if line.startswith("#"):
        return True
    if not _is_context_line(line):
        return False
    if line in heading_keywords:
        return True
    return line_counts[line] >= 3 and _contains_cjk(line)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _plain_heading_text(line: str) -> str:
    return line.lstrip("#").strip()
