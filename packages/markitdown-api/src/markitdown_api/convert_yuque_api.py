import json
import re
from datetime import datetime
from html import unescape
from io import BytesIO
from typing import Annotated, Any, List
from urllib.parse import unquote

import requests
from fastapi import Body, APIRouter
from pydantic import BaseModel, Field

from markitdown import DocumentConverterResult, StreamInfo
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    MarkdownResponse,
    ConvertResponse,
    StreamMetadata,
)
from markitdown_api.convert_http_request import ConvertHttpRequest

TAG = "Convert YuQue Doc"

EXAMPLE = "https://{login}.yuque.com/api/docs/{doc_url}?book_id={book_id}&include_contributors=true&include_like=true&include_hits=true&merge_dynamic_data=false"
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


class YuQueBookToc(BaseModel):
    type: str = Field(default="")
    title: str = Field(default="")
    url: str = Field(default="")
    api_doc_url: str = Field(default="")


class YuQueBook(BaseModel):
    id: int = Field(default=0)
    name: str = Field(default="")
    toc: List[YuQueBookToc] = Field(default=[])


@router.get(path="/book", response_model=YuQueBook)
async def convert_yuque_book(url: str):
    app_data = extract_yuque_app_data_url(url)
    login = app_data.get("organization").get("login")
    book_json = app_data.get("book")
    book_id = book_json.get("id")
    name = book_json.get("name")
    toc_json = book_json.get("toc")
    toc_list = []
    for toc in toc_json:
        url = toc.get("url")
        api_doc_url = ""
        if url:
            api_doc_url = f"https://{login}.yuque.com/api/docs/{url}?book_id={book_id}&include_contributors=true&include_like=true&include_hits=true&merge_dynamic_data=false"
        book_toc = YuQueBookToc(
            type=toc.get("type"),
            title=toc.get("title"),
            url=url,
            api_doc_url=api_doc_url,
        )
        toc_list.append(book_toc)

    return YuQueBook(id=book_id, name=name, toc=toc_list)


def extract_yuque_app_data_url(url):
    response = requests.get(url=url)
    result = response.content.decode("utf-8")
    if response.status_code != 200:
        raise Exception(f"Failed to get YuQue API URL: {response.status_code} {result}")
    return extract_yuque_app_data(result)


def extract_yuque_app_data(html_text):
    """
    从HTML文本中提取window.appData的编码字符串，解码并转换为JSON对象
    :param html_text: 包含appData的HTML文本
    :return: 解析后的JSON字典
    """
    # 使用正则表达式匹配 window.appData 赋值语句
    pattern = r'window\.appData\s*=\s*JSON\.parse\(decodeURIComponent\("([^"]+)"\)\)'
    match = re.search(pattern, html_text)

    if not match:
        raise ValueError("No appData data found")

    # 提取URI编码的字符串
    encoded_str = match.group(1)

    # 解码URI组件
    decoded_str = unquote(encoded_str)

    # 将解码后的字符串解析为JSON
    return json.loads(decoded_str)
