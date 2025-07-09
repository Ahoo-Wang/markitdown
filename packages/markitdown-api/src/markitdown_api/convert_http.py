from enum import Enum
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


class HttpMethod(str, Enum):
    GET = "get"
    POST = "post"
    PUT = "put"


class ConvertHttpRequest(ConvertRequest):
    url: str = Field(description=HTTP_DESCRIPTION, pattern=HTTP_PATTERN)
    method: HttpMethod = Field(
        default=HttpMethod.GET,
        description="HTTP method to be used. ",
    )
    headers: dict | None = Field(
        default=None,
        description="Headers to be passed to the HTTP request. ",
        examples=[{"Authorization": "Bearer <token>"}],
    )


class ConvertHttpResponse(ConvertResult):
    mime_type: str = Field(default="", description="Mime type of the data")
    data_size: int = Field(default=0, description="Size of the data in bytes")


router = APIRouter(prefix="/convert/http", tags=[TAG])


def _convert_http(request: ConvertHttpRequest) -> ConvertHttpResponse:
    response = requests.request(
        request.method.value, request.url, headers=request.headers
    )
    data_size = len(response.content)
    convert_result = build_markitdown(request.llm).convert_response(
        response,
        llm_prompt=request.get_llm_options(),
        keep_data_uris=request.keep_data_uris,
    )
    return ConvertHttpResponse(
        title=convert_result.title,
        markdown=convert_result.markdown,
        data_size=data_size,
    )


@router.post(path="", response_model=ConvertHttpResponse)
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
