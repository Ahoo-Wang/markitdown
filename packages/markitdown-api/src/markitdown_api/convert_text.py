from io import BytesIO
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from markitdown import StreamInfo
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    StreamMetadata,
    ConvertResponse,
)

TAG = "Convert Text"


class ConvertTextRequest(ConvertRequest):
    text: str = Field(min_length=1, description="Text to convert")
    mimetype: str = Field(
        default="text/plain", description="MIME type of the input text"
    )


class TextApiConverter(ApiConverter):
    def __init__(self, request: ConvertTextRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> ConvertResult:
        text_binary = self.request.text.encode("utf-8")
        self.metadata = StreamMetadata(
            mimetype=self.request.mimetype,
            data_size=len(text_binary),
        )
        binary_io = BytesIO(text_binary)

        stream_info = StreamInfo(mimetype=self.request.mimetype)
        result = self.markitdown.convert_stream(
            stream=binary_io, stream_info=stream_info, **kwargs
        )

        return ConvertResult(markdown=result.markdown, title=result.title)


router = APIRouter(
    prefix="/convert/text",
    tags=[TAG],
)


@router.post(path="", response_model=ConvertResponse)
async def convert_text(request: ConvertTextRequest):
    return TextApiConverter(request).convert()
