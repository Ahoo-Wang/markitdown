from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Annotated, Tuple

import requests
from fastapi import Body, APIRouter
from requests.utils import CaseInsensitiveDict

from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    MarkdownResponse,
)
from markitdown_api.commons import build_markitdown
from pydantic import Field, BaseModel

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


class HttpResponseMetadata(BaseModel):
    mimetype: str | None = Field(default=None, description="Mime type of the data")
    data_size: int | None = Field(default=None, description="Size of the data in bytes")
    last_modified: int | None = Field(
        default=None,
        description="Last modified timestamp(seconds) of the data",
    )


class ConvertHttpResponse(ConvertResult):
    metadata: HttpResponseMetadata = Field(
        description="Metadata of the http response",
    )


router = APIRouter(prefix="/convert/http", tags=[TAG])


def __parse_content_type(headers: CaseInsensitiveDict[str]) -> str | None:
    content_type = headers.get("Content-Type")
    if not content_type:
        return None

    parts = content_type.split(";")
    return parts.pop(0).strip()


def __parse_last_modified_timestamp(headers: CaseInsensitiveDict[str]) -> int | None:
    last_modified_str = headers.get("Last-Modified")
    if not last_modified_str:
        return None
    last_modified = parsedate_to_datetime(last_modified_str)
    return int(last_modified.timestamp())


def _convert_http(request: ConvertHttpRequest) -> ConvertHttpResponse:
    response = requests.request(
        request.method.value, request.url, headers=request.headers
    )
    data_size = len(response.content)
    last_modified = __parse_last_modified_timestamp(response.headers)
    mimetype = __parse_content_type(response.headers)
    metadata = HttpResponseMetadata(
        data_size=data_size, mimetype=mimetype, last_modified=last_modified
    )
    convert_result = build_markitdown(request.llm).convert_response(
        response,
        llm_prompt=request.get_llm_options(),
        keep_data_uris=request.keep_data_uris,
    )

    return ConvertHttpResponse(
        title=convert_result.title,
        markdown=convert_result.markdown,
        metadata=metadata,
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
