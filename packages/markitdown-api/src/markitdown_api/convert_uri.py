from typing import Annotated, Any

from fastapi import Query, Body, APIRouter
from pydantic import Field

from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    MarkdownResponse,
    ConvertResponse,
)

TAG = "Convert Uri"

URI_DESCRIPTION = """
The Uniform Resource Identifier (URI) to be converted.
Supported schemes are: file:, data:, http:, https:.
Example: https://example.com/document.docx
"""
URI_PATTERN = "^(file|data|http|https)://"

URI_QUERY = Query(description=URI_DESCRIPTION, pattern=URI_PATTERN)


class ConvertUriRequest(ConvertRequest):
    uri: str = Field(description=URI_DESCRIPTION, pattern=URI_PATTERN)


class UriApiConverter(ApiConverter):
    def __init__(self, request: ConvertUriRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> ConvertResult:
        result = self.markitdown.convert_uri(self.request.uri, **kwargs)
        return ConvertResult(title=result.title, markdown=result.markdown)


router = APIRouter(prefix="/convert/uri", tags=[TAG])


@router.post(path="", response_model=ConvertResponse)
async def convert_uri(
    request: Annotated[
        ConvertUriRequest, Body(examples=[{"uri": "https://wow.ahoo.me/"}])
    ]
):
    return UriApiConverter(request).convert()


@router.get(path="", response_model=ConvertResponse)
async def convert_uri(uri: Annotated[str, URI_QUERY]):
    """
    The Uniform Resource Identifier (URI) to be converted.
    Supported schemes include 'http://', 'https://', 'file://', and custom protocols understood by MarkItDown.
    Example: https://example.com/document.docx
    """
    return UriApiConverter(ConvertUriRequest(uri=uri)).convert()


@router.get(path="/markdown", response_class=MarkdownResponse)
async def convert_uri_markdown(uri: Annotated[str, URI_QUERY]):
    return UriApiConverter(ConvertUriRequest(uri=uri)).convert().result.markdown
