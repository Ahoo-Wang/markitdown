from datetime import datetime
from html import unescape
from io import BytesIO
from typing import Annotated, Any

import requests
from fastapi import Body, APIRouter

from markitdown import DocumentConverterResult, StreamInfo
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    MarkdownResponse,
    ConvertResponse,
    StreamMetadata,
)
from markitdown_api.convert_http_request import ConvertHttpRequest

TAG = "Convert YuQue Doc"

EXAMPLE = "https://{repo}.yuque.com/api/docs/{doc_id}?book_id={book_id}&include_contributors=true&include_like=true&include_hits=true&merge_dynamic_data=false"
HTTP_DESCRIPTION = f"""
The YuQue API URL to be converted.
Supported schemes are: http:, https:.
Example: {EXAMPLE} 
"""


class YuQueApiConverter(ApiConverter):
    def __init__(self, request: ConvertHttpRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> DocumentConverterResult:
        response = requests.get(
            url=self.request.url,
            headers=self.request.headers,
        )
        result = response.json()
        if response.status_code != 200:
            raise Exception(
                f"Failed to get YuQue API URL: {response.status_code} {result}"
            )

        data = result.get("data")
        title = data.get("title")
        # dateformat: 2025-05-19T07:20:41.000Z
        updated_at_str = data.get("updated_at")
        updated_at = datetime.strptime(updated_at_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        content = data.get("content")
        content = unescape(content)
        text_binary = content.encode("utf-8")
        data_size = len(text_binary)
        binary_io = BytesIO(text_binary)

        self.metadata = StreamMetadata(
            data_size=data_size,
            mimetype="text/html",
            last_modified=int(updated_at.timestamp()),
        )
        stream_info = StreamInfo(
            mimetype=self.metadata.mimetype, charset=self.request.charset
        )
        converted_result = self.markitdown.convert_stream(
            stream=binary_io, stream_info=stream_info, **kwargs
        )
        converted_result.title = title
        return converted_result


router = APIRouter(prefix="/convert/yuque-api", tags=[TAG])


@router.post(path="", response_model=ConvertResponse)
async def convert_yuque_api(
    request: Annotated[ConvertHttpRequest, Body(examples=[{"url": EXAMPLE}])]
):
    return YuQueApiConverter(request).convert()


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_yuque_api_markdown(
    request: Annotated[ConvertHttpRequest, Body(examples=[{"url": EXAMPLE}])]
):
    return YuQueApiConverter(request).convert().result.markdown
