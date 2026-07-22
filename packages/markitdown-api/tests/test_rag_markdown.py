from markitdown import DocumentConverterResult

from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import ConvertRequest, RagOptions
from markitdown_api.oss_image_upload import replace_data_images_with_oss_urls
from markitdown_api.rag_markdown import optimize_markdown_for_rag


def test_optimize_markdown_for_rag_cleans_pdf_markdown_for_chunking():
    markdown = """产品目录
HELLO Industry
+
2

目录
CE认证服务
4

![PDF page 4 image 1](https://cdn.example.com/page4.jpg)

工业安全解决方案
可编程安全控制器 -- sAMOs

®
 PRO
| 功能/版本 | 标准版 |
| ----- | --- |
| PL | Level e |
"""

    assert (
        optimize_markdown_for_rag(markdown, heading_keywords=["目录", "工业安全解决方案"])
        == """# 产品目录
HELLO Industry

## 目录
CE认证服务

![CE认证服务 - PDF page 4 image 1](https://cdn.example.com/page4.jpg)

## 工业安全解决方案
可编程安全控制器 -- sAMOs® PRO
| 功能/版本 | 标准版 |
| ----- | --- |
| PL | Level e |"""
    )


def test_optimize_markdown_for_rag_does_not_embed_business_heading_keywords():
    markdown = """产品目录

工业通讯
这个短行来自某个业务文档，不应被通用规则硬编码成标题。
"""

    assert (
        optimize_markdown_for_rag(markdown)
        == """# 产品目录

工业通讯
这个短行来自某个业务文档，不应被通用规则硬编码成标题。"""
    )
    assert (
        optimize_markdown_for_rag(markdown, heading_keywords=["工业通讯"])
        == """# 产品目录

## 工业通讯
这个短行来自某个业务文档，不应被通用规则硬编码成标题。"""
    )


def test_optimize_markdown_for_rag_does_not_remove_numbers_inside_tables():
    markdown = """参数
| 页码 | 数值 |
| --- | --- |
| 4 | 24 V |
5
"""

    assert (
        optimize_markdown_for_rag(markdown)
        == """# 参数
| 页码 | 数值 |
| --- | --- |
| 4 | 24 V |"""
    )


def test_optimize_markdown_for_rag_preserves_fenced_code_blocks():
    markdown = """Notebook
2

```python
  print("hello")
  2
+
```

目录
3
"""

    assert (
        optimize_markdown_for_rag(markdown, heading_keywords=["目录"])
        == """# Notebook

```python
  print("hello")
  2
+
```

## 目录"""
    )


def test_optimize_markdown_for_rag_preserves_long_fences_with_shorter_inner_fence():
    markdown = """Notebook

````python
print("before")
```
2
+
````

目录
"""

    assert (
        optimize_markdown_for_rag(markdown, heading_keywords=["目录"])
        == """# Notebook

````python
print("before")
```
2
+
````

## 目录"""
    )


def test_optimize_markdown_for_rag_does_not_merge_registered_mark_with_long_suffix():
    markdown = """Product

®
this suffix is too long
"""

    assert (
        optimize_markdown_for_rag(markdown)
        == """# Product

®
this suffix is too long"""
    )


def test_optimize_markdown_for_rag_uses_document_title_as_stable_h1():
    markdown = """从一个组件开始
这个示例端子
开 始
"""

    assert (
        optimize_markdown_for_rag(markdown, document_title="示例工业公司介绍（for 示例客户）")
        == """# 示例工业公司介绍（for 示例客户）
从一个组件开始
这个示例端子
开始"""
    )


def test_optimize_markdown_for_rag_does_not_repeat_matching_source_title():
    markdown = """Example Document
Body text
"""

    assert (
        optimize_markdown_for_rag(markdown, document_title="Example Document")
        == """# Example Document
Body text"""
    )


def test_optimize_markdown_for_rag_preserves_dots_in_document_title():
    markdown = """manual.v2
Body text
"""

    assert (
        optimize_markdown_for_rag(markdown, document_title="manual.v2")
        == """# manual.v2
Body text"""
    )


def test_optimize_markdown_for_rag_keeps_repeated_section_headings():
    markdown = """Report
## Summary
First section
## Summary
Second section
"""

    assert (
        optimize_markdown_for_rag(markdown)
        == """# Report
## Summary
First section
## Summary
Second section"""
    )


def test_optimize_markdown_for_rag_keeps_repeated_content_dates():
    markdown = """Events
2024/6/1
First event
2024/6/1
Second event
2024/6/1
Third event
"""

    optimized = optimize_markdown_for_rag(markdown)

    assert optimized.count("2024/6/1") == 3


def test_optimize_markdown_for_rag_keeps_distinct_dated_rows():
    markdown = """Schedule
2024/6/1 Alpha release 1
2024/6/2 Alpha release 2
2024/6/3 Alpha release 3
"""

    optimized = optimize_markdown_for_rag(markdown)

    assert "2024/6/1 Alpha release 1" in optimized
    assert "2024/6/2 Alpha release 2" in optimized
    assert "2024/6/3 Alpha release 3" in optimized


def test_optimize_markdown_for_rag_keeps_repeated_dated_rows_with_numeric_suffixes():
    markdown = """Report
2024/6/1 Release phase 1
2024/6/1 Release phase 2
2024/6/1 Release phase 3
"""

    optimized = optimize_markdown_for_rag(markdown)

    assert "2024/6/1 Release phase 1" in optimized
    assert "2024/6/1 Release phase 2" in optimized
    assert "2024/6/1 Release phase 3" in optimized


