from enum import Enum

from pydantic import Field

from markitdown_api.api_types import (
    ConvertRequest,
)

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
