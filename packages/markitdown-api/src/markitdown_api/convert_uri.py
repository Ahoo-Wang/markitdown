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


class ConvertUrlRequest(ConvertRequest):
    uri: str = Field(description=URI_DESCRIPTION, pattern=URI_PATTERN)


router = APIRouter(prefix="/convert/uri", tags=[TAG])


def _convert_uri(uri: str, llm_options: LlmOptions | None = None) -> ConvertResult:
    llm_prompt = llm_options.prompt if llm_options else ""
    convert_result = build_markitdown(llm_options).convert_uri(
        uri, llm_prompt=llm_prompt
    )
    return ConvertResult(title=convert_result.title, markdown=convert_result.markdown)


@router.post(path="", response_model=ConvertResult)
async def convert_uri(
    request: Annotated[
        ConvertUrlRequest, Body(examples=[{"uri": "https://wow.ahoo.me/"}])
    ]
):
    return _convert_uri(request.uri, request.llm)


@router.get(path="", response_model=ConvertResult)
async def convert_uri(uri: Annotated[str, URI_QUERY]):
    """
    The Uniform Resource Identifier (URI) to be converted.
    Supported schemes include 'http://', 'https://', 'file://', and custom protocols understood by MarkItDown.
    Example: https://example.com/document.docx
    """
    return _convert_uri(uri)


@router.get(path="/markdown", response_class=MarkdownResponse)
async def convert_uri_markdown(uri: Annotated[str, URI_QUERY]):
    return _convert_uri(uri).markdown
