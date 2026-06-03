from typing import Annotated, Any

import requests
from fastapi import Body, APIRouter

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

TAG = "Convert Http"


class HttpApiConverter(ApiConverter):
    def __init__(self, request: ConvertHttpRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> DocumentConverterResult:
        response = requests.request(
            method=self.request.method.value,
            url=self.request.url,
            headers=self.request.headers,
            verify=False,
        )
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
