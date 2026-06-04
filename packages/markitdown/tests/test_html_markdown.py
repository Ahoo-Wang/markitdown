from io import BytesIO

from markitdown import MarkItDown, StreamInfo


def test_empty_anchor_uses_title_as_link_text():
    html = """
    <html>
      <body>
        <a
          href="/downloads/product-guide.pdf"
          title="Product guide"
        ></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://docs.example.test/products/example-item/",
        ),
    )

    expected_link = (
        "[Product guide]" "(https://docs.example.test/downloads/product-guide.pdf)"
    )

    assert expected_link in result.markdown


def test_duplicate_empty_anchors_with_same_href_are_emitted_once():
    html = """
    <html>
      <body>
        <a href="/download.pdf" title="Download PDF"></a>
        <a href="/download.pdf" title="Download PDF"></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
    )

    expected_link = "[Download PDF](https://example.com/download.pdf)"

    assert result.markdown.count(expected_link) == 1


def test_empty_anchor_without_href_does_not_emit_title_text():
    html = """
    <html>
      <body>
        <a id="section" title="Section title"></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
    )

    assert result.markdown == ""


def test_empty_anchor_title_fallback_escapes_link_text():
    html = """
    <html>
      <body>
        <a
          href="/download.pdf"
          title="A ](https://bad.example)
                 second line"
        ></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
    )

    expected_link = (
        r"[A \](https://bad.example) second line]" "(https://example.com/download.pdf)"
    )

    assert result.markdown == expected_link


def test_empty_anchor_href_fallback_escapes_link_text():
    html = """
    <html>
      <body>
        <a href="/a](bad).pdf"></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
    )

    expected_link = (
        r"[https://example.com/a\](bad).pdf]" "(https://example.com/a%5D%28bad%29.pdf)"
    )

    assert result.markdown == expected_link


def test_empty_anchor_href_fallback_ignores_unsupported_schemes():
    html = """
    <html>
      <body>
        <a href="javascript:alert(1)"></a>
        <a href="mailto:test@example.com" title="Email"></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
    )

    assert result.markdown == ""


def test_empty_anchor_in_pre_remains_empty():
    html = """
    <html>
      <body>
        <pre><a href="/download.pdf"></a></pre>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
    )

    assert result.markdown == ""


def test_empty_anchor_href_fallback_preserves_default_title():
    html = """
    <html>
      <body>
        <a href="/download.pdf"></a>
      </body>
    </html>
    """

    result = MarkItDown().convert_stream(
        BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html",
            charset="utf-8",
            url="https://example.com/products/",
        ),
        default_title=True,
    )

    expected_link = (
        "[https://example.com/download.pdf]"
        '(https://example.com/download.pdf "https://example.com/download.pdf")'
    )

    assert result.markdown == expected_link


def test_html_path():
    result = (
        MarkItDown()
        .convert_uri("https://wms-docs.linyikj.com/guide/getting-started.html")
        .markdown
    )
    print(result)