def test_optimize_markdown_for_rag_removes_pdf_footers_and_preserves_cross_page_images():
    markdown = """产品介绍
2024/6/1 ACME ELECTRIC - DOC 2
![PDF page 2 image 1](data:image/png;base64,c2hhcmVk)

功能安全
| 2024/6/1 | ACME ELECTRIC - | DOC | 3 |
| ---------- | ----------------- | -- | - |
![PDF page 3 image 1](data:image/png;base64,c2hhcmVk)

安全服务
2024/6/1 ACME ELECTRIC - DOC 4
![PDF page 4 image 2](https://cdn.example.com/unique.png)

附录
2024/6/1 ACME ELECTRIC - DOC 5
Closing text
"""

    optimized = optimize_markdown_for_rag(markdown, document_title="示例工业公司介绍")

    assert optimized.startswith("# 示例工业公司介绍\n")
    assert "2024/6/1" not in optimized
    assert optimized.count("data:image/png;base64,c2hhcmVk") == 2
    assert optimized.count("https://cdn.example.com/unique.png") == 1
    assert "![产品介绍 - PDF page 2 image 1]" in optimized


def test_optimize_markdown_for_rag_only_removes_standalone_date_at_pdf_image_boundary():
    markdown = """Report
2024/6/1 ACME DOC 1
![PDF page 1 image 1](https://cdn.example.com/page-1.png)
Details
2024/6/1 ACME DOC 2
![PDF page 2 image 1](https://cdn.example.com/page-2.png)
Business date
2024/6/1
Description continues
2024/6/1 ACME DOC 3
![PDF page 3 image 1](https://cdn.example.com/page-3.png)
Product page
2024/6/1
![PDF page 4 image 1](https://cdn.example.com/product.png)
"""

    optimized = optimize_markdown_for_rag(markdown)

    assert "Business date\n2024/6/1\nDescription continues" in optimized
    assert "Product page\n2024/6/1\n![" not in optimized
    assert "![Product page - PDF page 4 image 1]" in optimized


def test_api_converter_applies_rag_optimizer_by_default(monkeypatch):
    markdown = "产品目录\n2\n"

    class StubApiConverter(ApiConverter):
        def _internal_convert(self, **kwargs):
            return DocumentConverterResult(markdown=markdown)

    monkeypatch.setattr(
        "markitdown_api.api_converter.replace_data_images_with_oss_urls",
        lambda markdown_value: markdown_value,
    )

    assert StubApiConverter(ConvertRequest()).convert().result.markdown == "# 产品目录"
    assert (
        StubApiConverter(ConvertRequest(rag=RagOptions(enabled=False)))
        .convert()
        .result.markdown
        == markdown
    )


def test_api_converter_uses_configured_rag_heading_keywords(monkeypatch):
    markdown = "产品目录\n\n目录\n"

    class StubApiConverter(ApiConverter):
        def _internal_convert(self, **kwargs):
            return DocumentConverterResult(markdown=markdown)

    monkeypatch.setattr(
        "markitdown_api.api_converter.replace_data_images_with_oss_urls",
        lambda markdown_value: markdown_value,
    )

    assert (
        StubApiConverter(ConvertRequest(rag=RagOptions(heading_keywords=["目录"])))
        .convert()
        .result.markdown
        == "# 产品目录\n\n## 目录"
    )


def test_api_converter_cleans_before_upload_without_removing_image_references(
    monkeypatch,
):
    markdown = """Document
![PDF page 1 image 1](data:image/png;base64,c2hhcmVk)
![PDF page 2 image 1](data:image/png;base64,c2hhcmVk)
"""
    observed = []

    class StubApiConverter(ApiConverter):
        def _internal_convert(self, **kwargs):
            return DocumentConverterResult(markdown=markdown, title="Document")

    def fake_upload(markdown_value):
        observed.append(markdown_value)
        return markdown_value.replace(
            "data:image/png;base64,c2hhcmVk", "https://cdn.example.com/shared.png"
        )

    monkeypatch.setattr(
        "markitdown_api.api_converter.replace_data_images_with_oss_urls", fake_upload
    )

    result = StubApiConverter(ConvertRequest()).convert().result.markdown

    assert len(observed) == 1
    assert observed[0].splitlines().count("# Document") == 1
    assert observed[0].splitlines().count("Document") == 0
    assert observed[0].count("data:image/png;base64,c2hhcmVk") == 2
    assert result.count("https://cdn.example.com/shared.png") == 2


def test_api_converter_uploads_wrapped_data_uri_after_rag_cleanup(monkeypatch):
    markdown = """Document
![chart](data:image/png;base64,QUJD
REVG)
![PDF page 2 image 1](https://cdn.example.com/next.png)
"""
    upload_calls = []

    class StubApiConverter(ApiConverter):
        def _internal_convert(self, **kwargs):
            return DocumentConverterResult(markdown=markdown, title="Document")

    class FakeUploader:
        def upload_image(self, mimetype, content):
            upload_calls.append((mimetype, content))
            return "https://cdn.example.com/chart.png"

    monkeypatch.setattr(
        "markitdown_api.api_converter.replace_data_images_with_oss_urls",
        lambda markdown_value: replace_data_images_with_oss_urls(
            markdown_value, uploader_factory=FakeUploader
        ),
    )

    result = StubApiConverter(ConvertRequest()).convert().result.markdown

    assert result == (
        "# Document\n"
        "![chart](https://cdn.example.com/chart.png)\n"
        "![Document - PDF page 2 image 1](https://cdn.example.com/next.png)"
    )
    assert upload_calls == [("image/png", b"ABCDEF")]
