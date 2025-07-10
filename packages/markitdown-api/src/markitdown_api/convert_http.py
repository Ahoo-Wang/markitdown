from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Annotated, Any

import requests
from fastapi import Body, APIRouter
from pydantic import Field
from requests.utils import CaseInsensitiveDict

from markitdown_api.ApiConverter import ApiConverter
from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    MarkdownResponse,
    ConvertResponse,
    StreamMetadata,
)

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


def _parse_mime_type_from_content_type(content_type: str) -> str | None:
    if not content_type:
        return None

    parts = content_type.split(";")
    return parts.pop(0).strip()


def _parse_last_modified_timestamp(headers: CaseInsensitiveDict[str]) -> int | None:
    last_modified_str = headers.get("Last-Modified")
    if not last_modified_str:
        return None
    last_modified = parsedate_to_datetime(last_modified_str)
    return int(last_modified.timestamp())


class HttpApiConverter(ApiConverter):
    def __init__(self, request: ConvertHttpRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> ConvertResult:
        response = requests.request(
            self.request.method.value, self.request.url, headers=self.request.headers
        )
        data_size = len(response.content)
        last_modified = _parse_last_modified_timestamp(response.headers)
        mimetype = _parse_mime_type_from_content_type(
            response.headers.get("Content-Type")
        )
        self.metadata = StreamMetadata(
            data_size=data_size, mimetype=mimetype, last_modified=last_modified
        )
        result = self.markitdown.convert_response(response, **kwargs)
        return ConvertResult(markdown=result.markdown, title=result.title)


router = APIRouter(prefix="/convert/http", tags=[TAG])


@router.post(path="", response_model=ConvertResponse)
async def convert_http(
    request: Annotated[
        ConvertHttpRequest, Body(examples=[{"url": "https://wow.ahoo.me/"}])
    ]
):
    return HttpApiConverter(request).convert()


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_uri_markdown(
    request: Annotated[
        ConvertHttpRequest, Body(examples=[{"url": "https://wow.ahoo.me/"}])
    ]
):
    return HttpApiConverter(request).convert().result.markdown
