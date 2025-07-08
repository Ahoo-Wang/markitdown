from typing import Annotated

import requests
from fastapi import Body, APIRouter
from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    MarkdownResponse,
)
from markitdown_api.commons import build_markitdown
from pydantic import Field

TAG = "Convert Http"

HTTP_DESCRIPTION = """
The Uniform Resource Identifier (URI) to be converted.
Supported schemes are: http:, https:.
Example: https://example.com/document.docx
"""
HTTP_PATTERN = "^(http|https)://"


class ConvertHttpRequest(ConvertRequest):
    url: str = Field(description=HTTP_DESCRIPTION, pattern=HTTP_PATTERN)
    headers: dict | None = Field(
        default=None,
        description="Headers to be passed to the HTTP request. "
        "Example: {'Authorization': 'Bearer <token>'}",
    )


router = APIRouter(prefix="/convert/http", tags=[TAG])


def _convert_http(request: ConvertHttpRequest) -> ConvertResult:
    response = requests.get(request.url, headers=request.headers)
    convert_result = build_markitdown(request.llm).convert_response(
        response, llm_prompt=request.get_llm_options()
    )
    return ConvertResult(title=convert_result.title, markdown=convert_result.markdown)


@router.post(path="", response_model=ConvertResult)
async def convert_http(
    request: Annotated[
        ConvertHttpRequest, Body(examples=[{"url": "https://wow.ahoo.me/"}])
    ]
):
    return _convert_http(request)


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_uri_markdown(
    request: Annotated[
        ConvertHttpRequest, Body(examples=[{"url": "https://wow.ahoo.me/"}])
    ]
):
    return _convert_http(request).markdown
