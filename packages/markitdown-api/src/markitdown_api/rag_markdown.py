import re
from collections import Counter

_MARKDOWN_IMAGE_RE = re.compile(
    r"^!\[(?P<alt>(?:\\.|[^\]])*)\]" r"\(" r"(?P<target>[^)]*)" r"\)$"
)

_EXACT_SECTION_HEADINGS = {
    "目录",
    "安全服务",
    "工业安全解决方案",
    "定制化产品",
    "工业通讯",
    "工业电子",
    "现场电源分配",
    "快速连接系统",
    "联系我们",
}

_NOISE_LINES = {"+", "-", "--", "是", "否", "×", "√"}


def optimize_markdown_for_rag(markdown: str) -> str:
    """Lightly normalize converted Markdown so downstream chunking has anchors."""

    lines = _merge_split_registered_terms(markdown.splitlines())
    line_counts = Counter(
        line.strip()
        for line in lines
        if _is_context_line(line.strip()) and not _is_standalone_page_number(line)
    )

    output: list[str] = []
    current_context: str | None = None
    title_seen = False

    for raw_line in lines:
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

        if _is_likely_section_heading(line, line_counts):
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
    i = 0
    while i < len(lines):
        line = lines[i]
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


def _is_likely_section_heading(line: str, line_counts: Counter[str]) -> bool:
    if line.startswith("#"):
        return True
    if not _is_context_line(line):
        return False
    if line in _EXACT_SECTION_HEADINGS:
        return True
    if "解决方案" in line and len(line) <= 24:
        return True
    return line_counts[line] >= 3 and _contains_cjk(line)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


def _plain_heading_text(line: str) -> str:
    return line.lstrip("#").strip()
