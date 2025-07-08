from io import BytesIO

from fastapi import APIRouter, HTTPException
from pydantic import Field

from markitdown import StreamInfo
from markitdown_api.api_types import ConvertRequest, ConvertResult
from markitdown_api.commons import build_markitdown

TAG = "Convert Text"


class ConvertTextRequest(ConvertRequest):
    text: str
    mimetype: str = Field(
        default="text/plain", description="MIME type of the input text"
    )


router = APIRouter(
    prefix="/convert/text",
    tags=[TAG],
)


@router.post(path="", response_model=ConvertResult)
async def convert_text(request: ConvertTextRequest):
    if not request.text or len(request.text) > 100_000:
        raise HTTPException(status_code=400, detail="Invalid input text length")

    text_binary = request.text.encode("utf-8")
    binary_io = BytesIO(text_binary)

    stream_info = StreamInfo(mimetype=request.mimetype)
    llm_prompt = request.llm.prompt if request.llm else ""
    convert_result = build_markitdown(request.llm).convert_stream(
        stream=binary_io, stream_info=stream_info, llm_prompt=llm_prompt
    )

    return {"title": convert_result.title, "markdown": convert_result.markdown}
