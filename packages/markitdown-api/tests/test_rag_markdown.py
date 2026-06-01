from markitdown import DocumentConverterResult

from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import ConvertRequest, RagOptions
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
        optimize_markdown_for_rag(markdown)
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
