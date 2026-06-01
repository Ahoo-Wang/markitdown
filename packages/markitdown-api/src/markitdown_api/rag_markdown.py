import re
from collections import Counter

_MARKDOWN_IMAGE_RE = re.compile(
    r"^!\[(?P<alt>(?:\\.|[^\]])*)\]" r"\(" r"(?P<target>[^)]*)" r"\)$"
)
_FENCE_RE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")

_NOISE_LINES = {"+", "-", "--", "是", "否", "×", "√"}


def optimize_markdown_for_rag(
    markdown: str, *, heading_keywords: list[str] | None = None
) -> str:
    """Lightly normalize converted Markdown so downstream chunking has anchors."""

    lines = _merge_split_registered_terms(markdown.splitlines())
    line_counts = Counter(line.strip() for line in _non_fenced_lines(lines))
    heading_keyword_set = {
        keyword.strip() for keyword in (heading_keywords or []) if keyword.strip()
    }

    output: list[str] = []
    current_context: str | None = None
    title_seen = False
    fence_marker: str | None = None

    for raw_line in lines:
        marker = _fence_marker(raw_line)
        if fence_marker:
            output.append(raw_line)
            if marker == fence_marker:
                fence_marker = None
            continue
        if marker:
            output.append(raw_line)
            fence_marker = marker
            continue

        line = raw_line.strip()

        if not line:
            if output and output[-1] != "":
                output.append("")
            continue

        if _is_standalone_page_number(line):
            continue

        if line in _NOISE_LINES:
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
            output.append(heading)
            current_context = _plain_heading_text(heading)
            continue

        if _is_context_line(line):
            current_context = line
        output.append(line)

    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


def _merge_split_registered_terms(lines: list[str]) -> list[str]:
    merged: list[str] = []
    fence_marker: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        marker = _fence_marker(line)
        if fence_marker:
            merged.append(line)
            if marker == fence_marker:
                fence_marker = None
            i += 1
            continue
        if marker:
            merged.append(line)
            fence_marker = marker
            i += 1
            continue

        if line.strip() == "®" and i + 1 < len(lines):
            blank_buffer = _pop_trailing_blank_lines(merged)
            suffix = lines[i + 1].strip()
            if merged and 1 <= len(suffix) <= 12:
                previous = merged.pop().rstrip()
                merged.append(f"{previous}® {suffix}")
                i += 2
                continue
            merged.extend(blank_buffer)

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
            if marker == fence_marker:
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
    return match.group("marker")[0]


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
