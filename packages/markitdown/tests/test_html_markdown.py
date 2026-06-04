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


def test_html_path():
    result = (
        MarkItDown()
        .convert_uri("https://wms-docs.linyikj.com/guide/getting-started.html")
        .markdown
    )
    print(result)
