from typing import Annotated

from fastapi import Query, Body, APIRouter
from pydantic import Field

from markitdown_api.api_types import (
    ConvertRequest,
    LlmOptions,
    ConvertResult,
    MarkdownResponse,
)
from markitdown_api.commons import build_markitdown

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


router = APIRouter(prefix="/convert/uri", tags=[TAG])


def _convert_uri(request: ConvertUriRequest) -> ConvertResult:
    convert_result = build_markitdown(request.llm).convert_uri(
        request.uri,
        llm_prompt=request.get_llm_options(),
        keep_data_uris=request.keep_data_uris,
    )
    return ConvertResult(title=convert_result.title, markdown=convert_result.markdown)


@router.post(path="", response_model=ConvertResult)
async def convert_uri(
    request: Annotated[
        ConvertUriRequest, Body(examples=[{"uri": "https://wow.ahoo.me/"}])
    ]
):
    return _convert_uri(request)


@router.get(path="", response_model=ConvertResult)
async def convert_uri(uri: Annotated[str, URI_QUERY]):
    """
    The Uniform Resource Identifier (URI) to be converted.
    Supported schemes include 'http://', 'https://', 'file://', and custom protocols understood by MarkItDown.
    Example: https://example.com/document.docx
    """
    return _convert_uri(ConvertUriRequest(uri=uri))


@router.get(path="/markdown", response_class=MarkdownResponse)
async def convert_uri_markdown(uri: Annotated[str, URI_QUERY]):
    return _convert_uri(ConvertUriRequest(uri=uri)).markdown
