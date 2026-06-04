import re
import markdownify

from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse, urlunparse

from markitdown._url_utils import convert_relative_to_absolute_path


class _CustomMarkdownify(markdownify.MarkdownConverter):
    """
    A custom version of markdownify's MarkdownConverter. Changes include:

    - Altering the default heading style to use '#', '##', etc.
    - Removing javascript hyperlinks.
    - Truncating images with large data:uri sources.
    - Ensuring URIs are properly escaped, and do not conflict with Markdown syntax
    """

    _SUPPORTED_LINK_SCHEMES = {"http", "https", "file"}

    def __init__(self, **options: Any):
        options["heading_style"] = options.get("heading_style", markdownify.ATX)
        options["keep_data_uris"] = options.get("keep_data_uris", False)
        options["url"] = options.get("url", None)
        # Explicitly cast options to the expected type if necessary
        super().__init__(**options)

    def convert_hn(
        self,
        n: int,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ) -> str:
        """Same as usual, but be sure to start with a new line"""
        if not convert_as_inline:
            if not re.search(r"^\n", text):
                return "\n" + super().convert_hn(n, el, text, convert_as_inline)  # type: ignore

        return super().convert_hn(n, el, text, convert_as_inline)  # type: ignore

    def convert_a(
        self,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ):
        """Same as usual converter, but removes Javascript links and escapes URIs."""
        prefix, suffix, text = markdownify.chomp(text)  # type: ignore
        raw_href = el.get("href")
        if self._has_unsupported_scheme(raw_href):
            return "" if not text else "%s%s%s" % (prefix, text, suffix)

        href = raw_href
        href = convert_relative_to_absolute_path(self.options["url"], href)
        title = el.get("title")
        title_used_as_text = False
        if not text:
            if not href or self._has_previous_duplicate_empty_anchor(
                el, raw_href, title
            ):
                return ""
            text = self._fallback_link_text(title, href)
            title_used_as_text = bool(text)
            if not text:
                return ""

        if el.find_parent("pre") is not None:
            return text

        # Escape URIs and skip non-http or file schemes
        if href:
            try:
                parsed_url = urlparse(href)  # type: ignore
                if parsed_url.scheme and parsed_url.scheme.lower() not in ["http", "https", "file"]:  # type: ignore
                    return "%s%s%s" % (prefix, text, suffix)
                href = urlunparse(parsed_url._replace(path=quote(unquote(parsed_url.path))))  # type: ignore
            except ValueError:  # It's not clear if this ever gets thrown
                return "%s%s%s" % (prefix, text, suffix)

        # For the replacement see #29: text nodes underscores are escaped
        if (
            self.options["autolinks"]
            and text.replace(r"\_", "_") == href
            and not title
            and not self.options["default_title"]
        ):
            # Shortcut syntax
            return "<%s>" % href
        if self.options["default_title"] and not title:
            title = href
        title_part = (
            ' "%s"' % title.replace('"', r"\"")
            if title and not title_used_as_text
            else ""
        )
        return (
            "%s[%s](%s%s)%s" % (prefix, text, href, title_part, suffix)
            if href
            else text
        )

    @classmethod
    def _has_unsupported_scheme(cls, href: Any) -> bool:
        if not isinstance(href, str) or not href:
            return False

        try:
            scheme = urlparse(href).scheme.lower()
        except ValueError:
            return True

        return bool(scheme and scheme not in cls._SUPPORTED_LINK_SCHEMES)

    def _fallback_link_text(self, title: Any, href: str) -> str:
        if isinstance(title, str) and title.strip():
            text = re.sub(r"\s+", " ", title.strip())
            return self._escape_link_text(text)

        return href

    def _escape_link_text(self, text: str) -> str:
        text = text.replace("\\", "\\\\")
        text = text.replace("[", r"\[")
        text = text.replace("]", r"\]")
        if self.options["escape_asterisks"]:
            text = text.replace("*", r"\*")
        if self.options["escape_underscores"]:
            text = text.replace("_", r"\_")
        return text

    @staticmethod
    def _has_previous_duplicate_empty_anchor(el: Any, href: Any, title: Any) -> bool:
        if not href or not hasattr(el, "find_previous_siblings"):
            return False

        normalized_title = title.strip() if isinstance(title, str) else title
        for sibling in el.find_previous_siblings("a"):
            sibling_title = sibling.get("title")
            normalized_sibling_title = (
                sibling_title.strip()
                if isinstance(sibling_title, str)
                else sibling_title
            )
            if (
                sibling.get("href") == href
                and normalized_sibling_title == normalized_title
                and not sibling.get_text(strip=True)
            ):
                return True

        return False

    def convert_img(
        self,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ) -> str:
        """Same as usual converter, but removes data URIs"""

        alt = el.attrs.get("alt", None) or ""
        src = el.attrs.get("src", None) or el.attrs.get("data-src", None) or ""
        title = el.attrs.get("title", None) or ""
        title_part = ' "%s"' % title.replace('"', r"\"") if title else ""
        # Remove all line breaks from alt
        alt = alt.replace("\n", " ")
        if (
            convert_as_inline
            and el.parent.name not in self.options["keep_inline_images_in"]
        ):
            return alt

        # Remove dataURIs
        if src.startswith("data:") and not self.options["keep_data_uris"]:
            src = src.split(",")[0] + "..."

        src = convert_relative_to_absolute_path(self.options["url"], src)

        return "![%s](%s%s)" % (alt, src, title_part)

    def convert_input(
        self,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ) -> str:
        """Convert checkboxes to Markdown [x]/[ ] syntax."""

        if el.get("type") == "checkbox":
            return "[x] " if el.has_attr("checked") else "[ ] "
        return ""

    def convert_soup(self, soup: Any) -> str:
        return super().convert_soup(soup)  # type: ignore
