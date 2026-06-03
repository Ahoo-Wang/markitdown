from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

import requests
from fastapi import Body, APIRouter
from requests.utils import CaseInsensitiveDict

from markitdown import DocumentConverterResult, StreamInfo
from markitdown_api._utils import (
    is_yuque_api_url,
    _parse_last_modified_timestamp,
    _parse_mime_type_from_content_type,
)
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    MarkdownResponse,
    ConvertResponse,
    StreamMetadata,
)
from markitdown_api.convert_http_request import ConvertHttpRequest
from markitdown_api.convert_yuque_api import YuQueApiConverter
from markitdown_api.commons import should_verify_http_ssl

TAG = "Convert Http"


def _same_origin_referer(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _has_header(headers: dict | None, header_name: str) -> bool:
    return header_name in CaseInsensitiveDict(headers or {})


def _headers_with_same_origin_referer(url: str, headers: dict | None) -> dict:
    request_headers = dict(headers or {})
    if not _has_header(request_headers, "Referer"):
        request_headers["Referer"] = _same_origin_referer(url)
    return request_headers


class HttpApiConverter(ApiConverter):
    def __init__(self, request: ConvertHttpRequest):
        super().__init__(request)

    def _request(self, headers: dict | None) -> requests.Response:
        return requests.request(
            method=self.request.method.value,
            url=self.request.url,
            headers=_headers_with_same_origin_referer(self.request.url, headers),
            verify=should_verify_http_ssl(),
        )

    def _internal_convert(self, **kwargs: Any) -> DocumentConverterResult:
        response = self._request(headers=self.request.headers)
        data_size = len(response.content)
        last_modified = _parse_last_modified_timestamp(response.headers)
        mimetype = _parse_mime_type_from_content_type(
            response.headers.get("Content-Type")
        )
        self.metadata = StreamMetadata(
            data_size=data_size, mimetype=mimetype, last_modified=last_modified
        )
        stream_info = StreamInfo(mimetype=mimetype, charset=self.request.charset)
        return self.markitdown.convert_response(
            response=response, stream_info=stream_info, **kwargs
        )


router = APIRouter(prefix="/convert/http", tags=[TAG])


@router.post(path="", response_model=ConvertResponse)
async def convert_http(
    request: Annotated[
        ConvertHttpRequest, Body(examples=[{"url": "https://wow.ahoo.me/"}])
    ]
):
    if is_yuque_api_url(request.url):
        return YuQueApiConverter(request).convert()
    return HttpApiConverter(request).convert()


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_http_markdown(
    request: Annotated[
        ConvertHttpRequest, Body(examples=[{"url": "https://wow.ahoo.me/"}])
    ]
):
    if is_yuque_api_url(request.url):
        return YuQueApiConverter(request).convert().result.markdown
    return HttpApiConverter(request).convert().result.markdown
