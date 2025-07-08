from io import BufferedReader
from typing import Annotated

from fastapi import APIRouter, UploadFile, File, Form

from markitdown import StreamInfo
from markitdown_api.commons import build_markitdown
from markitdown_api.api_types import ConvertResult, LlmOptions, MarkdownResponse

TAG = "Convert File"

router = APIRouter(
    prefix="/convert/file",
    tags=[TAG],
)


def _convert_file(
    file: UploadFile,
    openai_base_url: str = "",
    openai_api_key: str = "",
    llm_model: str = "",
    llm_prompt: str = "",
) -> ConvertResult:
    stream_info = StreamInfo(mimetype=file.content_type)
    openai_options = LlmOptions(
        open_ai_api_key=openai_api_key,
        open_ai_base_url=openai_base_url,
        model=llm_model,
    )
    with BufferedReader(file.file) as buffered_reader:
        convert_result = build_markitdown(openai_options).convert_stream(
            buffered_reader, stream_info=stream_info, llm_prompt=llm_prompt
        )
        return ConvertResult(
            title=convert_result.title, markdown=convert_result.markdown
        )


@router.post(path="", response_model=ConvertResult)
async def convert_file(
    file: Annotated[UploadFile, File()],
    openai_base_url: Annotated[str, Form()] = "",
    openai_api_key: Annotated[str, Form()] = "",
    llm_model: Annotated[str, Form()] = "",
    llm_prompt: Annotated[str, Form()] = "",
):
    return _convert_file(file, openai_base_url, openai_api_key, llm_model, llm_prompt)


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_file_markdown(
    file: Annotated[UploadFile, File()],
    openai_base_url: Annotated[str, Form()] = "",
    openai_api_key: Annotated[str, Form()] = "",
    llm_model: Annotated[str, Form()] = "",
    llm_prompt: Annotated[str, Form()] = "",
):
    return _convert_file(
        file, openai_base_url, openai_api_key, llm_model, llm_prompt
    ).markdown
